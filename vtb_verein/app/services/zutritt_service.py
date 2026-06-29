"""
ZutrittService – Domänen-Orchestrierung über der TTLock-Cloud (Phase 1: read-only).

Aufgaben:
- `inventar_sync()`  – Schlösser/Gateways aus der Cloud spiegeln (Akku, Online-Status).
- `logs_sync()`      – Zutrittslogs paginiert seit Cursor holen, idempotent (recordId)
                       speichern, Kartennummer → Chip → Mitglied auflösen, Cursor +
                       Status-Snapshot (letzter Schließvorgang) fortschreiben.

Der TTLock-Client wird aus der Env gebaut (ein Vereinskonto; Secrets nur in .env);
Token-Persistenz läuft über das ttlock_konto-Repo. Für Tests kann ein `client_factory`
injiziert werden (Fake-Client), dann ist kein Netz/keine Env nötig.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.models.schliessanlage import (
    TuerZutrittLog, record_type_label, IC_CARD_RECORD_TYPES,
)
from app.services.ttlock_client import TTLockClient

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://euapi.ttlock.com"


class ZutrittNichtKonfiguriertError(RuntimeError):
    """Es ist kein vollständiges TTLock-Konto in der Env hinterlegt."""


def _env_config() -> dict:
    return {
        "endpoint": os.getenv("TTLOCK_ENDPOINT", _DEFAULT_ENDPOINT),
        "client_id": os.getenv("TTLOCK_CLIENT_ID", ""),
        "client_secret": os.getenv("TTLOCK_CLIENT_SECRET", ""),
        "username": os.getenv("TTLOCK_USERNAME", ""),
        "password": os.getenv("TTLOCK_PASSWORD", ""),
    }


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, TypeError):
        return None


class ZutrittService:

    def __init__(self, *, konto_repo, schloss_repo, chip_repo, berechtigung_repo,
                 log_repo, client_factory: Optional[Callable[[], TTLockClient]] = None):
        self.konto_repo = konto_repo
        self.schloss_repo = schloss_repo
        self.chip_repo = chip_repo
        self.berechtigung_repo = berechtigung_repo
        self.log_repo = log_repo
        self._client_factory = client_factory

    # --- Client-Lifecycle ---------------------------------------------------
    @staticmethod
    def is_configured() -> bool:
        cfg = _env_config()
        return bool(cfg["client_id"] and cfg["client_secret"]
                    and cfg["username"] and cfg["password"])

    def _build_client(self) -> TTLockClient:
        cfg = _env_config()
        if not self.is_configured():
            raise ZutrittNichtKonfiguriertError(
                "Kein vollständiges TTLock-Konto in der Env (TTLOCK_CLIENT_ID/"
                "CLIENT_SECRET/USERNAME/PASSWORD)."
            )
        konto = self.konto_repo.get()
        expires_at = None
        if konto and konto.token_expires_at:
            try:
                expires_at = datetime.fromisoformat(konto.token_expires_at)
            except ValueError:
                expires_at = None
        return TTLockClient(
            cfg["endpoint"], cfg["client_id"], cfg["client_secret"],
            cfg["username"], cfg["password"],
            access_token=konto.access_token if konto else None,
            refresh_token=konto.refresh_token if konto else None,
            token_expires_at=expires_at,
            uid=konto.ttlock_uid if konto else None,
            on_token_update=self._persist_token,
        )

    def _persist_token(self, t: dict) -> None:
        exp = t.get("token_expires_at")
        self.konto_repo.save_tokens(
            endpoint=_env_config()["endpoint"],
            ttlock_uid=t.get("uid"),
            access_token=t.get("access_token"),
            refresh_token=t.get("refresh_token"),
            token_expires_at=exp.isoformat() if exp else None,
        )

    def _client(self) -> TTLockClient:
        return self._client_factory() if self._client_factory else self._build_client()

    # --- Inventar-Sync ------------------------------------------------------
    def inventar_sync(self) -> dict:
        """Schlösser + Gateways spiegeln. Online-Status kommt aus gateway/list
        (account-weit), die Schloss↔Gateway-Zuordnung aus gateway/listByLock."""
        client = self._client()
        online_map: dict = {}
        for g in client.gateway_list().get("list", []):
            online_map[g.get("gatewayId")] = bool(g.get("isOnline"))

        locks = client.lock_list().get("list", [])
        for l in locks:
            lock_id = l.get("lockId")
            gws = client.gateway_list_by_lock(lock_id).get("list", [])
            gw_id = gws[0].get("gatewayId") if gws else None
            gw_online = online_map.get(gw_id) if gw_id is not None else None
            self.schloss_repo.upsert_inventory(
                ttlock_lock_id=lock_id,
                name=l.get("lockAlias") or l.get("lockName") or str(lock_id),
                lock_mac=l.get("lockMac"),
                ttlock_gateway_id=gw_id,
                gateway_online=gw_online,
                akku_prozent=l.get("electricQuantity"),
                akku_stand_at=_ms_to_iso(l.get("electricQuantityUpdateDate")),
            )
        self.konto_repo.touch_sync(datetime.now(timezone.utc).isoformat())
        logger.info("Inventar-Sync: %d Schloss/Schlösser gespiegelt.", len(locks))
        return {"schloesser": len(locks)}

    # --- Log-Sync -----------------------------------------------------------
    def logs_sync(self, *, schloss_id: Optional[int] = None,
                  backfill_days: int = 30, max_pages: int = 20) -> dict:
        """Zutrittslogs paginiert seit Cursor holen und idempotent speichern."""
        client = self._client()
        if schloss_id is not None:
            s = self.schloss_repo.get(schloss_id)
            schloesser = [s] if s else []
        else:
            schloesser = self.schloss_repo.list_all(nur_aktive=True)

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        total_new = 0
        for s in schloesser:
            cursor = self.log_repo.max_server_date(s.id)
            start_ms = (cursor + 1) if cursor else int(
                (datetime.now(timezone.utc) - timedelta(days=backfill_days)).timestamp() * 1000
            )
            max_sd = cursor or 0
            newest_ld: Optional[int] = None
            newest_rt: Optional[int] = None
            page = 1
            while page <= max_pages:
                resp = client.lock_records(s.ttlock_lock_id, start_ms, now_ms,
                                           page_no=page, page_size=100)
                records = resp.get("list", [])
                for r in records:
                    rec_id = r.get("recordId")
                    if rec_id is None:
                        continue
                    rt = r.get("recordType")
                    credential = r.get("keyboardPwd") or None
                    chip = None
                    if credential and rt in IC_CARD_RECORD_TYPES:
                        chip = self.chip_repo.find_active_by_kartennummer(credential)
                    if self.log_repo.insert_if_new(TuerZutrittLog(
                        ttlock_record_id=rec_id, schloss_id=s.id,
                        record_type=rt, record_type_from_lock=r.get("recordTypeFromLock"),
                        methode=record_type_label(rt), erfolg=(r.get("success") == 1),
                        credential=credential, key_name=r.get("keyName"),
                        ttlock_username=r.get("username"),
                        chip_id=chip.id if chip else None,
                        mitglied_id=chip.mitglied_id if chip else None,
                        lock_date=_ms_to_iso(r.get("lockDate")),
                        server_date=r.get("serverDate"), raw=r,
                    )):
                        total_new += 1
                    sd = r.get("serverDate")
                    if sd and sd > max_sd:
                        max_sd = sd
                    ld = r.get("lockDate")
                    if ld and (newest_ld is None or ld > newest_ld):
                        newest_ld, newest_rt = ld, rt
                if page >= resp.get("pages", 1) or not records:
                    break
                page += 1

            # Cursor/Status-Snapshot nur fortschreiben, wenn es wirklich Neues gab
            # (vermeidet History-Leerrauschen durch No-Op-Version-Bumps).
            if max_sd and max_sd != (cursor or 0):
                self.schloss_repo.update_cursor_and_event(
                    s.id, serverdate=max_sd,
                    letztes_event_at=_ms_to_iso(newest_ld),
                    letztes_event_type=newest_rt,
                )
        self.konto_repo.touch_sync(datetime.now(timezone.utc).isoformat())
        logger.info("Log-Sync: %d neue Zutrittslog-Einträge.", total_new)
        return {"neu": total_new}
