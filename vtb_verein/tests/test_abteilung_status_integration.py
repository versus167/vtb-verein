"""Abteilungs-Status nur noch 'aktiv'/'passiv' (Schema v104) – Fresh == Migriert.

`mitglied_abteilung.status` trug zwei Dinge in einem Feld: Beitragsrelevanz
(aktiv/passiv) und Rolle (trainer/vorstand/ehrenmitglied). Weil beides dieselbe
Spalte belegte, konnte ein „trainer" nicht passiv sein. Rollen gehören zu den
Funktionen – mit Zeitraum, Abteilung und Rechten.

Der heikle Teil ist der Bestand, und darum geht es hier: Die alten Werte waren
allesamt **beitragspflichtig** (beitragsfrei war nur 'passiv'). Sie werden deshalb
zu 'aktiv' – nicht zu 'passiv', denn das erließe jemandem stillschweigend den
Beitrag. Und eine Beitragsregel, die einen wegfallenden Wert nennt, wird
mitgezogen: Sonst passt ihre Bedingung auf niemanden mehr, ohne dass ein Fehler
erscheint – auffallen würde das erst, wenn die Beiträge eines Quartals fehlen.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "abtstatustest"
WEG = ('trainer', 'vorstand', 'ehrenmitglied')


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-abtstatus-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    with db.cursor() as cur:
        for tabelle in ('beitragsregel_history', 'beitragsregel',
                        'mitglied_abteilung_history', 'mitglied_abteilung',
                        'mitglied_history', 'mitglied',
                        'abteilung_history', 'abteilung'):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture
def abteilung(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", ("AS-Sparte", MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname="Status"):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="As", nachname=nachname, eintrittsdatum="2020-01-01",
                 zahlungsart="lastschrift"), created_by=MARKE).id


def _zuordnen(db, mitglied_id, abteilung_id, status):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, status, von, "
            "created_by, updated_by) VALUES (%s, %s, %s, '2020-01-01', %s, %s) RETURNING id",
            (mitglied_id, abteilung_id, status, MARKE, MARKE))
        return cur.fetchone()["id"]


def _regel(db, bedingung):
    from app.models.beitrag import Beitragsregel
    return db.beitragsregeln.create(
        Beitragsregel(name="AS-Regel", betrag_pro_monat=5.0, gueltig_ab="2020-01-01",
                      bedingung_abteilung_status=bedingung),
        created_by=MARKE).id


# --- Frischaufbau -----------------------------------------------------------

@pytest.mark.parametrize("wert", [*WEG, 'irgendwas'])
def test_der_check_laesst_nur_aktiv_und_passiv_zu(db, abteilung, wert):
    mid = _mitglied(db)
    with pytest.raises(CheckViolation):
        _zuordnen(db, mid, abteilung, wert)
    db.conn.rollback()


def test_aktiv_und_passiv_gehen_weiterhin(db, abteilung):
    assert _zuordnen(db, _mitglied(db, "A"), abteilung, 'aktiv') > 0
    assert _zuordnen(db, _mitglied(db, "P"), abteilung, 'passiv') > 0


def test_die_api_nimmt_die_alten_werte_nicht_mehr_an():
    """Auch der Endpunkt weist sie ab, nicht erst die Datenbank."""
    from app.db.mitglied_abteilung_repository import VALID_STATUS
    assert VALID_STATUS == ('aktiv', 'passiv')


# --- Migration --------------------------------------------------------------

def _v103_stand(db):
    """CHECK entfernen und Version zurückdrehen – so sah v103 aus."""
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied_abteilung "
                    "DROP CONSTRAINT IF EXISTS mitglied_abteilung_status_check")
        cur.execute("UPDATE schema_version SET version = 103 WHERE id = 1")


def test_migration_v103_v104_bildet_rollen_auf_aktiv_ab(db, abteilung):
    """Nicht auf 'passiv': Die alten Werte waren beitragspflichtig, und das
    bleiben sie. Alles andere wäre ein stiller Beitragserlass."""
    _v103_stand(db)
    zeilen = {wert: _zuordnen(db, _mitglied(db, wert), abteilung, wert) for wert in WEG}
    zeilen['passiv'] = _zuordnen(db, _mitglied(db, 'P'), abteilung, 'passiv')
    zeilen['aktiv'] = _zuordnen(db, _mitglied(db, 'A'), abteilung, 'aktiv')
    with db.cursor() as cur:
        cur.execute("SELECT version FROM mitglied_abteilung WHERE id = %s", (zeilen['trainer'],))
        version_vorher = cur.fetchone()["version"]

    db._database._migrate_v103_to_v104()

    with db.cursor() as cur:
        cur.execute("SELECT id, status, version FROM mitglied_abteilung WHERE id = ANY(%s)",
                    (list(zeilen.values()),))
        stand = {r["id"]: r for r in cur.fetchall()}
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()["version"] == 104

    for wert in WEG:
        assert stand[zeilen[wert]]["status"] == 'aktiv'
    assert stand[zeilen['passiv']]["status"] == 'passiv'    # unangetastet
    assert stand[zeilen['aktiv']]["status"] == 'aktiv'
    # Fachliche Änderung → version-Bump, damit der Audit-Trigger sie festhält.
    assert stand[zeilen['trainer']]["version"] == version_vorher + 1


def test_migration_zieht_die_beitragsregeln_mit(db, abteilung):
    """Die eigentliche Falle: Eine Regel, die 'trainer' nennt, würde nach dem
    Wegfall auf niemanden mehr passen – ohne Fehlermeldung."""
    _v103_stand(db)
    betroffen = _regel(db, "aktiv,trainer")
    doppelt = _regel(db, "trainer,vorstand")      # beide werden 'aktiv' → entdoppeln
    unberuehrt = _regel(db, "passiv")

    db._database._migrate_v103_to_v104()

    with db.cursor() as cur:
        cur.execute("SELECT id, bedingung_abteilung_status AS b, version FROM beitragsregel "
                    "WHERE id = ANY(%s)", ([betroffen, doppelt, unberuehrt],))
        stand = {r["id"]: r for r in cur.fetchall()}

    assert stand[betroffen]["b"] == "aktiv"
    assert stand[doppelt]["b"] == "aktiv"
    assert stand[unberuehrt]["b"] == "passiv"
    assert stand[unberuehrt]["version"] == 1      # nichts zu tun, kein Bump


def test_migration_laeuft_auch_ohne_altlasten(db, abteilung):
    """Der Normalfall (nichts umzustellen) darf nicht stolpern."""
    _v103_stand(db)
    _zuordnen(db, _mitglied(db), abteilung, 'aktiv')

    db._database._migrate_v103_to_v104()

    with db.cursor() as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()["version"] == 104
    # Und der CHECK steht danach wie im Frischaufbau.
    with pytest.raises(CheckViolation):
        _zuordnen(db, _mitglied(db, "Neu"), abteilung, 'trainer')
    db.conn.rollback()
