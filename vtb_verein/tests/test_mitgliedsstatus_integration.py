"""
Mitgliedsstatus nur noch 'aktiv'/'passiv' (#173, Schema v103) – Fresh == Migriert.

`status` beschrieb zwei Dinge auf einmal: die FORM der Mitgliedschaft und ob sie
überhaupt besteht ('ausgetreten', 'inaktiv'). Das Zweite steht schon in
eintrittsdatum/austrittsdatum. Zwei Quellen für dieselbe Aussage gehen auseinander –
genau davor schützt jetzt ein CHECK, und die Auswertungen fragen ausschließlich die
Daten.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an):
    docker run -d --name vtb-pg-v103 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=v103test -p 55442:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55442/v103test \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_mitgliedsstatus_integration.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from psycopg.errors import CheckViolation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Wurzel

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_MARKE = 'statustest'
GESTERN = (date.today() - timedelta(days=1)).isoformat()
VORJAHR = (date.today() - timedelta(days=400)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-status-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Vor UND nach dem Test aufräumen – die Wegwerf-DB teilen sich alle
    Integrationstests, und mehrere zählen Mitglieder vereinsweit."""
    def weg():
        with db.cursor() as cur:
            cur.execute("DELETE FROM mitglied_abteilung WHERE created_by = %s", (_MARKE,))
            cur.execute("DELETE FROM mitglied_history WHERE created_by = %s", (_MARKE,))
            cur.execute("DELETE FROM mitglied WHERE created_by = %s", (_MARKE,))
            cur.execute("DELETE FROM abteilung WHERE created_by = %s", (_MARKE,))
    weg()
    yield
    weg()


def _mitglied(db, nachname, *, status='aktiv', eintritt=VORJAHR, austritt=None):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied (vorname, nachname, zahlungsart, status, art, "
            "eintrittsdatum, austrittsdatum, created_by, updated_by) "
            "VALUES ('St', %s, 'ueberweisung', %s, 'mitglied', %s, %s, %s, %s) RETURNING id",
            (nachname, status, eintritt, austritt, _MARKE, _MARKE))
        return cur.fetchone()['id']


# --- Frischaufbau -----------------------------------------------------------

@pytest.mark.parametrize("wert", ['ausgetreten', 'inaktiv', 'irgendwas'])
def test_der_check_laesst_nur_aktiv_und_passiv_zu(db, wert):
    with pytest.raises(CheckViolation):
        _mitglied(db, 'Alt', status=wert)
    db.conn.rollback()


def test_aktiv_und_passiv_gehen_weiterhin(db):
    assert _mitglied(db, 'Aktiv') > 0
    assert _mitglied(db, 'Passiv', status='passiv') > 0


# --- Auswertungen: es zählt das Datum, nicht der Status ---------------------

def test_wer_ausgetreten_ist_sagt_das_austrittsdatum(db):
    """Kernaussage des Tickets: Ein abgelaufenes Austrittsdatum nimmt jemanden aus
    dem Bestand – ganz ohne Status-Pflege."""
    _mitglied(db, 'Dabei')
    _mitglied(db, 'Weg', austritt=GESTERN)
    _mitglied(db, 'PassivDabei', status='passiv')

    kpis = db.statistik.kpis()
    assert kpis['gesamt'] == 2          # der Ausgetretene fehlt, der Passive zählt mit


def test_kpis_werten_den_toten_status_nicht_mehr_aus(db):
    """Weder 'inaktiv'/'ausgetreten' (#173) noch eine Kennzahl über m.status: Der
    Vereinsstatus wird nicht mehr gepflegt, also sagt eine Zahl darüber nichts."""
    kpis = db.statistik.kpis()
    for tot in ('inaktiv', 'ausgetreten', 'aktiv', 'passiv'):
        assert tot not in kpis
    assert 'aktiv_in_abteilung' in kpis


def _mit_abteilung(db, mitglied_id, abteilung_id, *, status='aktiv', bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, status, "
                    "von, bis, created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (mitglied_id, abteilung_id, status, VORJAHR, bis, _MARKE, _MARKE))


def _abteilung(db, name='Status-Abt'):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", (name, _MARKE, _MARKE))
        return cur.fetchone()['id']


def test_davon_in_abteilungen_zaehlt_die_gepflegte_zuordnung(db):
    """Die Kennzahl hängt an mitglied_abteilung – der einzigen Stelle, die gepflegt
    wird und die von/bis samt Passiv-Status kennt."""
    aid = _abteilung(db)
    _mit_abteilung(db, _mitglied(db, 'Dabei'), aid)
    _mit_abteilung(db, _mitglied(db, 'PassivInAbt'), aid, status='passiv')
    _mit_abteilung(db, _mitglied(db, 'Ausgelaufen'), aid, bis=GESTERN)
    _mitglied(db, 'OhneAbteilung')

    kpis = db.statistik.kpis()
    assert kpis['gesamt'] == 4                  # alle vier gehören dem Verein an
    assert kpis['aktiv_in_abteilung'] == 1      # nur die laufende, aktive Zuordnung


def test_in_der_abteilungssicht_deckt_sich_die_zahl_mit_gesamt(db):
    """Dort filtert schon der Scope-JOIN auf aktive Zuordnungen – die Oberfläche
    blendet die Kachel deshalb aus."""
    aid = _abteilung(db)
    _mit_abteilung(db, _mitglied(db, 'Dabei'), aid)
    _mit_abteilung(db, _mitglied(db, 'PassivInAbt'), aid, status='passiv')

    kpis = db.statistik.kpis(abteilung_id=aid)
    assert kpis['gesamt'] == kpis['aktiv_in_abteilung'] == 1


def test_abteilungsuebersicht_zaehlt_ausgetretene_nicht_mit(db):
    """Vorher hing das am Status; wessen Status nie nachgepflegt wurde, lief mit."""
    aid = _abteilung(db)
    for name, austritt in (('Dabei', None), ('Weg', GESTERN)):
        _mit_abteilung(db, _mitglied(db, name, austritt=austritt), aid)

    zeile = next(z for z in db.statistik.abteilungsuebersicht() if z['name'] == 'Status-Abt')
    assert zeile['anzahl'] == 1


# --- Import: das Austrittsdatum wandert nicht mehr in den Status -------------

_KOPF = ('"MITGLNR";"Anrede";"Nachname";"Vorname";"Geburtsdatum";"Strasse";"PLZ";'
         '"Ort";"IBAN1";"BIC1";"Status";"Eintritt";"Austritt";"Telefon";'
         '"Geschlecht";"Staatsangehörigkeit";"Mobiltelefon"')
_LEER = ';;;;;;;;;;;;;;;;'


def _linear_csv(nachname, status_text, austritt):
    zeile = (f'"4711";"Herr";"{nachname}";"Max";01.01.2000 00:00;"Weg 1";"09111";'
             f'"Musterstadt";"";"";"{status_text}";01.01.2020 00:00;{austritt};"";'
             f'"MÄNNLICH";"DE";""')
    return '\n'.join([_KOPF, _LEER, _LEER, zeile]).encode('utf-8')


@pytest.mark.parametrize("status_text,erwartet", [('Aktiv', 'aktiv'), ('Passiv', 'passiv')])
def test_import_spiegelt_den_austritt_nicht_in_den_status(db, status_text, erwartet):
    """Vorher setzte ein gefülltes Austrittsdatum den Status auf 'ausgetreten' und
    überschrieb damit die Angabe aus der Quelle – seit v103 verböte das der CHECK."""
    from app.services import linear_import_service as linear
    name = f'Import{erwartet.capitalize()}'
    linear.run_import(db.conn, _linear_csv(name, status_text, '30.06.2026 00:00'),
                      commit=True, allow_unmatched=True)
    with db.cursor() as cur:
        cur.execute("SELECT status, austrittsdatum, id FROM mitglied WHERE nachname = %s",
                    (name,))
        row = cur.fetchone()
        cur.execute("DELETE FROM mitglied_kontakt WHERE mitglied_id = %s", (row['id'],))
        cur.execute("DELETE FROM mitglied_history WHERE id = %s", (row['id'],))
        cur.execute("DELETE FROM mitglied WHERE id = %s", (row['id'],))
    assert row['status'] == erwartet
    assert row['austrittsdatum'] == '2026-06-30'


# --- Migration --------------------------------------------------------------

def test_migration_v102_v103(db):
    """v102-Stand nachbauen (CHECK weg, alte Werte drin) und migrieren."""
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied DROP CONSTRAINT IF EXISTS mitglied_status_check")
    mit_datum = _mitglied(db, 'MitDatum', status='ausgetreten', austritt=GESTERN)
    ohne_datum = _mitglied(db, 'OhneDatum', status='ausgetreten')
    war_inaktiv = _mitglied(db, 'Inaktiv', status='inaktiv')
    passiv = _mitglied(db, 'Passiv', status='passiv')
    with db.cursor() as cur:
        cur.execute("SELECT version FROM mitglied WHERE id = %s", (mit_datum,))
        version_vorher = cur.fetchone()['version']
        cur.execute("UPDATE schema_version SET version = 102 WHERE id = 1")

    db._database._migrate_v102_to_v103()

    with db.cursor() as cur:
        cur.execute("SELECT id, status, version, austrittsdatum FROM mitglied "
                    "WHERE id = ANY(%s)", ([mit_datum, ohne_datum, war_inaktiv, passiv],))
        zeilen = {r['id']: r for r in cur.fetchall()}
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 103

    assert zeilen[mit_datum]['status'] == 'aktiv'
    assert zeilen[ohne_datum]['status'] == 'aktiv'
    assert zeilen[war_inaktiv]['status'] == 'aktiv'
    assert zeilen[passiv]['status'] == 'passiv'          # unangetastet
    # Das Austrittsdatum bleibt die Wahrheit – es wird weder gesetzt noch gelöscht.
    assert zeilen[mit_datum]['austrittsdatum'] == GESTERN
    assert zeilen[ohne_datum]['austrittsdatum'] is None
    # Fachliche Änderung → version-Bump, damit der Audit-Trigger sie festhält.
    assert zeilen[mit_datum]['version'] == version_vorher + 1

    # Und der CHECK steht danach wie im Frischaufbau.
    with pytest.raises(CheckViolation):
        _mitglied(db, 'Neu', status='ausgetreten')
    db.conn.rollback()
