"""Sync-Takt in der App, Schema v120 (#61) – Fresh == Migriert.

Der Takt des Hintergrund-Syncs stand in der Env und war damit nur für den änderbar,
der an die `.env` und an einen Container-Neustart kommt. Seit v120 steht er neben der
Akku-Schwelle in `schliessanlage_einstellungen`; der Sidecar fragt bei jedem Tick dort
nach. Geprüft wird beides: der Frischaufbau (VereinsDB legt v120 beim Connect an) und
der Upgrade-Pfad aus einer nachgestellten v119-Datenbank.

Zwei Fallstricke, beide lautlos:

* Eine neue Spalte an einer auditierten Tabelle braucht auch neue Audit-Funktionen –
  sonst steht der Takt in der Tabelle, aber nie in der History.
* Ein Bestand, der bisher 6 h in der Env stehen hatte, dürfte nach dem Update nicht
  plötzlich alle 4 h synchronisieren. Der Startwert kommt deshalb aus der Env.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-takt -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=takt -p 55493:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55493/takt \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_zutritt_sync_takt_migration_integration.py
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Spaltenstand vor v120 – Grundlage der zurückgedrehten Audit-Funktionen.
_V119_COLS = ("id, version, akku_ticket_bereich_id, akku_ticket_schwelle, "
              "akku_ticket_prioritaet, created_at, created_by, updated_at, updated_by")

_NEUE_SPALTEN = ("sync_intervall_stunden", "logs_intervall_minuten")


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-takt-uploads")
    yield d
    d.close()


def _spalten(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _takt_zuruecksetzen(db):
    """Auf die Werte des Frischaufbaus – die Modul-DB ist über Tests geteilt."""
    with db.cursor() as cur:
        cur.execute("UPDATE schliessanlage_einstellungen "
                    "SET sync_intervall_stunden = 4, logs_intervall_minuten = 15 "
                    "WHERE id = 1")
        cur.execute("DELETE FROM schliessanlage_einstellungen_history WHERE version > 1")


@pytest.fixture(autouse=True)
def sauber(db):
    _takt_zuruecksetzen(db)
    yield
    _takt_zuruecksetzen(db)


# --------------------------------------------------------------- Frischaufbau
def test_frischaufbau_kennt_takt_und_merker(db):
    assert _NEUE_SPALTEN[0] in _spalten(db, 'schliessanlage_einstellungen')
    assert _NEUE_SPALTEN[1] in _spalten(db, 'schliessanlage_einstellungen')
    assert set(_NEUE_SPALTEN) <= _spalten(db, 'schliessanlage_einstellungen_history')
    # Die Takt-Merker hängen am Konto, nicht an den Einstellungen: Laufzeitspur,
    # keine Konfiguration.
    assert {'letzter_voll_sync_at', 'letzter_log_sync_at'} <= _spalten(db, 'ttlock_konto')


def test_startwerte_sind_vier_stunden_und_viertelstunde(db):
    e = db.schliessanlage_einstellungen.get()
    assert (e.sync_intervall_stunden, e.logs_intervall_minuten) == (4, 15)


def test_speichern_haelt_den_takt_und_schreibt_history(db):
    e = db.schliessanlage_einstellungen.get()
    e.sync_intervall_stunden = 6
    e.logs_intervall_minuten = 30

    gespeichert = db.schliessanlage_einstellungen.update(e, 'testuser')

    assert (gespeichert.sync_intervall_stunden, gespeichert.logs_intervall_minuten) == (6, 30)
    assert db.schliessanlage_einstellungen.get().sync_intervall_stunden == 6
    with db.cursor() as cur:
        cur.execute("SELECT sync_intervall_stunden, logs_intervall_minuten "
                    "FROM schliessanlage_einstellungen_history "
                    "ORDER BY version DESC LIMIT 1")
        letzte = cur.fetchone()
    assert (letzte['sync_intervall_stunden'], letzte['logs_intervall_minuten']) == (6, 30)


def test_merker_lassen_sich_getrennt_stellen(db):
    """`letzter_sync_at` (Anzeige) und die beiden Takt-Merker dürfen auseinanderlaufen."""
    db.ttlock_konto.touch_voll_sync('2026-09-09T10:00:00+00:00')
    db.ttlock_konto.touch_log_sync('2026-09-09T11:30:00+00:00')

    konto = db.ttlock_konto.get()
    assert konto.letzter_voll_sync_at.startswith('2026-09-09T10:00')
    assert konto.letzter_log_sync_at.startswith('2026-09-09T11:30')


def test_unbekannte_merker_spalte_wird_abgelehnt(db):
    """Der Spaltenname geht ins SQL – deshalb nur die drei bekannten."""
    with pytest.raises(ValueError):
        db.ttlock_konto._touch('beliebig; DROP TABLE ttlock_konto', 'x',
                               endpoint='https://euapi.ttlock.com', by='t')


# ------------------------------------------------------------ Migration v119→v120
@pytest.fixture()
def auf_v119(db):
    """Das Schema auf den Stand vor v120 zurückdrehen."""
    vals = ", ".join("NEW." + c.strip() for c in _V119_COLS.split(","))
    with db.cursor() as cur:
        for spalte in _NEUE_SPALTEN:
            cur.execute(f"ALTER TABLE schliessanlage_einstellungen DROP COLUMN IF EXISTS {spalte}")
            cur.execute("ALTER TABLE schliessanlage_einstellungen_history "
                        f"DROP COLUMN IF EXISTS {spalte}")
        cur.execute("ALTER TABLE ttlock_konto DROP COLUMN IF EXISTS letzter_voll_sync_at")
        cur.execute("ALTER TABLE ttlock_konto DROP COLUMN IF EXISTS letzter_log_sync_at")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_schliessanlage_einstellungen_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO schliessanlage_einstellungen_history ({_V119_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests wieder anheben.
    db._database._migrate_v119_to_v120()
    _takt_zuruecksetzen(db)


def test_migration_ergaenzt_spalten_in_tabelle_history_und_konto(db, auf_v119):
    assert not set(_NEUE_SPALTEN) & _spalten(db, 'schliessanlage_einstellungen')

    db._database._migrate_v119_to_v120()

    assert set(_NEUE_SPALTEN) <= _spalten(db, 'schliessanlage_einstellungen')
    assert set(_NEUE_SPALTEN) <= _spalten(db, 'schliessanlage_einstellungen_history')
    assert {'letzter_voll_sync_at', 'letzter_log_sync_at'} <= _spalten(db, 'ttlock_konto')


def test_migration_zieht_die_audit_funktionen_nach(db, auf_v119):
    """Der Fallstrick: ALTER TABLE allein lässt eine History zurück, die den Takt
    nie sieht – ohne dass irgendetwas kracht."""
    db._database._migrate_v119_to_v120()

    e = db.schliessanlage_einstellungen.get()
    e.sync_intervall_stunden = 2
    db.schliessanlage_einstellungen.update(e, 'testuser')

    with db.cursor() as cur:
        cur.execute("SELECT sync_intervall_stunden FROM schliessanlage_einstellungen_history "
                    "ORDER BY version DESC LIMIT 1")
        assert cur.fetchone()['sync_intervall_stunden'] == 2


def test_migration_uebernimmt_den_bisherigen_env_takt(db, auf_v119, monkeypatch):
    """Wer 6 h in der .env stehen hatte, synchronisiert nach dem Update weiter alle 6 h."""
    monkeypatch.setenv("TTLOCK_SYNC_INTERVAL_HOURS", "6")
    monkeypatch.setenv("TTLOCK_LOGS_INTERVAL_MINUTES", "30")

    db._database._migrate_v119_to_v120()

    e = db.schliessanlage_einstellungen.get()
    assert (e.sync_intervall_stunden, e.logs_intervall_minuten) == (6, 30)


def test_migration_begrenzt_unsinnige_env_werte(db, auf_v119, monkeypatch):
    monkeypatch.setenv("TTLOCK_SYNC_INTERVAL_HOURS", "48")
    monkeypatch.setenv("TTLOCK_LOGS_INTERVAL_MINUTES", "nein")

    db._database._migrate_v119_to_v120()

    e = db.schliessanlage_einstellungen.get()
    assert (e.sync_intervall_stunden, e.logs_intervall_minuten) == (6, 15)


def test_migration_erzeugt_keine_history_zeile(db, auf_v119):
    """Der Startwert ist keine Änderung durch einen Menschen."""
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM schliessanlage_einstellungen_history")
        vorher = cur.fetchone()['n']

    db._database._migrate_v119_to_v120()

    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM schliessanlage_einstellungen_history")
        assert cur.fetchone()['n'] == vorher
