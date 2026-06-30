"""
Tests für ZutrittService – Orchestrierung ohne Netz/DB (Fakes für Client + Repos).

Geprüft:
- inventar_sync spiegelt Schlösser inkl. Online-Status (aus gateway/list) und Akku.
- logs_sync ist idempotent (Dedupe über recordId) und schreibt den Cursor fort.
- Kartennummer → Chip → Mitglied wird nur für IC-Karten-Records aufgelöst.
- Status-Snapshot (letztes Event) entspricht dem jüngsten Log.
"""
import pytest

from app.services.zutritt_service import ZutrittService, build_alarm_digest
from app.services.ttlock_client import TTLockError


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

    def unlock(self, lock_id):
        self.unlocked.append(lock_id); return {"errcode": 0}

    def remote_lock(self, lock_id):
        self.locked.append(lock_id); return {"errcode": 0}

    def ic_card_add(self, lock_id, card_number, card_name, start_ms=0, end_ms=0, *, add_type=2):
        if self.add_should_fail:
            raise TTLockError("add fehlgeschlagen", errcode=-3007)
        self.added.append((lock_id, card_number, start_ms, end_ms)); return {"errcode": 0, "cardId": 9001}

    def ic_card_change_period(self, lock_id, card_id, start_ms=0, end_ms=0, *, change_type=2):
        self.changed.append((lock_id, card_id, start_ms, end_ms)); return {"errcode": 0}

    def ic_card_delete(self, lock_id, card_id, *, delete_type=2):
        self.deleted.append((lock_id, card_id)); return {"errcode": 0}

    def ic_cards(self, lock_id, page_no=1, page_size=100):
        return {"list": self.cards_by_lock.get(lock_id, [])}

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

    def list_all(self, nur_aktive=False):
        return [s for s in self._by_id.values() if s.aktiv or not nur_aktive]

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
    def __init__(self, id, mitglied_id, kartennummer="", bezeichnung=None):
        self.id, self.mitglied_id = id, mitglied_id
        self.kartennummer, self.bezeichnung = kartennummer, bezeichnung


class FakeChipRepo:
    def __init__(self, mapping=None):
        self._m = mapping or {}
        self._by_id = {c.id: c for c in self._m.values()}
        self._next = (max(self._by_id) + 1) if self._by_id else 1

    def find_active_by_kartennummer(self, kn):
        return self._m.get(kn)

    def get(self, id):
        return self._by_id.get(id)

    def create(self, c, created_by):
        chip = FakeChip(self._next, getattr(c, "mitglied_id", None),
                        kartennummer=c.kartennummer, bezeichnung=c.bezeichnung)
        self._by_id[chip.id] = chip; self._m[c.kartennummer] = chip; self._next += 1
        return chip


class FakeBer:
    def __init__(self, id, chip_id, schloss_id, **kw):
        self.id, self.chip_id, self.schloss_id = id, chip_id, schloss_id
        self.ttlock_card_id = kw.get("ttlock_card_id")
        self.gueltig_von = kw.get("gueltig_von")
        self.gueltig_bis = kw.get("gueltig_bis")
        self.sync_status = kw.get("sync_status") or "pending"
        self.sync_fehler = kw.get("sync_fehler")
        self.erteilt_von = kw.get("erteilt_von")
        self.deleted = False


class FakeBerechtigungRepo:
    def __init__(self):
        self.rows, self._next = {}, 1

    def create(self, b, created_by):
        r = FakeBer(self._next, b.chip_id, b.schloss_id, ttlock_card_id=b.ttlock_card_id,
                    gueltig_von=b.gueltig_von, gueltig_bis=b.gueltig_bis,
                    sync_status=b.sync_status, erteilt_von=b.erteilt_von)
        self.rows[r.id] = r; self._next += 1
        return r

    def get(self, id):
        r = self.rows.get(id)
        return r if (r and not r.deleted) else None

    def find_active_for_chip_schloss(self, chip_id, schloss_id):
        return next((r for r in self.rows.values()
                     if not r.deleted and r.chip_id == chip_id and r.schloss_id == schloss_id), None)

    def set_sync(self, id, *, ttlock_card_id, sync_status, sync_fehler, by):
        r = self.rows[id]
        r.ttlock_card_id, r.sync_status, r.sync_fehler = ttlock_card_id, sync_status, sync_fehler
        return r

    def update_period(self, id, *, gueltig_von, gueltig_bis, by):
        r = self.rows[id]
        r.gueltig_von, r.gueltig_bis = gueltig_von, gueltig_bis
        r.sync_status, r.sync_fehler = "aktiv", None
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


class FakeKontoRepo:
    def __init__(self):
        self.synced = []

    def get(self):
        return None

    def save_tokens(self, **k):
        pass

    def touch_sync(self, when_iso, **k):
        self.synced.append(when_iso)


def _service(chip_map=None):
    return ZutrittService(
        konto_repo=FakeKontoRepo(), schloss_repo=FakeSchlossRepo(),
        chip_repo=FakeChipRepo(chip_map or {}), berechtigung_repo=None,
        log_repo=FakeLogRepo(), client_factory=FakeClient,
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


def test_logs_sync_status_snapshot():
    svc = _service()
    svc.inventar_sync()
    svc.logs_sync()
    s = svc.schloss_repo.list_all()[0]
    # Jüngster lockDate (…312000) gehört zu recordType 7
    assert s.letztes_event_type == 7
    assert s.letztes_event_at is not None


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
        log_repo=FakeLogRepo(), client_factory=lambda: fake_client,
    )


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
