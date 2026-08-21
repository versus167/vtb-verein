"""
Tests für ZutrittService – Orchestrierung ohne Netz/DB (Fakes für Client + Repos).

Geprüft:
- inventar_sync spiegelt Schlösser inkl. Online-Status (aus gateway/list) und Akku.
- logs_sync ist idempotent (Dedupe über recordId) und schreibt den Cursor fort.
- Kartennummer → Chip → Mitglied wird nur für IC-Karten-Records aufgelöst.
- Status-Snapshot (letztes Event) entspricht dem jüngsten Log.
"""
from datetime import datetime, timezone

import pytest
import requests

from app.services.zutritt_service import (
    ZutrittService, build_alarm_digest, fehlertext, ist_dauerhaft, karte_fehlt,
    karte_wirkungslos, _ms_to_iso, _iso_to_ms,
)
from app.services.ttlock_client import TTLockError
from app.models.schliessanlage import (
    TuerCredential, CRED_FINGERPRINT, CRED_PASSCODE, CRED_EKEY, CRED_IC,
)


# --- Fakes ------------------------------------------------------------------
class FakeClient:
    def __init__(self):
        self.unlocked = []
        self.locked = []
        self.added = []
        self.changed = []
        self.deleted = []
        self.cards_by_lock = {}      # lock_id -> Liste Card-Dicts (für ic_cards/Import)
        self.add_should_fail = False
        self.add_errcode = -3007       # Standard: Störung; -4043 = Absage des Modells
        self.change_should_fail = False
        self.change_errcode = -3003    # Standard: Gateway offline; -1021 = Karte weg
        self.delete_should_fail = False
        self.delete_errcode = -3003
        # Credential-Mirror (read-only): lock_id -> Liste typ-spezifischer Dicts
        self.fingerprints_by_lock = {}
        self.passcodes_by_lock = {}
        self.ekeys_by_lock = {}
        self.fingerprint_should_fail = False   # simuliert Modell ohne Sensor (errcode)
        self.passcode_http_fail = False        # simuliert Transport-/HTTP-Fehler (z. B. 404)
        self.records = None                    # überschreibt die Standard-3-Records (Korrelations-Tests)

    def unlock(self, lock_id):
        self.unlocked.append(lock_id); return {"errcode": 0}

    def remote_lock(self, lock_id):
        self.locked.append(lock_id); return {"errcode": 0}

    def ic_card_add(self, lock_id, card_number, card_name, start_ms=0, end_ms=0, *, add_type=2):
        if self.add_should_fail:
            # Wortlaut wie im echten Client (_request): Pfad + errcode + Cloud-Text.
            raise TTLockError(f"v3/identityCard/add: errcode={self.add_errcode} "
                              f"add fehlgeschlagen", errcode=self.add_errcode)
        self.added.append((lock_id, card_number, start_ms, end_ms))
        self.cards_by_lock.setdefault(lock_id, []).append(
            {"cardId": 9001, "cardNumber": card_number, "cardName": card_name,
             "startDate": start_ms, "endDate": end_ms})
        return {"errcode": 0, "cardId": 9001}

    def ic_card_change_period(self, lock_id, card_id, start_ms=0, end_ms=0, *, change_type=2):
        if self.change_should_fail:
            raise TTLockError(
                f"v3/identityCard/changePeriod: errcode={self.change_errcode} "
                f"This IC Card does not exist", errcode=self.change_errcode)
        self.changed.append((lock_id, card_id, start_ms, end_ms))
        for card in self.cards_by_lock.get(lock_id, []):
            if card.get("cardId") == card_id:
                card["startDate"], card["endDate"] = start_ms, end_ms
        return {"errcode": 0}

    def ic_card_delete(self, lock_id, card_id, *, delete_type=2):
        if self.delete_should_fail:
            raise TTLockError(
                f"v3/identityCard/delete: errcode={self.delete_errcode} "
                f"This IC Card does not exist", errcode=self.delete_errcode)
        self.deleted.append((lock_id, card_id))
        self.cards_by_lock[lock_id] = [c for c in self.cards_by_lock.get(lock_id, [])
                                       if c.get("cardId") != card_id]
        return {"errcode": 0}

    def ic_cards(self, lock_id, page_no=1, page_size=100):
        return {"list": self.cards_by_lock.get(lock_id, [])}

    def fingerprints(self, lock_id, page_no=1, page_size=100):
        if self.fingerprint_should_fail:
            raise TTLockError("fingerprint/list nicht unterstützt", errcode=-3003)
        return {"list": self.fingerprints_by_lock.get(lock_id, []), "pages": 1}

    def passcodes(self, lock_id, page_no=1, page_size=100):
        if self.passcode_http_fail:
            raise requests.exceptions.HTTPError("404 Client Error")
        return {"list": self.passcodes_by_lock.get(lock_id, []), "pages": 1}

    def ekeys(self, lock_id, page_no=1, page_size=100):
        return {"list": self.ekeys_by_lock.get(lock_id, []), "pages": 1}

    def gateway_list(self, **k):
        return {"list": [{"gatewayId": 2147896, "isOnline": 1}]}

    def lock_list(self, **k):
        return {"total": 1, "list": [{
            "lockId": 30392116, "lockAlias": "s3", "lockMac": "AA:BB",
            "electricQuantity": 100, "electricQuantityUpdateDate": 1782456408000,
        }]}

    def gateway_list_by_lock(self, lock_id, **k):
        return {"list": [{"gatewayId": 2147896, "gatewayName": "wlandongle"}]}

    def lock_records(self, lock_id, start_ms, end_ms, page_no=1, page_size=100):
        if self.records is not None:
            if page_no > 1:
                return {"list": [], "pages": 1, "pageNo": page_no}
            return {"total": len(self.records), "pages": 1, "pageNo": 1, "list": self.records}
        if page_no > 1:
            return {"list": [], "pages": 1, "pageNo": page_no}
        return {"total": 3, "pages": 1, "pageNo": 1, "list": [
            {"recordId": 1, "recordType": 7, "recordTypeFromLock": 26, "success": 1,
             "keyboardPwd": "818229331", "keyName": "chipA", "username": "u",
             "lockDate": 1782456312000, "serverDate": 1782456409000},
            {"recordId": 2, "recordType": 4, "success": 0, "keyboardPwd": "0000",
             "keyName": "pw", "username": "u",
             "lockDate": 1782456310000, "serverDate": 1782456408000},
            {"recordId": 3, "recordType": 11, "success": 1, "keyboardPwd": "",
             "keyName": "bt", "username": "u",
             "lockDate": 1782456301000, "serverDate": 1782456407000},
        ]}


class FakeSchloss:
    def __init__(self, id, ttlock_lock_id, name="s3"):
        # ttlock_lock_id=None ⇒ externes Schloss (eigene Anlage, kein Cloud-Anschluss)
        self.id, self.ttlock_lock_id, self.aktiv = id, ttlock_lock_id, True
        self.name = name
        self.lock_mac = self.ttlock_gateway_id = self.gateway_online = None
        self.akku_prozent = self.akku_stand_at = None
        self.letzter_log_serverdate = self.letztes_event_at = self.letztes_event_type = None


class FakeSchlossRepo:
    def __init__(self):
        self._by_lock, self._by_id, self._next = {}, {}, 1

    def get(self, id):
        return self._by_id.get(id)

    def list_all(self, nur_aktive=False, nur_ttlock=False):
        return [s for s in self._by_id.values()
                if (s.aktiv or not nur_aktive) and (s.ttlock_lock_id or not nur_ttlock)]

    def add_extern(self, name="Tor Einfahrt"):
        """Externes Schloss einhängen (ohne lockId) – darf in keinen Cloud-Sync geraten."""
        s = FakeSchloss(self._next, None, name); self._next += 1
        self._by_id[s.id] = s
        return s

    def upsert_inventory(self, *, ttlock_lock_id, name, lock_mac, ttlock_gateway_id,
                         gateway_online, akku_prozent, akku_stand_at, by='SYSTEM'):
        s = self._by_lock.get(ttlock_lock_id)
        if not s:
            s = FakeSchloss(self._next, ttlock_lock_id, name); self._next += 1
            self._by_lock[ttlock_lock_id] = s; self._by_id[s.id] = s
        s.lock_mac, s.ttlock_gateway_id, s.gateway_online = lock_mac, ttlock_gateway_id, gateway_online
        s.akku_prozent, s.akku_stand_at = akku_prozent, akku_stand_at
        return s.id

    def update_cursor_and_event(self, schloss_id, *, serverdate, letztes_event_at,
                                letztes_event_type, by='SYSTEM'):
        s = self._by_id[schloss_id]
        if serverdate:
            s.letzter_log_serverdate = max(s.letzter_log_serverdate or 0, serverdate)
        if letztes_event_at:
            s.letztes_event_at = letztes_event_at
        if letztes_event_type is not None:
            s.letztes_event_type = letztes_event_type


class FakeChip:
    def __init__(self, id, mitglied_id, kartennummer="", bezeichnung=None, status="aktiv",
                 user_id=None):
        self.id, self.mitglied_id, self.user_id = id, mitglied_id, user_id
        self.kartennummer, self.bezeichnung = kartennummer, bezeichnung
        self.status, self.version, self.deleted = status, 1, False


class FakeChipRepo:
    def __init__(self, mapping=None):
        self._m = mapping or {}
        self._by_id = {c.id: c for c in self._m.values()}
        self._next = (max(self._by_id) + 1) if self._by_id else 1

    def find_active_by_kartennummer(self, kn):
        return self._m.get(kn)

    def get(self, id):
        chip = self._by_id.get(id)
        return chip if (chip and not chip.deleted) else None

    def create(self, c, created_by):
        chip = FakeChip(self._next, getattr(c, "mitglied_id", None),
                        kartennummer=c.kartennummer, bezeichnung=c.bezeichnung)
        self._by_id[chip.id] = chip; self._m[c.kartennummer] = chip; self._next += 1
        return chip

    def update(self, c, updated_by):
        chip = self._by_id[c.id]
        chip.status, chip.bezeichnung = c.status, c.bezeichnung
        chip.version += 1
        return chip

    def soft_delete(self, id, deleted_by):
        chip = self._by_id.get(id)
        if chip:
            chip.deleted = True
        return bool(chip)


class FakeBer:
    def __init__(self, id, chip_id, schloss_id, **kw):
        self.id, self.chip_id, self.schloss_id = id, chip_id, schloss_id
        self.ttlock_card_id = kw.get("ttlock_card_id")
        self.gueltig_von = kw.get("gueltig_von")
        self.gueltig_bis = kw.get("gueltig_bis")
        self.sync_status = kw.get("sync_status") or "pending"
        self.sync_fehler = kw.get("sync_fehler")
        self.erteilt_von = kw.get("erteilt_von")
        self.gruppe_id = kw.get("gruppe_id")
        self.deleted = False


class FakeBerechtigungRepo:
    def __init__(self):
        self.rows, self._next = {}, 1

    def create(self, b, created_by):
        r = FakeBer(self._next, b.chip_id, b.schloss_id, ttlock_card_id=b.ttlock_card_id,
                    gueltig_von=b.gueltig_von, gueltig_bis=b.gueltig_bis,
                    sync_status=b.sync_status, erteilt_von=b.erteilt_von,
                    gruppe_id=b.gruppe_id)
        self.rows[r.id] = r; self._next += 1
        return r

    def get(self, id):
        r = self.rows.get(id)
        return r if (r and not r.deleted) else None

    def list_for_chip(self, chip_id):
        return [r for r in self.rows.values() if not r.deleted and r.chip_id == chip_id]

    def find_active_for_chip_schloss(self, chip_id, schloss_id):
        return next((r for r in self.rows.values()
                     if not r.deleted and r.chip_id == chip_id and r.schloss_id == schloss_id), None)

    def set_sync(self, id, *, ttlock_card_id, sync_status, sync_fehler, by):
        r = self.rows[id]
        r.ttlock_card_id, r.sync_status, r.sync_fehler = ttlock_card_id, sync_status, sync_fehler
        return r

    def update_period(self, id, *, gueltig_von, gueltig_bis, by, sync_status="aktiv"):
        r = self.rows[id]
        r.gueltig_von, r.gueltig_bis = gueltig_von, gueltig_bis
        r.sync_status, r.sync_fehler = sync_status, None
        return r

    def soft_delete(self, id, deleted_by):
        r = self.rows.get(id)
        if r:
            r.deleted = True
        return bool(r)


class FakeLogRepo:
    def __init__(self):
        self.rows, self._seen = [], set()

    def insert_if_new(self, log):
        if log.ttlock_record_id in self._seen:
            return False
        self._seen.add(log.ttlock_record_id); self.rows.append(log)
        return True

    def max_server_date(self, schloss_id):
        sds = [r.server_date for r in self.rows if r.schloss_id == schloss_id and r.server_date]
        return max(sds) if sds else None


class FakeCredentialRepo:
    """Mirror je (schloss_id, typ) – ersetzt autoritativ, wie der echte Repo."""
    def __init__(self):
        self.by_schloss_typ = {}     # (schloss_id, typ) -> list[TuerCredential]

    def replace_for_schloss_typ(self, schloss_id, typ, rows):
        self.by_schloss_typ[(schloss_id, typ)] = list(rows)
        return len(rows)

    def ic_karte_gesetzt(self, schloss_id, *, credential_id, name, kartennummer,
                         gueltig_von, gueltig_bis):
        rows = self.by_schloss_typ.setdefault((schloss_id, CRED_IC), [])
        for r in rows:
            if r.ttlock_credential_id == credential_id:
                r.name, r.detail = name, kartennummer
                r.gueltig_von, r.gueltig_bis = gueltig_von, gueltig_bis
                return
        # Wie im echten Repo: `gesehen_am` erbt den Stand DIESES Schlosses – geschrieben
        # ist nicht gelesen, der Spiegel wird davon nicht frischer.
        rows.append(TuerCredential(
            schloss_id=schloss_id, typ=CRED_IC, ttlock_credential_id=credential_id,
            name=name, detail=kartennummer, gueltig_von=gueltig_von,
            gueltig_bis=gueltig_bis,
            gesehen_am=max((r.gesehen_am for r in rows if r.gesehen_am), default=None)))

    def ic_karte_entfernt(self, schloss_id, credential_id):
        self.by_schloss_typ[(schloss_id, CRED_IC)] = [
            r for r in self.by_schloss_typ.get((schloss_id, CRED_IC), [])
            if r.ttlock_credential_id != credential_id]

    def list_for_schloss(self, schloss_id):
        out = []
        for (sid, _typ), rows in self.by_schloss_typ.items():
            if sid == schloss_id:
                out.extend(rows)
        return out


class FakeKontoRepo:
    def __init__(self):
        self.synced = []

    def get(self):
        return None

    def save_tokens(self, **k):
        pass

    def touch_sync(self, when_iso, **k):
        self.synced.append(when_iso)


class FakeMitgliedForLog:
    def __init__(self, id):
        self.id = id


class FakeMitgliedRepo:
    def __init__(self, by_user=None):
        self._by_user = by_user or {}      # user_id -> FakeMitgliedForLog

    def get_by_user_id(self, user_id):
        return self._by_user.get(user_id)


class FakeAccessLogRepo:
    """Spiegelt die SQL-Semantik von find_schliessanlage_unlock_near:
    gleiches Schloss, Zeit innerhalb ±window_seconds, nächstliegender Treffer."""
    def __init__(self, unlocks=None):
        # unlocks: list[{schloss_id, user_id, username, ts_iso}]
        self._unlocks = unlocks or []

    def find_schliessanlage_unlock_near(self, schloss_id, ts_iso, window_seconds=120):
        target = datetime.fromisoformat(ts_iso)
        best, best_dt = None, None
        for u in self._unlocks:
            if u["schloss_id"] != schloss_id:
                continue
            dt = abs((datetime.fromisoformat(u["ts_iso"]) - target).total_seconds())
            if dt <= window_seconds and (best_dt is None or dt < best_dt):
                best, best_dt = u, dt
        return {"user_id": best["user_id"], "username": best["username"]} if best else None


def _service(chip_map=None, access_log_repo=None, mitglied_repo=None):
    return ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo(chip_map or {}), berechtigung_repo=None,
        log_repo=FakeLogRepo(), client_factory=FakeClient,
        access_log_repo=access_log_repo, mitglied_repo=mitglied_repo,
    )


# --- Tests ------------------------------------------------------------------
def test_inventar_sync_spiegelt_schloss_und_online():
    svc = _service()
    res = svc.inventar_sync()
    assert res == {"schloesser": 1}
    s = svc.schloss_repo.list_all()[0]
    assert s.ttlock_lock_id == 30392116
    assert s.gateway_online is True          # aus gateway/list isOnline=1
    assert s.ttlock_gateway_id == 2147896    # aus gateway/listByLock
    assert s.akku_prozent == 100
    assert s.akku_stand_at is not None       # ms → ISO


def test_logs_sync_dedupe_und_cursor():
    svc = _service()
    svc.inventar_sync()
    assert svc.logs_sync()["neu"] == 3       # erster Lauf: alle drei neu
    assert len(svc.log_repo.rows) == 3
    assert svc.logs_sync()["neu"] == 0       # zweiter Lauf: alles dedupliziert
    assert len(svc.log_repo.rows) == 3
    # Cursor steht auf dem jüngsten serverDate
    assert svc.schloss_repo.list_all()[0].letzter_log_serverdate == 1782456409000


def test_logs_sync_chip_aufloesung_nur_fuer_ic_karte():
    svc = _service(chip_map={"818229331": FakeChip(5, mitglied_id=42)})
    svc.inventar_sync()
    svc.logs_sync()
    by_rec = {r.ttlock_record_id: r for r in svc.log_repo.rows}
    # IC-Karten-Record (recordType 7) → Chip+Mitglied aufgelöst
    assert by_rec[1].chip_id == 5 and by_rec[1].mitglied_id == 42
    assert by_rec[1].methode == "IC-Karte" and by_rec[1].erfolg is True
    # Passcode-Record (recordType 4) → keine Chip-Auflösung, obwohl keyboardPwd gesetzt
    assert by_rec[2].chip_id is None and by_rec[2].erfolg is False


def test_externes_schloss_bleibt_aus_cloud_syncs_heraus():
    """Ein Schloss ohne lockId (eigene Anlage, gleiche Chips) darf in keinen Cloud-
    Aufruf geraten – dort liefe die lockId None gegen ein fremdes oder gar kein Schloss."""
    svc = _service()
    svc.inventar_sync()                       # ein echtes TTLock-Schloss
    extern = svc.schloss_repo.add_extern()
    assert svc.logs_sync()["neu"] == 3        # nur das Cloud-Schloss geliefert
    assert {r.schloss_id for r in svc.log_repo.rows} == {1}
    # Auch gezielt angefragt bleibt es unberührt (kein Fehler, kein Cloud-Call)
    assert svc.logs_sync(schloss_id=extern.id)["neu"] == 0


def test_externes_schloss_laesst_sich_nicht_fernsteuern():
    svc = _service()
    extern = svc.schloss_repo.add_extern()
    with pytest.raises(ValueError, match="extern"):
        svc.oeffnen(extern.id)
    with pytest.raises(ValueError, match="extern"):
        svc.verriegeln(extern.id)
    assert svc._client_factory().unlocked == []


def test_logs_sync_status_snapshot():
    svc = _service()
    svc.inventar_sync()
    svc.logs_sync()
    s = svc.schloss_repo.list_all()[0]
    # Jüngster lockDate (…312000) gehört zu recordType 7
    assert s.letztes_event_type == 7
    assert s.letztes_event_at is not None


# --- App-/Gateway-Öffnung → Mitglied auflösen (#66, Phase-5-Teil B) ----------
_REMOTE_MS = 1782456312000     # lockDate des Gateway-Remote-Records (recordType 3)


def _remote_record():
    return [{"recordId": 10, "recordType": 3, "success": 1, "keyboardPwd": "",
             "keyName": "Gateway", "username": "ttlock@verein",
             "lockDate": _REMOTE_MS, "serverDate": 1782456409000}]


def _remote_service(fake, access_log_repo=None, mitglied_repo=None):
    return ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo({}), berechtigung_repo=None,
        log_repo=FakeLogRepo(), client_factory=lambda: fake,
        access_log_repo=access_log_repo, mitglied_repo=mitglied_repo,
    )


def test_logs_sync_app_oeffnung_wird_auf_mitglied_korreliert():
    fake = FakeClient(); fake.records = _remote_record()
    alog = FakeAccessLogRepo([{"schloss_id": 1, "user_id": 7, "username": "vsuess",
                               "ts_iso": _ms_to_iso(_REMOTE_MS)}])
    svc = _remote_service(fake, alog, FakeMitgliedRepo({7: FakeMitgliedForLog(99)}))
    svc.inventar_sync()
    svc.logs_sync()
    rec = svc.log_repo.rows[0]
    assert rec.record_type == 3 and rec.chip_id is None
    assert rec.mitglied_id == 99          # VTB-User per access_log-Korrelation → Mitglied


def test_logs_sync_app_oeffnung_ausserhalb_fensters_bleibt_unaufgeloest():
    fake = FakeClient(); fake.records = _remote_record()
    # access_log-Eintrag 5 min entfernt → außerhalb des 120s-Korrelationsfensters
    alog = FakeAccessLogRepo([{"schloss_id": 1, "user_id": 7, "username": "vsuess",
                               "ts_iso": _ms_to_iso(_REMOTE_MS + 5 * 60 * 1000)}])
    svc = _remote_service(fake, alog, FakeMitgliedRepo({7: FakeMitgliedForLog(99)}))
    svc.inventar_sync()
    svc.logs_sync()
    assert svc.log_repo.rows[0].mitglied_id is None


def test_logs_sync_app_oeffnung_user_ohne_mitglied_bleibt_unaufgeloest():
    fake = FakeClient(); fake.records = _remote_record()
    alog = FakeAccessLogRepo([{"schloss_id": 1, "user_id": 7, "username": "admin",
                               "ts_iso": _ms_to_iso(_REMOTE_MS)}])
    svc = _remote_service(fake, alog, FakeMitgliedRepo({}))   # User 7 ohne verknüpftes Mitglied
    svc.inventar_sync()
    svc.logs_sync()
    assert svc.log_repo.rows[0].mitglied_id is None


def test_logs_sync_app_oeffnung_ohne_korrelations_repos_kein_fehler():
    fake = FakeClient(); fake.records = _remote_record()
    svc = _remote_service(fake)              # keine access_log-/mitglied-Repos injiziert
    svc.inventar_sync()
    svc.logs_sync()
    assert svc.log_repo.rows[0].mitglied_id is None


def test_oeffnen_ruft_unlock_mit_ttlock_lock_id():
    fake = FakeClient()
    svc = ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo({}), berechtigung_repo=None,
        log_repo=FakeLogRepo(), client_factory=lambda: fake,
    )
    svc.inventar_sync()
    sid = svc.schloss_repo.list_all()[0].id     # lokale id
    res = svc.oeffnen(sid)
    assert res["ok"] is True
    assert fake.unlocked == [30392116]          # an die TTLock-lockId, nicht die lokale id


def test_oeffnen_unbekanntes_schloss_wirft():
    svc = _service()
    with pytest.raises(ValueError):
        svc.oeffnen(999)


# --- Phase 2: Chip anlernen / Berechtigungen --------------------------------
def _p2_service(fake_client, chip_map=None):
    return ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo(chip_map or {}), berechtigung_repo=FakeBerechtigungRepo(),
        log_repo=FakeLogRepo(), credential_repo=FakeCredentialRepo(),
        client_factory=lambda: fake_client,
    )


def _spiegel(svc, schloss_id=1):
    """Was der Ist-Spiegel dieses Schlosses an IC-Karten führt (cardId -> Zeile)."""
    return {c.ttlock_credential_id: c
            for c in svc.credential_repo.by_schloss_typ.get((schloss_id, CRED_IC), [])}


def test_chip_anlernen_ruft_add_und_setzt_card_id():
    fake = FakeClient()
    chip = FakeChip(7, mitglied_id=None, kartennummer="818229331", bezeichnung="Chip blau")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()                       # legt Schloss id=1 (lockId 30392116) an
    ber = svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    # add ging an die TTLock-lockId mit der Kartennummer
    assert fake.added and fake.added[0][0] == 30392116 and fake.added[0][1] == "818229331"
    assert ber.sync_status == "aktiv" and ber.ttlock_card_id == 9001


def test_chip_anlernen_doppelt_wirft():
    fake = FakeClient()
    chip = FakeChip(7, None, kartennummer="818229331")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()
    svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    with pytest.raises(ValueError):
        svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")


def test_chip_anlernen_ohne_kartennummer_wirft():
    fake = FakeClient()
    chip = FakeChip(7, None, kartennummer="")   # keine Nummer → Gateway-Add unmöglich
    svc = _p2_service(fake, chip_map={"seed": chip})
    svc.inventar_sync()
    with pytest.raises(ValueError):
        svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    assert fake.added == []


def test_chip_anlernen_cloud_fehler_setzt_status_fehler_und_wirft():
    fake = FakeClient(); fake.add_should_fail = True
    chip = FakeChip(7, None, kartennummer="999")
    svc = _p2_service(fake, chip_map={"999": chip})
    svc.inventar_sync()
    with pytest.raises(TTLockError):
        svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    rows = list(svc.berechtigung_repo.rows.values())
    assert len(rows) == 1 and rows[0].sync_status == "fehler" and rows[0].sync_fehler


def test_berechtigung_aendern_ruft_change_period():
    fake = FakeClient()
    chip = FakeChip(7, None, kartennummer="818229331")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()
    ber = svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    out = svc.berechtigung_aendern(berechtigung_id=ber.id,
                                   gueltig_bis="2026-12-31T23:00:00+00:00", actor="admin")
    assert fake.changed and fake.changed[0][1] == 9001
    assert out.gueltig_bis == "2026-12-31T23:00:00+00:00" and out.sync_status == "aktiv"


def test_berechtigung_entziehen_loescht_card_und_soft_delete():
    fake = FakeClient()
    chip = FakeChip(7, None, kartennummer="818229331")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()
    ber = svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    svc.berechtigung_entziehen(berechtigung_id=ber.id, actor="admin")
    assert fake.deleted == [(30392116, 9001)]
    assert svc.berechtigung_repo.get(ber.id) is None   # lokal soft-gelöscht


def test_ic_cards_sync_importiert_chip_und_berechtigung_idempotent():
    fake = FakeClient()
    svc = _p2_service(fake)
    svc.inventar_sync()                       # Schloss id=1, ttlock_lock_id 30392116
    fake.cards_by_lock[30392116] = [
        {"cardId": 4242, "cardNumber": "818229331", "cardName": "Chip blau",
         "startDate": 0, "endDate": 0},
    ]
    res = svc.ic_cards_sync()
    assert res["chips_neu"] == 1 and res["berechtigungen_neu"] == 1
    chip = svc.chip_repo.find_active_by_kartennummer("818229331")
    assert chip is not None
    ber = svc.berechtigung_repo.find_active_for_chip_schloss(chip.id, 1)
    assert ber.ttlock_card_id == 4242 and ber.sync_status == "aktiv"
    # zweiter Lauf: nichts Neues (idempotent)
    res2 = svc.ic_cards_sync()
    assert res2["chips_neu"] == 0 and res2["berechtigungen_neu"] == 0


# --- Credential-Mirror (read-only Inventar je Schloss) ----------------------
def _cred_service(fake_client):
    return ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo({}), berechtigung_repo=FakeBerechtigungRepo(),
        log_repo=FakeLogRepo(), credential_repo=FakeCredentialRepo(),
        client_factory=lambda: fake_client,
    )


def test_credentials_sync_spiegelt_alle_typen():
    fake = FakeClient()
    svc = _cred_service(fake)
    svc.inventar_sync()                                   # Schloss id=1, lockId 30392116
    fake.fingerprints_by_lock[30392116] = [
        {"fingerprintId": 1, "fingerprintName": "Daumen rechts", "startDate": 0, "endDate": 0}]
    fake.passcodes_by_lock[30392116] = [
        {"keyboardPwdId": 5, "keyboardPwdName": "Putzdienst", "keyboardPwd": "1234",
         "startDate": 0, "endDate": 1782456408000}]
    fake.ekeys_by_lock[30392116] = [
        {"keyId": 9, "keyName": "Trainer", "username": "max@example.com",
         "startDate": 0, "endDate": 0}]
    fake.cards_by_lock[30392116] = [
        {"cardId": 42, "cardName": "Chip blau", "cardNumber": "818229331",
         "startDate": 0, "endDate": 0}]

    res = svc.credentials_sync()
    assert res["credentials"] == 4
    creds = {c.typ: c for c in svc.credential_repo.list_for_schloss(1)}
    assert creds[CRED_FINGERPRINT].name == "Daumen rechts"
    assert creds[CRED_FINGERPRINT].ttlock_credential_id == 1
    assert creds[CRED_PASSCODE].name == "Putzdienst"
    assert creds[CRED_PASSCODE].gueltig_bis is not None      # ms → ISO
    # Passcode-Klartext darf NICHT mitgespeichert werden (keine neue Angriffsfläche).
    assert "keyboardPwd" not in (creds[CRED_PASSCODE].raw or {})
    assert creds[CRED_EKEY].detail == "max@example.com"      # eKey → TTLock-Konto
    assert creds[CRED_IC].detail == "818229331"              # IC → Kartennummer
    assert all(c.gesehen_am for c in creds.values())


def test_credentials_sync_ersetzt_und_entfernt_verschwundene():
    fake = FakeClient()
    svc = _cred_service(fake)
    svc.inventar_sync()
    fake.passcodes_by_lock[30392116] = [
        {"keyboardPwdId": 1, "keyboardPwdName": "A", "startDate": 0, "endDate": 0},
        {"keyboardPwdId": 2, "keyboardPwdName": "B", "startDate": 0, "endDate": 0}]
    assert svc.credentials_sync()["credentials"] == 2
    # Einer wird am Schloss entfernt → verschwindet beim nächsten Sync auch lokal.
    fake.passcodes_by_lock[30392116] = [
        {"keyboardPwdId": 1, "keyboardPwdName": "A", "startDate": 0, "endDate": 0}]
    svc.credentials_sync()
    pw = [c for c in svc.credential_repo.list_for_schloss(1) if c.typ == CRED_PASSCODE]
    assert len(pw) == 1 and pw[0].ttlock_credential_id == 1


def test_credentials_sync_typ_fehler_laesst_bestand_unangetastet():
    fake = FakeClient()
    fake.fingerprint_should_fail = True          # z. B. Schloss ohne Fingerprint-Sensor
    fake.ekeys_by_lock[30392116] = [
        {"keyId": 9, "keyName": "Trainer", "username": "u", "startDate": 0, "endDate": 0}]
    svc = _cred_service(fake)
    svc.inventar_sync()
    # Bestehender Fingerprint-Mirror (z. B. aus früherem erfolgreichen Sync).
    svc.credential_repo.replace_for_schloss_typ(1, CRED_FINGERPRINT, [
        TuerCredential(schloss_id=1, typ=CRED_FINGERPRINT, ttlock_credential_id=7,
                       name="alt", gesehen_am="2026-06-01T00:00:00+00:00")])

    res = svc.credentials_sync()                 # darf NICHT werfen
    by_typ = {c.typ: c for c in svc.credential_repo.list_for_schloss(1)}
    # Fehlgeschlagener Typ bleibt erhalten (kein fälschliches Leeren), eKey kommt dazu.
    assert by_typ[CRED_FINGERPRINT].name == "alt"
    assert by_typ[CRED_EKEY].ttlock_credential_id == 9
    assert res["credentials"] == 1               # nur der eingefügte eKey zählt


def test_credentials_sync_http_fehler_bricht_lauf_nicht_ab():
    # Regression: ein Transport-/HTTP-Fehler (z. B. falscher Endpoint → 404) bei EINEM Typ
    # darf den Gesamtlauf NICHT abbrechen (sonst stirbt im Sidecar auch der nachgelagerte
    # Log-Sync). Andere Typen werden weiter gespiegelt, der fehlende Typ bleibt unangetastet.
    fake = FakeClient()
    fake.passcode_http_fail = True
    fake.ekeys_by_lock[30392116] = [
        {"keyId": 9, "keyName": "Trainer", "username": "u", "startDate": 0, "endDate": 0}]
    svc = _cred_service(fake)
    svc.inventar_sync()

    res = svc.credentials_sync()                 # darf NICHT werfen
    by_typ = {c.typ: c for c in svc.credential_repo.list_for_schloss(1)}
    assert CRED_PASSCODE not in by_typ           # fehlgeschlagener Typ nicht fälschlich geleert/befüllt
    assert by_typ[CRED_EKEY].ttlock_credential_id == 9
    assert res["credentials"] == 1               # nur der eKey zählt


def test_credentials_sync_ohne_repo_ist_noop():
    # Service ohne credential_repo (Rückwärtskompatibilität) → kein Cloud-Call, 0.
    svc = _service()                             # credential_repo=None
    svc.inventar_sync()
    assert svc.credentials_sync() == {"credentials": 0}


# --- Phase 4: Alarm-Erkennung / Benachrichtigung ----------------------------
class AlarmClient(FakeClient):
    """Liefert genau einen Sabotage-Alarm-Record (recordType 44)."""
    def lock_records(self, lock_id, start_ms, end_ms, page_no=1, page_size=100):
        if page_no > 1:
            return {"list": [], "pages": 1, "pageNo": page_no}
        return {"total": 1, "pages": 1, "pageNo": 1, "list": [
            {"recordId": 99, "recordType": 44, "success": 1, "keyboardPwd": "",
             "keyName": "tamper", "username": "u",
             "lockDate": 1782456500000, "serverDate": 1782456500000},
        ]}


def test_logs_sync_meldet_nur_neue_alarme():
    fake = AlarmClient()
    svc = ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo(), berechtigung_repo=FakeBerechtigungRepo(),
        log_repo=FakeLogRepo(), client_factory=lambda: fake,
    )
    svc.inventar_sync()
    res = svc.logs_sync()
    assert res["neu"] == 1 and len(res["alarme"]) == 1
    a = res["alarme"][0]
    assert a["record_type"] == 44 and a["methode"] == "Sabotage-Alarm" and a["schloss_name"] == "s3"
    # zweiter Lauf: derselbe Record ist dedupliziert → kein erneuter Alarm
    assert svc.logs_sync()["alarme"] == []


def test_logs_sync_normale_records_ohne_alarm():
    # Der Standard-FakeClient liefert recordTypes 7/4/11 → keine Alarme.
    svc = _service()
    svc.inventar_sync()
    assert svc.logs_sync()["alarme"] == []


def test_build_alarm_digest():
    assert build_alarm_digest([]) is None
    titel, text = build_alarm_digest([
        {"schloss_id": 1, "schloss_name": "s3", "record_type": 44,
         "methode": "Sabotage-Alarm", "lock_date": "2026-06-30T10:00:00+00:00"},
    ])
    assert "1" in titel
    assert "s3" in text and "Sabotage-Alarm" in text


# --- Chip-weite Aktionen: sperren / entsperren / löschen ---------------------
# Kern der Sache: Der Chip-Status und der Papierkorb müssen an der TÜR wirken.
# Ein Chip, der in der Liste als gesperrt oder gelöscht steht, aber weiter öffnet,
# ist gefährlicher als gar keine Funktion – man hält das Problem für erledigt.

def _chip_mit_zwei_schloessern(fake):
    """Chip 7, angelernt an zwei Schlössern (das zweite direkt im Fake-Repo)."""
    chip = FakeChip(7, None, kartennummer="818229331", bezeichnung="Chip blau")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()                                   # Schloss id=1 (lockId 30392116)
    svc.schloss_repo._by_id[2] = FakeSchloss(2, 30392117, "Kabine")
    svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")
    svc.chip_anlernen(chip_id=7, schloss_id=2, gueltig_bis="2026-12-31T23:00:00+00:00",
                      actor="admin")
    return svc


def test_chip_sperren_loescht_die_karten_am_schloss():
    """Was nicht am Schloss steht, kann kein Fehler und kein Handgriff in der
    TTLock-App wieder gültig machen."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)

    out = svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")

    assert out["schloesser"] == 2
    assert {d[0] for d in fake.deleted} == {30392116, 30392117}
    assert fake.cards_by_lock[30392116] == [] and fake.cards_by_lock[30392117] == []
    assert svc.chip_repo.get(7).status == "gesperrt"
    # Die Berechtigung bleibt – sie ist das Soll für den Tag, an dem er auftaucht.
    for r in svc.berechtigung_repo.rows.values():
        assert r.deleted is False
        assert r.ttlock_card_id is None and r.sync_status == "gesperrt"


# --- Ist-Spiegel: was wir geschrieben haben, steht sofort da ---------------
# Der Abgleich vergleicht das Soll gegen den gespiegelten Ist-Stand, den der Sync
# viermal am Tag holt. Bliebe der nach einem geglückten Schreibvorgang stehen, hielte
# die App stundenlang eine Abweichung hoch, die sie gerade selbst beseitigt hat — beim
# Sperren sogar das kritische „öffnet noch" für eine längst gelöschte Karte.

def test_sperren_nimmt_die_karten_aus_dem_ist_spiegel():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    assert list(_spiegel(svc, 1)) == [9001] and list(_spiegel(svc, 2)) == [9001]

    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")

    # Kein Ist mehr = kein Befund: Genau darauf prüft der Abgleich (s.
    # test_zutritt_abgleich_service::test_gesperrter_chip_ohne_karte_am_schloss...).
    assert _spiegel(svc, 1) == {} and _spiegel(svc, 2) == {}


def test_entsperren_traegt_die_karte_mit_ihrer_gueltigkeit_wieder_ein():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")

    svc.chip_status_setzen(chip_id=7, status="aktiv", actor="admin")

    karte = _spiegel(svc, 2)[9001]
    assert karte.detail == "818229331" and karte.name == "Chip blau"
    assert karte.gueltig_bis == "2026-12-31T23:00:00+00:00"


def test_spiegel_erbt_den_stand_des_schlosses_statt_jetzt():
    """Geschrieben ist nicht gelesen. Ein frischer Zeitstempel machte jedes ANDERE
    Schloss zum veralteten Spiegel – und entwertete dort echte Befunde."""
    fake = FakeClient()
    chip = FakeChip(7, None, kartennummer="818229331", bezeichnung="Chip blau")
    svc = _p2_service(fake, chip_map={"818229331": chip})
    svc.inventar_sync()
    svc.credential_repo.replace_for_schloss_typ(1, CRED_IC, [
        TuerCredential(schloss_id=1, typ=CRED_IC, ttlock_credential_id=4242,
                       detail="999", gesehen_am="2026-08-20T06:00:00+00:00")])

    svc.chip_anlernen(chip_id=7, schloss_id=1, actor="admin")

    assert _spiegel(svc, 1)[9001].gesehen_am == "2026-08-20T06:00:00+00:00"


def test_gueltigkeit_aendern_zieht_das_fenster_im_spiegel_nach():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)

    svc.berechtigung_aendern(berechtigung_id=1, gueltig_bis="2027-06-30T22:00:00+00:00",
                             actor="admin")

    assert _spiegel(svc, 1)[9001].gueltig_bis == "2027-06-30T22:00:00+00:00"


def test_entziehen_nimmt_die_karte_aus_dem_ist_spiegel():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)

    svc.berechtigung_entziehen(berechtigung_id=1, actor="admin")

    assert _spiegel(svc, 1) == {} and list(_spiegel(svc, 2)) == [9001]


def test_chip_entsperren_lernt_die_karten_wieder_an():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")
    fake.added.clear()

    svc.chip_status_setzen(chip_id=7, status="aktiv", actor="admin")

    # Angelernt wird mit der hinterlegten Gültigkeit, nicht mit irgendeinem Fenster.
    nach_schloss = {a[0]: (a[2], a[3]) for a in fake.added}
    assert nach_schloss[30392116] == (0, 0)               # war unbefristet
    assert nach_schloss[30392117] == (0, _iso_to_ms("2026-12-31T23:00:00+00:00"))
    assert svc.chip_repo.get(7).status == "aktiv"
    for r in svc.berechtigung_repo.rows.values():
        assert r.ttlock_card_id is not None and r.sync_status == "aktiv"


def test_chip_sperren_bei_cloud_fehler_aendert_den_status_nicht():
    """Sonst stünde „gesperrt" in der Liste, während die Karte weiter öffnet."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True

    with pytest.raises(TTLockError):
        svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")

    assert svc.chip_repo.get(7).status == "aktiv"
    assert all(r.sync_status == "fehler" and r.sync_fehler
               for r in svc.berechtigung_repo.rows.values())


def test_gesperrter_chip_laesst_sich_nicht_anlernen():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")
    svc.schloss_repo._by_id[3] = FakeSchloss(3, 30392118, "Lager")
    fake.added.clear()

    with pytest.raises(ValueError):
        svc.chip_anlernen(chip_id=7, schloss_id=3, actor="admin")
    assert fake.added == []


def test_chip_loeschen_entfernt_die_karten_von_allen_schloessern():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)

    out = svc.chip_loeschen(chip_id=7, actor="admin")

    assert out["berechtigungen_entzogen"] == 2
    assert {d[0] for d in fake.deleted} == {30392116, 30392117}
    assert svc.chip_repo.get(7) is None
    assert all(r.deleted for r in svc.berechtigung_repo.rows.values())


def test_chip_loeschen_bricht_ab_wenn_ein_schloss_nicht_erreichbar_ist():
    """Der Chip bleibt bestehen – sonst öffnete er unsichtbar weiter."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True

    with pytest.raises(TTLockError):
        svc.chip_loeschen(chip_id=7, actor="admin")

    assert svc.chip_repo.get(7) is not None
    assert fake.deleted == []


# --- Karte am Schloss nicht (mehr) vorhanden: errcode −1021 ----------------
# Aus der Praxis: Ein verlorener Chip wurde gesperrt, ein Schloss lief auf einen
# Fehler, beim zweiten Versuch meldete die Cloud dort „This IC Card does not
# exist". Das ist keine Störung, sondern der Ist-Zustand – und fürs Sperren
# genau das Ziel.

def test_sperren_akzeptiert_eine_karte_die_es_am_schloss_nicht_mehr_gibt():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True
    fake.delete_errcode = -1021

    out = svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")

    assert svc.chip_repo.get(7).status == "verloren"       # Status wird gesetzt
    assert out["ohne_karte"] == 2 and out["schloesser"] == 0
    # Die Zeile behauptet keine tote cardId mehr und steht nicht auf „fehler".
    for r in svc.berechtigung_repo.rows.values():
        assert r.ttlock_card_id is None
        assert r.sync_status == "gesperrt" and r.sync_fehler is None


def test_sperren_bleibt_bei_einer_echten_stoerung_hart():
    """Gegenprobe: −3003 (Gateway offline) ist weiterhin ein Fehler."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True

    with pytest.raises(TTLockError):
        svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")
    assert svc.chip_repo.get(7).status == "aktiv"


def test_entsperren_meldet_wenn_das_neu_anlernen_scheitert():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")
    fake.add_should_fail = True

    with pytest.raises(TTLockError):
        svc.chip_status_setzen(chip_id=7, status="aktiv", actor="admin")
    assert svc.chip_repo.get(7).status == "gesperrt"


def test_entziehen_ist_erledigt_wenn_die_karte_schon_weg_ist():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.delete_should_fail = True
    fake.delete_errcode = -1021

    out = svc.berechtigung_entziehen(berechtigung_id=ber_id, actor="admin")

    assert out == {"ok": True}
    assert svc.berechtigung_repo.rows[ber_id].deleted is True


def test_chip_loeschen_laeuft_durch_wenn_karten_schon_weg_sind():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True
    fake.delete_errcode = -1021

    out = svc.chip_loeschen(chip_id=7, actor="admin")

    assert out["berechtigungen_entzogen"] == 2
    assert svc.chip_repo.get(7) is None


def test_gueltigkeit_aendern_spielt_eine_fehlende_karte_neu_auf():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.added.clear()
    fake.change_should_fail = True
    fake.change_errcode = -1021

    ber = svc.berechtigung_aendern(berechtigung_id=ber_id,
                                   gueltig_bis="2027-06-30T22:00:00+00:00", actor="admin")

    assert ber.gueltig_bis == "2027-06-30T22:00:00+00:00"
    assert fake.added and fake.added[0][3] == _iso_to_ms("2027-06-30T22:00:00+00:00")
    assert ber.sync_status == "aktiv"


def test_gueltigkeit_aendern_holt_gesperrte_karten_nicht_zurueck_aufs_schloss():
    """Bei einem gesperrten Chip wird die Gültigkeit gepflegt, mehr nicht.

    Ein `changePeriod` mit dem neuen Fenster machte die Karte am Schloss wieder
    gültig – der verlorene Chip öffnete wieder, ohne dass irgendwo „aktiv" stünde.
    """
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.added.clear()
    fake.changed.clear()

    ber = svc.berechtigung_aendern(berechtigung_id=ber_id,
                                   gueltig_bis="2027-06-30T22:00:00+00:00", actor="admin")

    assert fake.added == [] and fake.changed == []      # die Cloud bleibt unberührt
    assert ber.gueltig_bis == "2027-06-30T22:00:00+00:00"
    assert ber.sync_status == "gesperrt"


def test_ic_card_sync_dreht_gesperrte_tueren_nicht_auf_aktiv_zurueck():
    """Die Karte liegt am Schloss – aber mit abgelaufenem Fenster. Zöge der Sync sie
    wieder auf „aktiv", stellte er bei jedem Lauf die Behauptung her, die das Sperren
    gerade beseitigt hat."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")

    res = svc.ic_cards_sync()

    assert res["berechtigungen_akt"] == 0 and res["berechtigungen_neu"] == 0
    assert {b.sync_status for b in svc.berechtigung_repo.list_for_chip(7)} == {"gesperrt"}


def test_gesperrter_chip_steht_an_seinen_tueren_als_gesperrt():
    """Sonst behauptet die Türliste eines verlorenen Chips überall „aktiv"."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)

    svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")
    assert {b.sync_status for b in svc.berechtigung_repo.list_for_chip(7)} == {"gesperrt"}

    svc.chip_status_setzen(chip_id=7, status="aktiv", actor="admin")
    assert {b.sync_status for b in svc.berechtigung_repo.list_for_chip(7)} == {"aktiv"}


def test_fehlertexte_sagen_was_zu_tun_ist():
    """Die Rohmeldung der Cloud ist zweisprachig und beantwortet die einzige Frage
    nicht, die der Anwender hat: nochmal versuchen oder nicht?"""
    # errcode 1 ist TTLocks Sammelfehler ("failed or means no") – keine Aussage über
    # die Karte, also bleibt es ein Fehler, nur mit brauchbarem Text.
    sammel = TTLockError("v3/identityCard/changePeriod: errcode=1 failed or means no",
                         errcode=1)
    assert "erneut versuchen" in fehlertext(sammel)
    assert "errcode=1" in fehlertext(sammel)          # Rohmeldung bleibt zur Fehlersuche
    assert karte_fehlt(sammel) is False               # wird NICHT als erledigt gewertet
    assert ist_dauerhaft(sammel) is False             # und auch nicht als Absage

    assert "Gateway" in fehlertext(TTLockError("offline", errcode=-3003))
    # Unbekannte Codes bleiben, wie sie sind – lieber roh als falsch gedeutet.
    assert fehlertext(TTLockError("xy", errcode=-9999)) == "xy"


def test_sammelfehler_laesst_den_chip_status_stehen():
    """Gegenprobe: Steht die Karte laut Cloud unverändert am Schloss, sagt errcode=1
    nichts – dann darf ein verlorener Chip nicht als gesperrt gelten, während er
    weiter öffnet."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.delete_should_fail = True
    fake.delete_errcode = 1

    with pytest.raises(TTLockError):
        svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")

    assert svc.chip_repo.get(7).status == "aktiv"
    for r in svc.berechtigung_repo.rows.values():
        assert r.sync_status == "fehler"
        assert "erneut versuchen" in r.sync_fehler
        assert r.ttlock_card_id is not None            # die Karte bleibt bekannt


def test_sammelfehler_mit_karte_nicht_in_der_liste_gilt_als_gesperrt():
    """errcode=1 sagt nur „hat nicht geklappt". Die Kartenliste sagt, was gilt: Ist
    die Karte dort nicht geführt, gibt es auch nichts mehr zu löschen."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    fake.cards_by_lock = {}                    # Schlösser kennen die Karte nicht (mehr)
    fake.delete_should_fail = True
    fake.delete_errcode = 1

    out = svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")

    assert svc.chip_repo.get(7).status == "verloren"
    assert out["ohne_karte"] == 2
    for r in svc.berechtigung_repo.rows.values():
        assert r.ttlock_card_id is None and r.sync_status == "gesperrt"


def test_zweites_sperren_findet_nichts_mehr_zu_loeschen():
    """Zustandsbasiert: Was beim ersten Mal weg ist, wird nicht noch einmal gelöscht."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    svc.chip_status_setzen(chip_id=7, status="gesperrt", actor="admin")
    fake.deleted.clear()

    out = svc.chip_status_setzen(chip_id=7, status="verloren", actor="admin")

    assert svc.chip_repo.get(7).status == "verloren"
    assert fake.deleted == [] and out["schloesser"] == 0


def test_sammelfehler_beim_richten_einer_aktiven_karte_bleibt_ein_fehler():
    """errcode=1 mit weiterhin gelisteter Karte sagt nur „nicht angekommen"."""
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.change_should_fail = True
    fake.change_errcode = 1

    with pytest.raises(TTLockError):
        svc.berechtigung_aendern(berechtigung_id=ber_id,
                                 gueltig_bis="2027-06-30T22:00:00+00:00", actor="admin")
    assert svc.berechtigung_repo.rows[ber_id].sync_status == "fehler"


def test_entziehen_bei_sammelfehler_und_fehlender_karte_ist_erledigt():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.cards_by_lock = {}
    fake.delete_should_fail = True
    fake.delete_errcode = 1

    assert svc.berechtigung_entziehen(berechtigung_id=ber_id, actor="admin") == {"ok": True}
    assert svc.berechtigung_repo.rows[ber_id].deleted is True


def test_entziehen_bei_sammelfehler_mit_vorhandener_karte_bleibt_fehler():
    fake = FakeClient()
    svc = _chip_mit_zwei_schloessern(fake)
    ber_id = next(iter(svc.berechtigung_repo.rows))
    fake.delete_should_fail = True
    fake.delete_errcode = 1

    with pytest.raises(TTLockError):
        svc.berechtigung_entziehen(berechtigung_id=ber_id, actor="admin")
    assert svc.berechtigung_repo.rows[ber_id].deleted is False


def test_karte_wirkungslos_erkennt_nur_abgelaufene_fenster():
    jetzt = 1_000_000
    assert karte_wirkungslos({"startDate": 10, "endDate": 20}, jetzt) is True
    assert karte_wirkungslos({"startDate": 0, "endDate": 0}, jetzt) is False      # unbefristet
    assert karte_wirkungslos({"startDate": 10, "endDate": 2_000_000}, jetzt) is False


def test_karte_fehlt_erkennt_nur_den_passenden_errcode():
    assert karte_fehlt(TTLockError("weg", errcode=-1021)) is True
    assert karte_fehlt(TTLockError("offline", errcode=-3003)) is False
    assert karte_fehlt(ValueError("kein Cloud-Fehler")) is False
    assert "nicht mehr vor" in fehlertext(TTLockError("weg", errcode=-1021))


# ---------------------------------------------------------------------------
# Rechtegruppen (#169): der Abgleich Chip ↔ Gruppen
# ---------------------------------------------------------------------------

class FakeGruppe:
    def __init__(self, id, name):
        self.id, self.name = id, name
        self.schloss_ids = []


class FakeGruppeRepo:
    """Fake von db.chip_gruppen – hält nur den SOLL-Zustand."""

    def __init__(self):
        self.gruppen = {}            # id -> FakeGruppe
        self.chips = {}              # gruppe_id -> set(chip_id)
        self._next = 1
        self.geloescht = []

    def anlegen(self, name, schloss_ids=()):
        g = FakeGruppe(self._next, name); self._next += 1
        g.schloss_ids = list(schloss_ids)
        self.gruppen[g.id] = g
        self.chips[g.id] = set()
        return g

    def get(self, id):
        return self.gruppen.get(id)

    def schloss_ids(self, gruppe_id):
        g = self.gruppen.get(gruppe_id)
        return list(g.schloss_ids) if g else []

    def set_schloesser(self, gruppe_id, schloss_ids, by):
        self.gruppen[gruppe_id].schloss_ids = list(schloss_ids)
        return list(schloss_ids)

    def chip_ids(self, gruppe_id):
        return sorted(self.chips.get(gruppe_id, set()))

    def gruppen_fuer_chip(self, chip_id):
        return [g for g in self.gruppen.values() if chip_id in self.chips.get(g.id, set())]

    def soll_schloss_ids_fuer_chip(self, chip_id):
        soll = set()
        for g in self.gruppen_fuer_chip(chip_id):
            soll |= set(g.schloss_ids)
        return sorted(soll)

    def quelle_gruppe(self, chip_id, schloss_id):
        treffer = [g for g in self.gruppen_fuer_chip(chip_id) if schloss_id in g.schloss_ids]
        return sorted(treffer, key=lambda g: g.name)[0].id if treffer else None

    def chip_zuordnen(self, gruppe_id, chip_id, by):
        self.chips[gruppe_id].add(chip_id)

    def chip_entfernen(self, gruppe_id, chip_id, by):
        self.chips[gruppe_id].discard(chip_id)
        return True

    def alle_chips_entfernen(self, gruppe_id, by):
        chips = sorted(self.chips.get(gruppe_id, set()))
        self.chips[gruppe_id] = set()
        return chips

    def soft_delete(self, id, deleted_by):
        self.geloescht.append(id)
        self.gruppen.pop(id, None)
        return True


def _gruppen_service(fake_client=None, chip_status="aktiv"):
    """Service mit einem Chip und drei Cloud-Schlössern (ids 1..3)."""
    fake = fake_client or FakeClient()
    chip = FakeChip(1, mitglied_id=10, kartennummer="ABC", bezeichnung="Chip Wagner",
                    status=chip_status)
    schloss_repo = FakeSchlossRepo()
    for nr in range(1, 4):
        s = FakeSchloss(nr, 3000 + nr, f"Tür {nr}")
        schloss_repo._by_id[nr] = s
        schloss_repo._by_lock[s.ttlock_lock_id] = s
    schloss_repo._next = 4
    svc = ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=schloss_repo,
        chip_repo=FakeChipRepo({"ABC": chip}), berechtigung_repo=FakeBerechtigungRepo(),
        gruppe_repo=FakeGruppeRepo(), log_repo=FakeLogRepo(),
        credential_repo=FakeCredentialRepo(), client_factory=lambda: fake,
    )
    return svc, fake


def _tueren(svc, chip_id=1):
    return sorted(b.schloss_id for b in svc.berechtigung_repo.list_for_chip(chip_id))


class TestGruppenAbgleich:
    def test_gruppe_zuordnen_erteilt_alle_tueren(self):
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        res = svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["erteilt"] == 2 and res["fehler"] == []
        assert _tueren(svc) == [1, 2]
        # An jedem Schloss ist eine IC-Karte angelegt worden (an die TTLock-lockId).
        assert sorted(lock for lock, *_ in fake.added) == [3001, 3002]

    def test_herkunft_steht_an_der_berechtigung(self):
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert svc.berechtigung_repo.list_for_chip(1)[0].gruppe_id == g.id

    def test_neue_tuer_in_der_gruppe_erreicht_alle_chips(self):
        """Der eigentliche Gewinn: eine Tür dazu, und alle Träger haben sie."""
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        # Tür 3 kommt dazu, Tür 2 fällt raus – beides wirkt sofort auf den Chip.
        res = svc.gruppe_schloesser_setzen(gruppe_id=g.id, schloss_ids=[1, 3], actor="admin")
        assert res["erteilt"] == 1 and res["entzogen"] == 1
        assert _tueren(svc) == [1, 3]

    def test_gruppe_entziehen_nimmt_ihre_tueren_weg(self):
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        res = svc.gruppe_chip_entfernen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["entzogen"] == 2
        assert _tueren(svc) == []

    def test_einzeln_erteilte_tuer_bleibt_unangetastet(self):
        """Sonst nähme die erste Gruppenzuordnung dem Chip weg, was jemand
        bewusst einzeln vergeben hat."""
        svc, _ = _gruppen_service()
        svc.chip_anlernen(chip_id=1, schloss_id=3, actor="admin")     # von Hand
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert _tueren(svc) == [1, 3]
        svc.gruppe_chip_entfernen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert _tueren(svc) == [3]

    def test_zwei_gruppen_teilen_sich_eine_tuer(self):
        """Nimmt man die eine Gruppe weg, bleibt die Tür – die andere fordert sie."""
        svc, _ = _gruppen_service()
        a = svc.gruppe_repo.anlegen("Abteilungsleiter", [1, 2])
        b = svc.gruppe_repo.anlegen("Übungsleiter", [2, 3])
        svc.gruppe_chip_zuordnen(gruppe_id=a.id, chip_id=1, actor="admin")
        svc.gruppe_chip_zuordnen(gruppe_id=b.id, chip_id=1, actor="admin")
        assert _tueren(svc) == [1, 2, 3]
        svc.gruppe_chip_entfernen(gruppe_id=a.id, chip_id=1, actor="admin")
        assert _tueren(svc) == [2, 3]

    def test_abgleich_ist_wiederholbar(self):
        """Zustandsbasiert: ein zweiter Lauf ändert nichts."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        res = svc.chip_gruppen_abgleichen(chip_id=1, actor="admin")
        assert res == {"chip_id": 1, "erteilt": 0, "entzogen": 0, "gerichtet": 0,
                       "bestaetigt": 0, "fehler": []}
        assert len(fake.added) == 2

    def test_offline_schloss_blockiert_die_uebrigen_nicht(self):
        """Jede Tür ist ein eigener Cloud-Vorgang; eine kaputte darf nicht alle
        anderen verhindern."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        fake.add_should_fail = True
        res = svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["erteilt"] == 0 and len(res["fehler"]) == 2
        assert res["fehler"][0]["schloss"] == "Tür 1"

    def test_nachfassen_spielt_die_karte_erneut_auf(self):
        """Maßstab ist die Karte am Schloss, nicht die Zeile in der Tabelle: Eine
        gescheiterte Erteilung hinterlässt eine Zeile OHNE cardId – die Tür lässt
        sich nicht öffnen und muss beim nächsten Lauf erneut versucht werden."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        fake.add_should_fail = True
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        offen = svc.berechtigung_repo.list_for_chip(1)
        assert all(b.sync_status == "fehler" and b.ttlock_card_id is None for b in offen)

        fake.add_should_fail = False
        res = svc.chip_gruppen_abgleichen(chip_id=1, actor="admin")
        assert res["erteilt"] == 2 and res["fehler"] == []
        jetzt = svc.berechtigung_repo.list_for_chip(1)
        assert all(b.sync_status == "aktiv" and b.ttlock_card_id for b in jetzt)
        # Kein zweiter Datensatz je Tür – dieselben Zeilen, nur jetzt wirksam.
        assert {b.id for b in jetzt} == {b.id for b in offen}
        assert sorted(lock for lock, *_ in fake.added) == [3001, 3002]

    def test_nachfassen_ruehrt_von_hand_erteiltes_nicht_an(self):
        """Auch eine gescheiterte Einzelberechtigung gehört dem Menschen, der sie
        erteilt hat – der Gruppen-Abgleich fasst sie nicht an."""
        svc, fake = _gruppen_service()
        fake.add_should_fail = True
        with pytest.raises(TTLockError):
            svc.chip_anlernen(chip_id=1, schloss_id=3, actor="admin")
        fake.add_should_fail = False
        res = svc.chip_gruppen_abgleichen(chip_id=1, actor="admin")
        assert res == {"chip_id": 1, "erteilt": 0, "entzogen": 0, "gerichtet": 0,
                       "bestaetigt": 0, "fehler": []}
        assert svc.berechtigung_repo.list_for_chip(1)[0].sync_status == "fehler"

    def test_absage_des_schlosses_wird_als_dauerhaft_gemeldet(self):
        """errcode -4043 heißt nicht „offline", sondern „kann das Modell nicht".
        Ein Wiederholen wird da nie helfen – das muss der Anwender sehen."""
        svc, fake = _gruppen_service()
        fake.add_errcode = -4043
        fake.add_should_fail = True
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        res = svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["fehler"][0]["dauerhaft"] is True
        assert res["fehler"][0]["meldung"].startswith("Das Schloss unterstützt keine Chip-Karten")

    def test_abgleichen_richtet_die_karten_am_schloss(self):
        """Der Knopf, den man drückt, wenn der Soll-Ist-Abgleich etwas meldet: Eine
        Sperre, die nicht bis zum Schloss kam, wird hier nachgeholt."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.chip_repo.get(1).status = "verloren"      # ohne die Karten zu entfernen
        fake.deleted.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert res["gerichtet"] == 2 and res["fehler"] == []
        assert {d[0] for d in fake.deleted} == {3001, 3002}
        assert fake.cards_by_lock[3001] == [] and fake.cards_by_lock[3002] == []
        assert {b.sync_status for b in svc.berechtigung_repo.list_for_chip(1)} == {"gesperrt"}

    def test_abgleichen_stellt_die_hinterlegte_gueltigkeit_wieder_her(self):
        """Bei aktivem Chip zählt, was bei uns steht – nicht, was jemand in der
        TTLock-App am Schloss verstellt hat."""
        svc, fake = _gruppen_service()
        svc.chip_anlernen(chip_id=1, schloss_id=1,
                          gueltig_bis="2026-12-31T23:00:00+00:00", actor="admin")
        fake.cards_by_lock[3001][0]["endDate"] = 0        # am Schloss auf unbefristet
        fake.changed.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert fake.changed == [(3001, 9001, 0, _iso_to_ms("2026-12-31T23:00:00+00:00"))]
        assert res["gerichtet"] == 1 and res["bestaetigt"] == 0

    def test_abgleichen_bringt_auch_einen_alten_spiegel_auf_stand(self):
        """Der Fall ganz ohne Schreibvorgang: Am Schloss stimmt alles, nur unser Ist-Stand
        ist alt. Nachgesehen haben wir gerade – das gehört in den Spiegel, sonst bliebe
        der Fenster-Befund stehen und kein weiterer Klick löste ihn je auf."""
        svc, fake = _gruppen_service()
        svc.chip_anlernen(chip_id=1, schloss_id=1, actor="admin")
        svc.credential_repo.ic_karte_gesetzt(          # Spiegel von gestern: befristet
            1, credential_id=9001, name="Chip Wagner", kartennummer="ABC",
            gueltig_von=None, gueltig_bis="2026-01-01T00:00:00+00:00")
        fake.changed.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert fake.changed == [] and res["bestaetigt"] == 1
        assert _spiegel(svc, 1)[9001].gueltig_bis is None

    def test_abgleichen_schreibt_nur_wo_es_abweicht(self):
        """Jeder Schreibvorgang geht übers Gateway bis ans Schloss. Was dort schon
        stimmt, wird gelesen und bestätigt – nicht neu geschrieben."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        fake.cards_by_lock[3002][0]["endDate"] = 1798758000000   # nur Tür 2 verstellt
        fake.changed.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert [c[0] for c in fake.changed] == [3002]
        assert res["gerichtet"] == 1 and res["bestaetigt"] == 1

    def test_abgleichen_bestaetigt_eine_schon_entfernte_karte(self):
        """Zweiter Klick: Die Karten sind weg, es bleibt beim Nachsehen – die Prüfung
        läuft dann über die Kartennummer, denn eine cardId gibt es nicht mehr."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.chip_repo.get(1).status = "verloren"
        svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")
        fake.deleted.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert fake.deleted == [] and res["bestaetigt"] == 2

    def test_abgleichen_entfernt_eine_heimlich_angelernte_karte(self):
        """Ohne cardId hilft die Nummer: Was jemand per BLE an der App vorbei angelernt
        hat, gehört bei einem verlorenen Chip trotzdem nicht ans Schloss."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.chip_repo.get(1).status = "verloren"
        svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")
        fake.cards_by_lock[3001] = [{"cardId": 4242, "cardNumber": "ABC",
                                     "cardName": "von Hand", "startDate": 0, "endDate": 0}]
        fake.deleted.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert fake.deleted == [(3001, 4242)] and res["gerichtet"] == 1

    def test_gruppen_abgleich_fasst_die_karten_nicht_an(self):
        """Über alle Chips einer Gruppe wären das hunderte Gateway-Aufrufe für einen
        Zustand, der meistens stimmt – Karten richtet nur der Knopf am Chip."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        fake.changed.clear()

        res = svc.chip_gruppen_abgleichen(chip_id=1, actor="admin")

        assert fake.changed == [] and res["gerichtet"] == 0

    def test_ein_offline_schloss_haelt_das_richten_nicht_auf(self):
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        for karten in fake.cards_by_lock.values():
            for k in karten:
                k["endDate"] = 1798758000000      # überall verstellt → muss geschrieben werden
        fake.change_should_fail = True
        fake.change_errcode = -3003

        res = svc.chip_gruppen_abgleichen(chip_id=1, karten_richten=True, actor="admin")

        assert res["gerichtet"] == 0 and len(res["fehler"]) == 2
        assert all(not f["dauerhaft"] for f in res["fehler"])

    def test_offline_schloss_bleibt_ein_vorlaeufiger_fehler(self):
        svc, fake = _gruppen_service()
        fake.add_should_fail = True          # Standard-errcode: Störung, nicht Absage
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        res = svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["fehler"][0]["dauerhaft"] is False

    def test_absage_steht_auch_an_der_gespeicherten_zeile(self):
        """Die Notification ist weg, sobald man wegklickt – die Zeile bleibt."""
        svc, fake = _gruppen_service()
        fake.add_errcode = -4043
        fake.add_should_fail = True
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        ber = svc.berechtigung_repo.list_for_chip(1)[0]
        assert ber.sync_fehler.startswith("Das Schloss unterstützt keine Chip-Karten")
        assert "-4043" in ber.sync_fehler          # rohe Meldung bleibt für die Fehlersuche

    def test_gescheiterte_erteilung_laesst_sich_per_gruppenentzug_aufloesen(self):
        """Kommt das Schloss nie wieder, muss die Leiche verschwinden können –
        ohne Karte am Schloss ist das ein reiner Datenbank-Vorgang."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        fake.add_should_fail = True
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        fake.delete_should_fail = True          # Schloss weiterhin nicht erreichbar
        res = svc.gruppe_chip_entfernen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["entzogen"] == 1 and _tueren(svc) == []

    def test_haengengebliebene_karte_wird_beim_naechsten_lauf_entzogen(self):
        """Scheitert das Entziehen (Schloss offline), bleibt die Zeile mit Herkunft
        stehen, obwohl keine Gruppe sie mehr fordert – der nächste Lauf holt es nach."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        fake.delete_should_fail = True
        res = svc.gruppe_chip_entfernen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["entzogen"] == 0 and len(res["fehler"]) == 1
        assert _tueren(svc) == [1]
        fake.delete_should_fail = False
        res = svc.chip_gruppen_abgleichen(chip_id=1, actor="admin")
        assert res["entzogen"] == 1 and _tueren(svc) == []

    def test_gesperrter_chip_bekommt_keine_neuen_tueren(self):
        svc, _ = _gruppen_service(chip_status="gesperrt")
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        res = svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["erteilt"] == 0 and _tueren(svc) == []
        assert "gesperrt" in res["fehler"][0]["meldung"]

    def test_gesperrter_chip_verliert_trotzdem_was_wegfaellt(self):
        """Weniger Rechte sind bei einem gesperrten Chip nie das Problem."""
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.chip_repo.get(1).status = "verloren"
        res = svc.gruppe_chip_entfernen(gruppe_id=g.id, chip_id=1, actor="admin")
        assert res["entzogen"] == 1 and _tueren(svc) == []

    def test_gruppen_abgleich_fasst_fuer_alle_traeger_nach(self):
        """Bei zwanzig Trägern ist das der Unterschied zwischen einem Klick und zwanzig."""
        svc, fake = _gruppen_service()
        chip2 = FakeChip(2, mitglied_id=11, kartennummer="XYZ", bezeichnung="Chip Kern")
        svc.chip_repo._by_id[2] = chip2
        svc.chip_repo._m["XYZ"] = chip2
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        fake.add_should_fail = True
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=2, actor="admin")

        fake.add_should_fail = False
        res = svc.gruppe_abgleichen(gruppe_id=g.id, actor="admin")
        assert res["chips"] == 2 and res["erteilt"] == 2 and res["fehler"] == []
        assert _tueren(svc, 1) == [1] and _tueren(svc, 2) == [1]

    def test_fehler_im_gruppen_abgleich_nennt_den_chip(self):
        """Sonst wüsste man nicht, wessen Tür hängt."""
        svc, fake = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_repo.chip_zuordnen(g.id, 1, "admin")
        fake.add_should_fail = True
        res = svc.gruppe_abgleichen(gruppe_id=g.id, actor="admin")
        assert res["fehler"][0]["chip"] == "Chip Wagner"
        assert res["fehler"][0]["schloss"] == "Tür 1"

    def test_gruppe_aufloesen_raeumt_die_chips_ab(self):
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1, 2])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        res = svc.gruppe_loeschen(gruppe_id=g.id, actor="admin")
        assert res["geloescht"] is True and res["entzogen"] == 2
        assert _tueren(svc) == []
        assert svc.gruppe_repo.geloescht == [g.id]

    def test_chip_loeschen_nimmt_die_gruppen_mit(self):
        """Ein gelöschter Chip, der weiter in „Übungsleiter" steht, tauchte in
        jeder Gruppenzählung auf."""
        svc, _ = _gruppen_service()
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=1, actor="admin")
        svc.chip_loeschen(chip_id=1, actor="admin")
        assert svc.gruppe_repo.chip_ids(g.id) == []

    def test_unbekannte_gruppe_oder_chip(self):
        svc, _ = _gruppen_service()
        with pytest.raises(ValueError):
            svc.gruppe_chip_zuordnen(gruppe_id=99, chip_id=1, actor="admin")
        g = svc.gruppe_repo.anlegen("Übungsleiter", [1])
        with pytest.raises(ValueError):
            svc.gruppe_chip_zuordnen(gruppe_id=g.id, chip_id=99, actor="admin")
