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

    # --- Signierte GET-Requests --------------------------------------------
    def _get(self, path: str, _retry_auth: bool = True, **params: Any) -> dict:
        self._ensure_token()
        params.update({
            "clientId": self.client_id,
            "accessToken": self.access_token,
            "date": self._now_ms(),
        })
        resp = self.session.get(
            f"{self.endpoint}/{path.lstrip('/')}", params=params, timeout=_HTTP_TIMEOUT
        )
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("errcode", 0):
            if body["errcode"] in _AUTH_ERRCODES and _retry_auth:
                logger.info("TTLock-Token ungültig (errcode=%s) – Neu-Login + Retry.",
                            body["errcode"])
                self.login()
                return self._get(path, _retry_auth=False, **params)
            raise TTLockError(
                f"{path}: errcode={body['errcode']} {body.get('errmsg')} "
                f"({body.get('description', '')})",
                errcode=body["errcode"],
            )
        return body

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

    def lock_records(self, lock_id: int, start_ms: int, end_ms: int,
                     page_no: int = 1, page_size: int = 100) -> dict:
        return self._get("v3/lockRecord/list", lockId=lock_id,
                         startDate=start_ms, endDate=end_ms,
                         pageNo=page_no, pageSize=page_size)
