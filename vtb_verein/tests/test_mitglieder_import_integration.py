"""Mitglieder-Import (SPG und LINEAR) mit ``commit=True`` gegen echtes PostgreSQL.

Der Probelauf endet vor dem Schreiben – ein Signaturfehler im Schreibpfad fällt
dort nicht auf. Genau das ist mit v104/v105 passiert: ``mitglied_abteilung``
verlor den Status, die Importe riefen ``create()`` weiter mit ihm auf und brachen
beim ersten Mitglied mit Abteilung ab (#66). Diese Tests gehen den Schreibpfad
deshalb bis zum Ende durch.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-import -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=importtest -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/importtest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_mitglieder_import_integration.py
"""
import os

import pytest

from app.db.mitglied_abteilung_repository import MitgliedAbteilungRepository
from app.db.mitglied_funktion_repository import MitgliedFunktionRepository
from app.db.mitglied_kontakt_repository import MitgliedKontaktRepository
from app.db.mitglied_mannschaft_repository import MitgliedMannschaftRepository
from app.services import linear_import_service as linear
from app.services import spg_import_service as spg

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "importtest"
ABT_A, ABT_B = "IT-Turnen", "IT-Kegeln"
TEAM = "IT-Riege 1"
FUNKTION = "IT-Kampfgericht"           # → Schlüssel it_kampfgericht, neu im Katalog
FUNKTION_KEY = "it_kampfgericht"


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-mitglieder-import-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Eigene Zeilen entfernen, Blatt vor Wurzel. Kein TRUNCATE: der Wegwerf-
    Postgres ist geteilt. Die History trägt das created_by der Zeile mit."""
    akteure = [spg.ACTOR, linear.ACTOR, MARKE]
    with db.cursor() as cur:
        for tabelle in ('mitglied_mannschaft_history', 'mitglied_mannschaft',
                        'mannschaft_history', 'mannschaft',
                        'mitglied_kontakt_history', 'mitglied_kontakt',
                        'mitglied_funktion_history', 'mitglied_funktion',
                        'mitglied_abteilung_history', 'mitglied_abteilung',
                        'mitglied_history', 'mitglied',
                        'funktion_history', 'funktion',
                        'abteilung_history', 'abteilung'):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = ANY(%s)", (akteure,))


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture
def abteilungen(db):
    ids = {}
    with db.cursor() as cur:
        for name in (ABT_A, ABT_B):
            cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                        "VALUES (%s, %s, %s) RETURNING id", (name, MARKE, MARKE))
            ids[name] = cur.fetchone()["id"]
    return ids


def _mitglied_id(db, vermerk):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM mitglied WHERE bemerkungen LIKE %s AND deleted_at IS NULL",
                    (f"%{vermerk}%",))
        zeilen = cur.fetchall()
    assert len(zeilen) == 1, f"genau ein Mitglied mit {vermerk} erwartet, {len(zeilen)} gefunden"
    return zeilen[0]["id"]


def _zuordnungen(db, mid):
    return {(z.abteilung_name, z.von, z.bis) for z in MitgliedAbteilungRepository(db.conn).list_for_mitglied(mid)}


def _funktionen(db, mid):
    return {(f.funktion, f.abteilung_id, f.von, f.bis)
            for f in MitgliedFunktionRepository(db.conn).list_for_mitglied(mid)}


# --- SPG ---------------------------------------------------------------------

SPG_KOPF = ("Mitglieds_Nr;Nachname;Vorname;Geburtsdatum;Eintritt_Datum;Austritt_Datum;Email;"
            "Abteilung_1;Abt_Status_1;Abteilung_Datum_1;"
            "Abteilung_2;Abt_Status_2;Abteilung_Datum_2;"
            "Funktion_1;Funkt_von_Datum_1;Funkt_Bis_Datum_1;Sonstiges_1;Zahlart;Bemerkungen")


def spg_zeile(nr='101', nachname='Importmann', vorname='Ida', email='ida@example.org',
              abt1=ABT_A, status1='a', datum1='01.03.2020',
              abt2=ABT_B, status2='a', datum2='01.04.2021',
              funktion=FUNKTION, f_von='01.01.2022', f_bis='', team=TEAM):
    return (f"{nr};{nachname};{vorname};01.02.1990;01.01.2020;;{email};"
            f"{abt1};{status1};{datum1};{abt2};{status2};{datum2};"
            f"{funktion};{f_von};{f_bis};{team};s;")


def spg_csv(*zeilen):
    return "\n".join([SPG_KOPF, *zeilen]).encode("cp1252")


def test_spg_commit_schreibt_mitglied_mit_allen_zuordnungen(db, abteilungen):
    res = spg.run_import(db.conn, spg_csv(spg_zeile()), commit=True)

    assert not res.aborted, res.abort_reason
    assert (res.neu, res.abteilungen, res.funktionen, res.kontakte, res.kader) == (1, 2, 1, 1, 1)
    assert res.neue_funktionen == [FUNKTION_KEY]
    assert res.neue_mannschaften == [TEAM]

    mid = _mitglied_id(db, "[SPG:101]")
    assert _zuordnungen(db, mid) == {(ABT_A, "2020-03-01", None), (ABT_B, "2021-04-01", None)}
    assert _funktionen(db, mid) == {(FUNKTION_KEY, None, "2022-01-01", None)}
    assert [(k.typ, k.wert) for k in MitgliedKontaktRepository(db.conn).list_for_mitglied(mid)] == \
        [("email", "ida@example.org")]
    assert len(MitgliedMannschaftRepository(db.conn).list_for_mitglied(mid)) == 1


def test_spg_zweiter_lauf_ueberspringt_und_update_ersetzt(db, abteilungen):
    spg.run_import(db.conn, spg_csv(spg_zeile()), commit=True)

    zweiter = spg.run_import(db.conn, spg_csv(spg_zeile()), commit=True)
    assert (zweiter.neu, zweiter.skip_exist) == (0, 1)

    # Update: nur noch eine Abteilung, andere Mail – die alten Kinder sind weich
    # gelöscht, nicht doppelt.
    neu = spg_zeile(email='ida.neu@example.org', abt2='', status2='', datum2='')
    upd = spg.run_import(db.conn, spg_csv(neu), commit=True, update=True)
    assert upd.aktualisiert == 1

    mid = _mitglied_id(db, "[SPG:101]")
    assert _zuordnungen(db, mid) == {(ABT_A, "2020-03-01", None)}
    assert [k.wert for k in MitgliedKontaktRepository(db.conn).list_for_mitglied(mid)] == ["ida.neu@example.org"]
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM mitglied_abteilung "
                    "WHERE mitglied_id = %s AND deleted_at IS NOT NULL", (mid,))
        assert cur.fetchone()["n"] == 2


# --- LINEAR ------------------------------------------------------------------

LINEAR_KOPF = ('"MITGLNR";"Anrede";"Nachname";"Vorname";"Geburtsdatum";"Strasse";"PLZ";'
               '"Ort";"IBAN1";"BIC1";"Status";"Eintritt";"Austritt";"Telefon";'
               '"Geschlecht";"Staatsangehörigkeit";"Mobiltelefon";'
               f'"{ABT_A}";"{ABT_B}"')
LINEAR_LEER = ';' * 18


def linear_zeile(nr='0201', nachname='Linearmann', status='Aktiv',
                 eintritt='01.05.2019 00:00', abt_a='X', abt_b=''):
    return (f'"{nr}";"Herr";"{nachname}";"Lars";01.01.1985 00:00;"Weg 1";"09111";'
            f'"Musterstadt , Sachs";"";"";"{status}";{eintritt};;"0371 123";'
            f'"MÄNNLICH";"DE";"";"{abt_a}";"{abt_b}"')


def linear_csv(*zeilen):
    return "\n".join([LINEAR_KOPF, LINEAR_LEER, *zeilen]).encode("utf-8")


def test_linear_commit_schreibt_mitglied_mit_abteilungen(db, abteilungen):
    res = linear.run_import(db.conn, linear_csv(linear_zeile(abt_b='X')), commit=True)

    assert not res.aborted, res.abort_reason
    assert (res.neu, res.abteilungen, res.kontakte) == (1, 2, 1)

    mid = _mitglied_id(db, "[LINEAR:0201]")
    # Von-Datum = Eintritt (Entscheidung im LINEAR-Plan).
    assert _zuordnungen(db, mid) == {(ABT_A, "2019-05-01", None), (ABT_B, "2019-05-01", None)}


def test_linear_update_ersetzt_zuordnungen(db, abteilungen):
    linear.run_import(db.conn, linear_csv(linear_zeile(abt_b='X')), commit=True)
    upd = linear.run_import(db.conn, linear_csv(linear_zeile(abt_a='', abt_b='X')),
                            commit=True, update=True)
    assert upd.aktualisiert == 1
    mid = _mitglied_id(db, "[LINEAR:0201]")
    assert _zuordnungen(db, mid) == {(ABT_B, "2019-05-01", None)}


# --- Passiv: seit v105 eine Funktion, kein Abteilungs-Status ------------------

def test_spg_passiv_wird_funktion_mit_abteilungsbezug(db, abteilungen):
    """Abt_Status 'p' ging beim Umbau ersatzlos verloren – passiv in Turnen heißt
    jetzt: Funktion `passiv` für Turnen ab dem Abteilungsdatum."""
    zeile = spg_zeile(status1='p', funktion='', f_von='', team='')
    res = spg.run_import(db.conn, spg_csv(zeile), commit=True)

    assert (res.passiv, res.funktionen) == (1, 1)
    assert 'passiv' not in res.neue_funktionen          # kommt mit dem Schema
    mid = _mitglied_id(db, "[SPG:101]")
    assert _funktionen(db, mid) == {("passiv", abteilungen[ABT_A], "2020-03-01", None)}
    # Die Zuordnung selbst bleibt – passiv ist man IN der Abteilung.
    assert _zuordnungen(db, mid) == {(ABT_A, "2020-03-01", None), (ABT_B, "2021-04-01", None)}


def test_spg_probelauf_zaehlt_passiv_ohne_zu_schreiben(db, abteilungen):
    res = spg.run_import(db.conn, spg_csv(spg_zeile(status1='p', status2='p')))
    assert (res.neu, res.passiv) == (1, 2)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM mitglied_funktion WHERE created_by = %s",
                    (spg.ACTOR,))
        assert cur.fetchone()["n"] == 0


@pytest.mark.parametrize("abt_a,abt_b,bezug", [
    ('X', '', ABT_A),     # genau eine Abteilung → deren Bezug
    ('X', 'X', None),     # mehrere → vereinsweit, statt eine zu raten
    ('', '', None),       # keine → vereinsweit
])
def test_linear_passiv_wird_funktion(db, abteilungen, abt_a, abt_b, bezug):
    res = linear.run_import(
        db.conn, linear_csv(linear_zeile(status='Passiv', abt_a=abt_a, abt_b=abt_b)),
        commit=True)

    assert res.passiv == 1
    mid = _mitglied_id(db, "[LINEAR:0201]")
    erwartet_aid = abteilungen[bezug] if bezug else None
    assert _funktionen(db, mid) == {("passiv", erwartet_aid, "2019-05-01", None)}
    with db.cursor() as cur:
        cur.execute("SELECT status FROM mitglied WHERE id = %s", (mid,))
        assert cur.fetchone()["status"] == "passiv"


def test_linear_aktiv_legt_keine_passiv_funktion_an(db, abteilungen):
    res = linear.run_import(db.conn, linear_csv(linear_zeile()), commit=True)
    assert res.passiv == 0
    assert _funktionen(db, _mitglied_id(db, "[LINEAR:0201]")) == set()


def test_linear_update_ersetzt_nur_die_eigene_passiv_zeile(db, abteilungen):
    """Wird aus Passiv wieder Aktiv, fällt die Import-Zeile weg; eine von Hand
    gepflegte Funktion bleibt – die Datei kennt keine Funktionen."""
    linear.run_import(db.conn, linear_csv(linear_zeile(status='Passiv')), commit=True)
    mid = _mitglied_id(db, "[LINEAR:0201]")
    MitgliedFunktionRepository(db.conn).create(mid, None, 'vorstand', '2024-01-01', None, MARKE)

    linear.run_import(db.conn, linear_csv(linear_zeile()), commit=True, update=True)

    assert _funktionen(db, mid) == {("vorstand", None, "2024-01-01", None)}


def test_linear_legt_fehlenden_passiv_schluessel_an(db, abteilungen):
    from app.db.funktion_repository import FunktionRepository
    f_repo = FunktionRepository(db.conn)
    seed = f_repo.get_by_key('passiv')
    f_repo.mark_deleted(seed.id, MARKE)
    try:
        res = linear.run_import(db.conn, linear_csv(linear_zeile(status='Passiv')), commit=True)
        assert res.neue_funktionen == ['passiv']
        assert f_repo.get_by_key('passiv') is not None
    finally:
        # Seed-Zeile zurückholen, damit andere Module ihn weiter finden.
        with db.cursor() as cur:
            cur.execute("DELETE FROM funktion_history WHERE created_by = %s", (linear.ACTOR,))
            cur.execute("DELETE FROM funktion WHERE created_by = %s", (linear.ACTOR,))
            cur.execute("UPDATE funktion SET deleted_at = NULL, deleted_by = NULL, "
                        "version = version + 1 WHERE id = %s", (seed.id,))
