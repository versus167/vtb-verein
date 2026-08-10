"""
Integrationstest des Fremd-Log-Imports gegen echtes PostgreSQL.

Hier zählt die SQL-Semantik, die Fakes nicht abbilden können: der partielle
Unique-Index (Dedupe über Schloss + Zeitpunkt + Konto), die dreistufige
Konto-Auflösung in SQL und das nachträgliche Zuordnen früher importierter Zeilen.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-import -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=importtest -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/importtest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_zutritt_import_integration.py
"""
import os

import pytest

from app.models.schliessanlage import SchluesselChip, QUELLE_EXTERN
from app.services.zutritt_import_service import run_import

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

CSV = (
    "Unlock Account,Unlock Type, Lock Name,Unlock Time\n"
    "test1,Karte entsperren,Tor Einfahrt,2026-08-07 19:56:16\n"
    "test1,Karte entsperren,Tor Einfahrt,2026-08-07 19:59:00\n"
    "Chip8,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05\n"
    "Volker1,Karte entsperren,Tor Einfahrt,2026-08-10 17:53:12\n"
).encode()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-import-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM tuer_zutritt_log")
        cur.execute("DELETE FROM tuer_schloss_status_log")
        cur.execute("DELETE FROM tuer_schloss_history")
        cur.execute("DELETE FROM tuer_schloss")
        cur.execute("DELETE FROM schluessel_chip_history")
        cur.execute("DELETE FROM schluessel_chip")
    db.conn.commit()
    yield


def test_lauf_legt_externes_schloss_an_und_ist_idempotent(db):
    erster = run_import(db, CSV, commit=True, actor="tester")
    assert erster.neu == 4

    schloss = db.tuer_schloesser.find_extern_by_name("tor einfahrt")   # case-insensitiv
    assert schloss is not None
    assert schloss.quelle == QUELLE_EXTERN and schloss.ttlock_lock_id is None
    # Ortszeit → UTC (Sommerzeit: -2 h)
    assert schloss.letztes_event_at == "2026-08-10T15:53:12+00:00"
    assert schloss.letztes_event_type == 7

    zweiter = run_import(db, CSV, commit=True, actor="tester")
    assert (zweiter.neu, zweiter.doppelt) == (0, 4)
    assert len(db.tuer_zutritt_logs.list_for_schloss(schloss.id)) == 4
    # Kein zweites Schloss durch denselben Namen
    assert len([s for s in db.tuer_schloesser.list_all() if s.quelle == QUELLE_EXTERN]) == 1


def test_vorschau_schreibt_nichts(db):
    bericht = run_import(db, CSV, commit=False)
    assert bericht.neu == 4 and bericht.schloesser[0].neu_angelegt is True
    assert db.tuer_schloesser.list_all() == []


def test_konto_aufloesung_ueber_kennung_bezeichnung_kartennummer(db):
    db.schluessel_chips.create(
        SchluesselChip(kartennummer="Chip8", bezeichnung="Kartennummer-Treffer"), "test")
    db.schluessel_chips.create(
        SchluesselChip(kartennummer="222", bezeichnung="volker1"), "test")   # Groß/Klein egal
    kennung = db.schluessel_chips.create(
        SchluesselChip(kartennummer="333", bezeichnung="Test-Chip",
                       externe_kennung="test1"), "test")

    run_import(db, CSV, commit=True)
    schloss = db.tuer_schloesser.find_extern_by_name("Tor Einfahrt")
    nach_konto = {l.extern_konto: l for l in db.tuer_zutritt_logs.list_for_schloss(schloss.id)}
    assert nach_konto["test1"].chip_id == kennung.id
    assert nach_konto["Chip8"].chip_bezeichnung == "Kartennummer-Treffer"
    assert nach_konto["Volker1"].chip_id is not None


def test_gepflegte_kennung_gewinnt_gegen_bezeichnung(db):
    db.schluessel_chips.create(SchluesselChip(kartennummer="111", bezeichnung="Volker1"), "t")
    gepflegt = db.schluessel_chips.create(
        SchluesselChip(kartennummer="222", bezeichnung="Karte rot",
                       externe_kennung="Volker1"), "t")
    run_import(db, CSV, commit=True)
    schloss = db.tuer_schloesser.find_extern_by_name("Tor Einfahrt")
    treffer = next(l for l in db.tuer_zutritt_logs.list_for_schloss(schloss.id)
                   if l.extern_konto == "Volker1")
    assert treffer.chip_id == gepflegt.id


def test_spaeter_gepflegte_kennung_zieht_alte_zeilen_nach(db):
    run_import(db, CSV, commit=True)
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="999", bezeichnung="Spät", externe_kennung="test1"), "t")
    nachgezogen = db.tuer_zutritt_logs.resolve_extern_konto(
        "test1", chip_id=chip.id, mitglied_id=None)
    assert nachgezogen == 2
    assert len(db.tuer_zutritt_logs.list_for_chip(chip.id)) == 2


def test_extern_und_ttlock_liegen_im_selben_log(db):
    """Der Gesamt-Log mischt beide Herkünfte – genau dafür ist es eine Tabelle."""
    from app.models.schliessanlage import TuerZutrittLog
    schloss_id = db.tuer_schloesser.upsert_inventory(
        ttlock_lock_id=4711, name="Küche", lock_mac=None, ttlock_gateway_id=None,
        gateway_online=True, akku_prozent=90, akku_stand_at=None)
    db.tuer_zutritt_logs.insert_if_new(TuerZutrittLog(
        ttlock_record_id=1, schloss_id=schloss_id, record_type=7, methode="IC-Karte",
        erfolg=True, lock_date="2026-08-09T10:00:00+00:00", server_date=1))
    run_import(db, CSV, commit=True)

    gesamt = db.tuer_zutritt_logs.list_neueste(limit=50)
    assert len(gesamt) == 5
    assert {l.quelle for l in gesamt} == {"ttlock", "extern"}
    # Neueste zuerst, über beide Herkünfte hinweg
    assert gesamt[0].lock_date == "2026-08-10T15:53:12+00:00"
