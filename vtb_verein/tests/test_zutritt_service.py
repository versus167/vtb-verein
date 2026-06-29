"""
Tests für ZutrittService – Orchestrierung ohne Netz/DB (Fakes für Client + Repos).

Geprüft:
- inventar_sync spiegelt Schlösser inkl. Online-Status (aus gateway/list) und Akku.
- logs_sync ist idempotent (Dedupe über recordId) und schreibt den Cursor fort.
- Kartennummer → Chip → Mitglied wird nur für IC-Karten-Records aufgelöst.
- Status-Snapshot (letztes Event) entspricht dem jüngsten Log.
"""
from app.services.zutritt_service import ZutrittService


# --- Fakes ------------------------------------------------------------------
class FakeClient:
    def __init__(self):
        self.unlocked = []
        self.locked = []

    def unlock(self, lock_id):
        self.unlocked.append(lock_id); return {"errcode": 0}

    def remote_lock(self, lock_id):
        self.locked.append(lock_id); return {"errcode": 0}

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
    def __init__(self, id, mitglied_id):
        self.id, self.mitglied_id = id, mitglied_id


class FakeChipRepo:
    def __init__(self, mapping):
        self._m = mapping

    def find_active_by_kartennummer(self, kn):
        return self._m.get(kn)


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
    import pytest
    with pytest.raises(ValueError):
        svc.oeffnen(999)
