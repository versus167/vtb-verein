"""
ZutrittService – Domänen-Orchestrierung über der TTLock-Cloud.

Aufgaben:
- `inventar_sync()`  – Schlösser/Gateways aus der Cloud spiegeln (Akku, Online-Status).
- `logs_sync()`      – Zutrittslogs paginiert seit Cursor holen, idempotent (recordId)
                       speichern, Kartennummer → Chip → Mitglied auflösen, Cursor +
                       Status-Snapshot (letzter Schließvorgang) fortschreiben.
- `ic_cards_sync()`  – am Schloss angelernte IC-Karten spiegeln (Chips/Berechtigungen).
- `chip_anlernen()` / `berechtigung_aendern()` / `berechtigung_entziehen()` – Cloud-Writes
                       (`identityCard/add|changePeriod|delete`) über das Gateway (Phase 2).

Der TTLock-Client wird aus der Env gebaut (ein Vereinskonto; Secrets nur in .env);
Token-Persistenz läuft über das ttlock_konto-Repo. Für Tests kann ein `client_factory`
injiziert werden (Fake-Client), dann ist kein Netz/keine Env nötig.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.models.schliessanlage import (
    TuerZutrittLog, SchluesselChip, TuerBerechtigung, record_type_label,
    IC_CARD_RECORD_TYPES, ALARM_RECORD_TYPES, SYNC_AKTIV, SYNC_FEHLER, SYNC_PENDING,
)
from app.services.ttlock_client import TTLockClient, TTLockError

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


def _iso_to_ms(iso: Optional[str]) -> int:
    """ISO-Zeitstempel → ms (für TTLock). None/leer → 0 (= unbefristet bei TTLock)."""
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def build_alarm_digest(alarme: list[dict]) -> Optional[tuple[str, str]]:
    """Aus neuen Alarm-Events eine kompakte Benachrichtigung (Titel, Text) bauen;
    None, wenn keine Alarme. Reine Funktion (kein Versand) – gut testbar."""
    if not alarme:
        return None
    zeilen = [
        f"• {a.get('schloss_name') or ('Schloss #' + str(a.get('schloss_id')))}: "
        f"{a.get('methode')} ({a.get('lock_date') or 'Zeit unbekannt'})"
        for a in alarme
    ]
    titel = f"⚠️ Schließanlage: {len(alarme)} sicherheitsrelevante(s) Ereignis(se)"
    text = "Beim Zutritts-Sync wurden folgende Ereignisse registriert:\n\n" + "\n".join(zeilen)
    return titel, text


def notify_alarme(db, alarme: list[dict]) -> int:
    """Aktive Admins über neue Alarm-Events benachrichtigen (Phase 4). Gibt die Zahl
    erreichter Empfänger zurück. Fehler je Empfänger werden geloggt, nicht propagiert
    (der Sync darf an einem Notification-Problem nicht scheitern)."""
    digest = build_alarm_digest(alarme)
    if digest is None:
        return 0
    titel, text = digest
    from app.services.user_service import UserService
    from app.services.notification_service import NotificationService
    empfaenger = [u for u in UserService(db).list_all() if u.active and u.role == "admin"]
    sent = 0
    for u in empfaenger:
        try:
            if NotificationService.send_notification(u, titel, text):
                sent += 1
        except Exception:
            logger.exception("Alarm-Benachrichtigung an %s fehlgeschlagen.", u.username)
    logger.info("Alarm-Benachrichtigung: %d/%d Admins erreicht.", sent, len(empfaenger))
    return sent


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

    # --- Steuern (Fernöffnen/-verriegeln über Gateway) ---------------------
    def oeffnen(self, schloss_id: int) -> dict:
        """Schloss per Gateway fernöffnen. Wirft ValueError, wenn unbekannt."""
        schloss = self.schloss_repo.get(schloss_id)
        if not schloss:
            raise ValueError("Schloss nicht gefunden")
        self._client().unlock(schloss.ttlock_lock_id)
        logger.info("Schloss %s (lockId=%s) ferngeöffnet.", schloss.name, schloss.ttlock_lock_id)
        return {"ok": True, "schloss": schloss.name}

    def verriegeln(self, schloss_id: int) -> dict:
        """Schloss per Gateway fernverriegeln (modellabhängig)."""
        schloss = self.schloss_repo.get(schloss_id)
        if not schloss:
            raise ValueError("Schloss nicht gefunden")
        self._client().remote_lock(schloss.ttlock_lock_id)
        logger.info("Schloss %s (lockId=%s) fernverriegelt.", schloss.name, schloss.ttlock_lock_id)
        return {"ok": True, "schloss": schloss.name}

    # --- Chip-Anlernen / Berechtigungen (Phase 2, Cloud-Writes) ------------
    def chip_anlernen(self, *, chip_id: int, schloss_id: int,
                      gueltig_von: Optional[str] = None, gueltig_bis: Optional[str] = None,
                      erteilt_von: Optional[int] = None, actor: str = "SYSTEM") -> TuerBerechtigung:
        """Chip an einem Schloss anlernen: lokale Berechtigung (pending) anlegen, dann per
        Gateway `identityCard/add` → `cardId` + `sync_status` festschreiben. Bei Cloud-Fehler
        bleibt die Zeile als `fehler` stehen (mit Meldung) und der Fehler wird geworfen."""
        chip = self.chip_repo.get(chip_id)
        if not chip:
            raise ValueError("Chip nicht gefunden")
        if not (chip.kartennummer or "").strip():
            raise ValueError("Chip hat keine Kartennummer – Anlernen über Gateway nicht möglich")
        schloss = self.schloss_repo.get(schloss_id)
        if not schloss:
            raise ValueError("Schloss nicht gefunden")
        if self.berechtigung_repo.find_active_for_chip_schloss(chip_id, schloss_id):
            raise ValueError("Chip ist diesem Schloss bereits zugeteilt")

        ber = self.berechtigung_repo.create(TuerBerechtigung(
            chip_id=chip_id, schloss_id=schloss_id, gueltig_von=gueltig_von,
            gueltig_bis=gueltig_bis, sync_status=SYNC_PENDING, erteilt_von=erteilt_von,
        ), actor)
        card_name = chip.bezeichnung or f"Chip {chip.kartennummer}"
        try:
            resp = self._client().ic_card_add(
                schloss.ttlock_lock_id, chip.kartennummer, card_name,
                _iso_to_ms(gueltig_von), _iso_to_ms(gueltig_bis),
            )
        except TTLockError as e:
            self.berechtigung_repo.set_sync(ber.id, ttlock_card_id=None,
                                            sync_status=SYNC_FEHLER, sync_fehler=str(e), by=actor)
            raise
        card_id = resp.get("cardId")
        logger.info("Chip %s an Schloss %s angelernt (cardId=%s).",
                    chip.kartennummer, schloss.name, card_id)
        return self.berechtigung_repo.set_sync(ber.id, ttlock_card_id=card_id,
                                               sync_status=SYNC_AKTIV, sync_fehler=None, by=actor)

    def berechtigung_aendern(self, *, berechtigung_id: int,
                             gueltig_von: Optional[str] = None,
                             gueltig_bis: Optional[str] = None,
                             actor: str = "SYSTEM") -> TuerBerechtigung:
        """Gültigkeitszeitraum einer angelernten Berechtigung per Gateway ändern."""
        ber = self.berechtigung_repo.get(berechtigung_id)
        if not ber:
            raise ValueError("Berechtigung nicht gefunden")
        if not ber.ttlock_card_id:
            raise ValueError("Berechtigung ist noch nicht mit der Cloud synchronisiert")
        schloss = self.schloss_repo.get(ber.schloss_id)
        if not schloss:
            raise ValueError("Schloss nicht gefunden")
        try:
            self._client().ic_card_change_period(
                schloss.ttlock_lock_id, ber.ttlock_card_id,
                _iso_to_ms(gueltig_von), _iso_to_ms(gueltig_bis),
            )
        except TTLockError as e:
            self.berechtigung_repo.set_sync(ber.id, ttlock_card_id=ber.ttlock_card_id,
                                            sync_status=SYNC_FEHLER, sync_fehler=str(e), by=actor)
            raise
        logger.info("Berechtigung %s: Gültigkeit geändert (%s–%s).",
                    berechtigung_id, gueltig_von or "sofort", gueltig_bis or "unbefristet")
        return self.berechtigung_repo.update_period(ber.id, gueltig_von=gueltig_von,
                                                    gueltig_bis=gueltig_bis, by=actor)

    def berechtigung_entziehen(self, *, berechtigung_id: int, actor: str = "SYSTEM") -> dict:
        """Berechtigung entziehen: IC-Karte per Gateway vom Schloss entfernen (sofern bereits
        angelernt), dann die lokale Zeile soft-löschen. Schlägt der Cloud-Delete fehl, bleibt
        die Zeile als `fehler` bestehen (kein lokaler Soft-Delete) – die Karte ist sonst noch
        gültig am Schloss."""
        ber = self.berechtigung_repo.get(berechtigung_id)
        if not ber:
            raise ValueError("Berechtigung nicht gefunden")
        if ber.ttlock_card_id:
            schloss = self.schloss_repo.get(ber.schloss_id)
            if schloss:
                try:
                    self._client().ic_card_delete(schloss.ttlock_lock_id, ber.ttlock_card_id)
                except TTLockError as e:
                    self.berechtigung_repo.set_sync(ber.id, ttlock_card_id=ber.ttlock_card_id,
                                                    sync_status=SYNC_FEHLER, sync_fehler=str(e),
                                                    by=actor)
                    raise
        self.berechtigung_repo.soft_delete(ber.id, actor)
        logger.info("Berechtigung %s entzogen (Chip von Schloss entfernt).", berechtigung_id)
        return {"ok": True}

    def ic_cards_sync(self) -> dict:
        """Bereits am Schloss (per BLE) angelernte IC-Karten aus der Cloud spiegeln:
        fehlende Chips anlegen, Berechtigungen (Chip↔Schloss) anlegen bzw. cardId/Status
        nachziehen. Read-only gegenüber dem Schloss (keine Cloud-Writes), idempotent."""
        client = self._client()
        neu_chips = neu_ber = akt_ber = 0
        for s in self.schloss_repo.list_all(nur_aktive=True):
            for card in client.ic_cards(s.ttlock_lock_id).get("list", []):
                cn = str(card.get("cardNumber") or "").strip()
                if not cn:
                    continue
                chip = self.chip_repo.find_active_by_kartennummer(cn)
                if not chip:
                    chip = self.chip_repo.create(
                        SchluesselChip(kartennummer=cn, bezeichnung=card.get("cardName") or None),
                        "SYSTEM")
                    neu_chips += 1
                card_id = card.get("cardId")
                ber = self.berechtigung_repo.find_active_for_chip_schloss(chip.id, s.id)
                if not ber:
                    self.berechtigung_repo.create(TuerBerechtigung(
                        chip_id=chip.id, schloss_id=s.id, ttlock_card_id=card_id,
                        gueltig_von=_ms_to_iso(card.get("startDate")),
                        gueltig_bis=_ms_to_iso(card.get("endDate")),
                        sync_status=SYNC_AKTIV), "SYSTEM")
                    neu_ber += 1
                elif ber.ttlock_card_id != card_id or ber.sync_status != SYNC_AKTIV:
                    self.berechtigung_repo.set_sync(ber.id, ttlock_card_id=card_id,
                                                    sync_status=SYNC_AKTIV, sync_fehler=None,
                                                    by="SYSTEM")
                    akt_ber += 1
        self.konto_repo.touch_sync(datetime.now(timezone.utc).isoformat())
        logger.info("IC-Card-Import: %d Chips neu, %d Berechtigungen neu, %d aktualisiert.",
                    neu_chips, neu_ber, akt_ber)
        return {"chips_neu": neu_chips, "berechtigungen_neu": neu_ber, "berechtigungen_akt": akt_ber}

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
        alarme: list[dict] = []
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
                        # Nur für tatsächlich NEUE Einträge melden (kein Re-Alarm bei Re-Sync).
                        if rt in ALARM_RECORD_TYPES:
                            alarme.append({
                                "schloss_id": s.id, "schloss_name": s.name,
                                "record_type": rt, "methode": record_type_label(rt),
                                "lock_date": _ms_to_iso(r.get("lockDate")),
                            })
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
        logger.info("Log-Sync: %d neue Zutrittslog-Einträge (%d Alarme).",
                    total_new, len(alarme))
        return {"neu": total_new, "alarme": alarme}
