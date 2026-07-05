"""
Integrationstests des Konnektivitäts-Logs je Schloss (#82) gegen echtes PostgreSQL.

Die Transition-Erkennung sitzt im TuerSchlossRepository.upsert_inventory und lässt sich nur
gegen das reale Schema (tri-state BOOLEAN, append-only tuer_schloss_status_log, abgeleitete
gateway_online_seit-Subquery) sinnvoll prüfen – nicht mit den Service-Fakes.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt (ephemerer
Postgres-Container). VereinsDB legt das Schema beim Connect an. Beispiel:
    docker run -d --name vtb-pg-statustest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=statustest -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55432/statustest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_schloss_status_log_integration.py
"""
import os

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-status-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute("TRUNCATE tuer_schloss, tuer_schloss_status_log RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE tuer_schloss_history RESTART IDENTITY")
    yield


def _sync(db, online, *, akku=90, mac="AA", gw=77):
    """Ein Inventar-Upsert des Test-Schlosses (ttlock_lock_id=999)."""
    return db.tuer_schloesser.upsert_inventory(
        ttlock_lock_id=999, name="Test", lock_mac=mac, ttlock_gateway_id=gw,
        gateway_online=online, akku_prozent=akku, akku_stand_at="2026-07-05T10:00:00",
    )


def _states(db, sid):
    return [e.online for e in db.tuer_schloss_status_logs.list_for_schloss(sid)]


def test_insert_schreibt_baseline(db):
    sid = _sync(db, True)
    assert _states(db, sid) == [True]


def test_noop_und_reine_akku_aenderung_ohne_neuen_eintrag(db):
    sid = _sync(db, True, akku=90)
    _sync(db, True, akku=90)          # identisch → No-Op
    _sync(db, True, akku=80)          # nur Akku ändert sich → kein Status-Wechsel
    assert _states(db, sid) == [True]


def test_wechsel_haengt_je_einen_eintrag_an(db):
    sid = _sync(db, True)             # Baseline True
    _sync(db, None)                   # True → unbekannt
    _sync(db, False)                  # unbekannt → offline
    _sync(db, True)                   # offline → online
    # list_for_schloss ist absteigend (jüngster zuerst)
    assert _states(db, sid) == [True, False, None, True]


def test_gateway_online_seit_folgt_aktuellem_status(db):
    sid = _sync(db, True)
    _sync(db, False)                  # jetzt offline
    s = db.tuer_schloesser.get(sid)
    juengster = db.tuer_schloss_status_logs.list_for_schloss(sid)[0]
    assert s.gateway_online is False
    assert juengster.online is False
    # abgeleitete „seit" == Zeitstempel des jüngsten Übergangs (Start des aktuellen Status)
    assert str(s.gateway_online_seit) == str(juengster.geaendert_am)
