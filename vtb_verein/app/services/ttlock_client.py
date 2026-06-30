"""
TTLockClient – dünner, signierter HTTP-Client für die TTLock-Cloud-API.

Die App ist Orchestrierungs-/Verwaltungsschicht über der TTLock-Cloud (Quelle der
Wahrheit). Dieser Client kapselt ausschließlich die HTTP-Ebene:

  * OAuth2-Login (`grant_type=password`, Passwort als MD5-Hex) und Token-Refresh
    (`grant_type=refresh_token`), proaktiv vor Ablauf.
  * Signierte Requests: jeder Call trägt `clientId`, `accessToken` und `date`
    (13-stelliger ms-Timestamp).
  * TTLock-Fehler-Envelope: `errcode != 0` → :class:`TTLockError` (auch bei HTTP 200).

**Kein DB-Zugriff.** Token-Persistenz erfolgt über den Callback ``on_token_update``;
die Domänen-/Orchestrierungslogik (``zutritt_service``) reicht den Persistenz-Hook
und den zuletzt gespeicherten Token-Stand herein.

Verifiziert (PoC 2026-06-29) gegen ``euapi.ttlock.com``. ``euopen.ttlock.com`` ist nur
das Entwickler-Portal und liefert auf ``/oauth2/token`` ein HTML-404.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

# errcodes, bei denen der Access-Token ungültig/abgelaufen ist → einmal neu einloggen.
_AUTH_ERRCODES = {10003}
# Token spätestens so lange vor Ablauf erneuern (TTLock-Tokens leben ~90 Tage).
_REFRESH_SKEW = timedelta(days=1)
_HTTP_TIMEOUT = 20


class TTLockError(RuntimeError):
    """Fehler aus dem TTLock-Envelope (`errcode != 0`) oder fehlgeschlagener Login."""

    def __init__(self, message: str, errcode: Optional[int] = None):
        super().__init__(message)
        self.errcode = errcode


class TTLockClient:
    """Signierter API-Client für genau ein TTLock-Konto."""

    def __init__(
        self,
        endpoint: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        *,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        uid: Optional[int] = None,
        on_token_update: Optional[Callable[[dict], None]] = None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at
        self.uid = uid
        self._on_token_update = on_token_update
        self.session = requests.Session()

    # --- Auth ---------------------------------------------------------------
    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _store_token(self, body: dict) -> None:
        """Token-Felder aus einer Token-Response übernehmen und persistieren lassen."""
        self.access_token = body.get("access_token")
        self.refresh_token = body.get("refresh_token", self.refresh_token)
        if body.get("uid") is not None:
            self.uid = body["uid"]
        expires_in = body.get("expires_in")
        self.token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            if expires_in else None
        )
        if self._on_token_update:
            self._on_token_update({
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expires_at": self.token_expires_at,
                "uid": self.uid,
            })

    def login(self) -> dict:
        """OAuth2 password-grant; Passwort als MD5 (lowercase hex)."""
        data = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "username": self.username,
            "password": self._md5(self.password),
            "grant_type": "password",
        }
        body = self._post_token(data)
        logger.info("TTLock-Login ok (uid=%s).", self.uid)
        return body

    def refresh(self) -> dict:
        """Access-Token via refresh_token erneuern."""
        data = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        body = self._post_token(data)
        logger.info("TTLock-Token erneuert (uid=%s).", self.uid)
        return body

    def _post_token(self, data: dict) -> dict:
        resp = self.session.post(
            f"{self.endpoint}/oauth2/token", data=data, timeout=_HTTP_TIMEOUT
        )
        resp.raise_for_status()
        body = resp.json()
        if "access_token" not in body:
            raise TTLockError(
                f"Token-Request fehlgeschlagen: errcode={body.get('errcode')} "
                f"{body.get('errmsg')} ({body.get('description', '')})",
                errcode=body.get("errcode"),
            )
        self._store_token(body)
        return body

    def _ensure_token(self) -> None:
        """Sorgt für einen gültigen Access-Token: Login bzw. proaktiver Refresh."""
        if not self.access_token:
            self.login()
            return
        if self.token_expires_at and datetime.now(timezone.utc) >= (
            self.token_expires_at - _REFRESH_SKEW
        ):
            try:
                self.refresh()
            except (requests.RequestException, TTLockError):
                logger.warning("TTLock-Refresh fehlgeschlagen – versuche Neu-Login.")
                self.login()

    # --- Signierte Requests ------------------------------------------------
    def _request(self, method: str, path: str, _retry_auth: bool = True,
                 **params: Any) -> dict:
        """Signierter Request (GET oder POST). Lese-Endpunkte und Gateway-Steuerung
        nutzen GET (verifiziert), Schreib-Endpunkte (IC-Card add/change/delete) POST
        (form-encoded) – TTLock signiert beide identisch über clientId+accessToken+date."""
        self._ensure_token()
        params.update({
            "clientId": self.client_id,
            "accessToken": self.access_token,
            "date": self._now_ms(),
        })
        url = f"{self.endpoint}/{path.lstrip('/')}"
        if method == "POST":
            resp = self.session.post(url, data=params, timeout=_HTTP_TIMEOUT)
        else:
            resp = self.session.get(url, params=params, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("errcode", 0):
            if body["errcode"] in _AUTH_ERRCODES and _retry_auth:
                logger.info("TTLock-Token ungültig (errcode=%s) – Neu-Login + Retry.",
                            body["errcode"])
                self.login()
                return self._request(method, path, _retry_auth=False, **params)
            raise TTLockError(
                f"{path}: errcode={body['errcode']} {body.get('errmsg')} "
                f"({body.get('description', '')})",
                errcode=body["errcode"],
            )
        return body

    def _get(self, path: str, **params: Any) -> dict:
        return self._request("GET", path, **params)

    def _post(self, path: str, **params: Any) -> dict:
        return self._request("POST", path, **params)

    # --- Read-only-Wrapper (Phase 1) ---------------------------------------
    def lock_list(self, page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/lock/list", pageNo=page_no, pageSize=page_size)

    def lock_detail(self, lock_id: int) -> dict:
        return self._get("v3/lock/detail", lockId=lock_id)

    def gateway_list(self, page_no: int = 1, page_size: int = 100) -> dict:
        """Account-weite Gateway-Liste – liefert als Einzige den Online-Status (`isOnline`)."""
        return self._get("v3/gateway/list", pageNo=page_no, pageSize=page_size)

    def gateway_list_by_lock(self, lock_id: int) -> dict:
        return self._get("v3/gateway/listByLock", lockId=lock_id)

    def ic_cards(self, lock_id: int, page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/identityCard/list", lockId=lock_id,
                         pageNo=page_no, pageSize=page_size)

    # Read-only Credential-Listen (Mirror): je Typ eine eigene paginierte Liste.
    # Achtung: die Listen-Endpunkte sind NICHT einheitlich `v3/<typ>/list` – Passcodes und
    # eKeys hängen unter `v3/lock/...` (lock-scoped), nur Fingerprint hat `v3/fingerprint/list`.
    # `v3/keyboardPwd/*` kennt kein /list (→ 404), `v3/key/list` wäre account-weit ohne lockId.
    # Modellabhängig – Schlösser ohne den jeweiligen Sensor können errcode liefern
    # (vom Aufrufer abgefangen).
    def fingerprints(self, lock_id: int, page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/fingerprint/list", lockId=lock_id,
                         pageNo=page_no, pageSize=page_size)

    def passcodes(self, lock_id: int, page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/lock/listKeyboardPwd", lockId=lock_id,
                         pageNo=page_no, pageSize=page_size)

    def ekeys(self, lock_id: int, page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/lock/listKey", lockId=lock_id,
                         pageNo=page_no, pageSize=page_size)

    # --- IC-Card-Schreiboperationen (über Gateway, Phase 2) ----------------
    # TTLock-Typ-Felder: 2 = „über Gateway/WLAN" (server-seitig, ohne Bluetooth).
    # startDate/endDate in ms; 0 = unbefristet. Ein neuer Chip braucht eine bereits
    # bekannte cardNumber (am Schloss per BLE gelesen oder per RFID-Leser erfasst).
    def ic_card_add(self, lock_id: int, card_number: str, card_name: str,
                    start_ms: int = 0, end_ms: int = 0, *, add_type: int = 2) -> dict:
        """IC-Karte an ein Schloss anlernen (v3/identityCard/add) → liefert `cardId`."""
        return self._post("v3/identityCard/add", lockId=lock_id, cardNumber=card_number,
                          cardName=card_name, startDate=start_ms, endDate=end_ms,
                          addType=add_type)

    def ic_card_change_period(self, lock_id: int, card_id: int,
                              start_ms: int = 0, end_ms: int = 0, *,
                              change_type: int = 2) -> dict:
        """Gültigkeitszeitraum einer IC-Karte ändern (v3/identityCard/changePeriod)."""
        return self._post("v3/identityCard/changePeriod", lockId=lock_id, cardId=card_id,
                          startDate=start_ms, endDate=end_ms, changeType=change_type)

    def ic_card_delete(self, lock_id: int, card_id: int, *, delete_type: int = 2) -> dict:
        """IC-Karte von einem Schloss entfernen (v3/identityCard/delete)."""
        return self._post("v3/identityCard/delete", lockId=lock_id, cardId=card_id,
                          deleteType=delete_type)

    def lock_records(self, lock_id: int, start_ms: int, end_ms: int,
                     page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/lockRecord/list", lockId=lock_id,
                         startDate=start_ms, endDate=end_ms,
                         pageNo=page_no, pageSize=page_size)

    # --- Steuer-Operationen (über Gateway) ---------------------------------
    # TTLock nutzt für diese Gateway-Kommandos denselben signierten Request-Stil
    # (clientId+accessToken+date) wie die Lese-Endpunkte; per PoC verifiziert (errcode 0).
    def unlock(self, lock_id: int) -> dict:
        """Schloss per Gateway fernöffnen (v3/lock/unlock)."""
        return self._get("v3/lock/unlock", lockId=lock_id)

    def remote_lock(self, lock_id: int) -> dict:
        """Schloss per Gateway fernverriegeln (v3/lock/lock; modellabhängig)."""
        return self._get("v3/lock/lock", lockId=lock_id)
