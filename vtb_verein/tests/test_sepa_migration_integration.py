"""
Integrationstest des SEPA-Schemas (v79) gegen echtes PostgreSQL – Ticket #114.

Prüft am realen Schema, was Stub-Tests nicht können: dass Frischaufbau und Migration
dieselben Tabellen/Trigger/Indexe liefern, dass der Audit-Trigger die History schreibt
und dass der partielle Unique-Index einen zweiten Einzug desselben Postens verhindert.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(z.B. ein ephemerer Postgres-Container). VereinsDB legt das Schema beim Connect an.
Beispiel:
    docker run -d --name vtb-pg-sepatest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=sepatest -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55433/sepatest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_sepa_migration_integration.py
"""
import os

import psycopg
import pytest

from app.models.sepa import SepaLauf, SepaPosition

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_SEPA_TABELLEN = ('sepa_lauf', 'sepa_lauf_history',
                  'sepa_lauf_position', 'sepa_lauf_position_history')
_SEPA_EINSTELLUNGEN = ('sepa_glaeubiger_id', 'sepa_glaeubiger_name', 'sepa_iban',
                       'sepa_bic', 'sepa_vorlauftage')

# created_by-Stempel aller hier angelegten Zeilen – daran erkennt die clean-Fixture,
# was ihr gehört (die Wegwerf-DB teilen sich alle Integrationstests).
_MARKE = 'sepatest'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-sepa-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Nur die eigenen Zeilen wegräumen – Muster der übrigen Integrationstests.

    Ein pauschales ``DELETE FROM mitglied`` scheitert, sobald ein anderes Testmodul in
    derselben Wegwerf-DB Zeilen hinterlassen hat, die auf Mitglieder zeigen (z. B. ein
    ``schluessel_chip``), und würde umgekehrt deren Fixtures zerstören. Die sepa_*-
    Tabellen benutzt nur dieses Modul, die dürfen komplett geleert werden.
    """
    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM sepa_lauf_position_history")
        cur.execute("DELETE FROM sepa_lauf_position")
        cur.execute("DELETE FROM sepa_lauf_history")
        cur.execute("DELETE FROM sepa_lauf")
        for tabelle in ('beitrag_sollstellung', 'beitragsregel', 'mitglied'):
            cur.execute(f"DELETE FROM {tabelle}_history WHERE created_by = %s", (_MARKE,))
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (_MARKE,))
    db.conn.commit()


@pytest.fixture(autouse=True)
def clean(db):
    # Vor UND nach dem Test aufräumen: Nur davor zu putzen lässt die Zeilen des
    # letzten Tests im geteilten Wegwerf-Postgres stehen. Vereinsweite Auswertungen
    # anderer Module zählen sie dann mit (die Statistik-KPIs in
    # test_gastspieler_integration fielen genau darüber, sobald die Suite ein
    # zweites Mal gegen dieselbe DB lief).
    _aufraeumen(db)
    yield
    _aufraeumen(db)


def _spalten(db, tabelle) -> set:
    with db.conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s", (tabelle,))
        return {r['column_name'] for r in cur.fetchall()}


def _mitglied(db, nummer=1001) -> int:
    with db.conn.cursor() as cur:
        # zahlungsart ist NOT NULL ohne Default – ohne Wert scheitert schon das INSERT.
        cur.execute("INSERT INTO mitglied (mitgliedsnummer, vorname, nachname, "
                    "zahlungsart, created_by) "
                    "VALUES (%s, 'Jürgen', 'Müller', '', %s) RETURNING id", (nummer, _MARKE))
        return cur.fetchone()['id']


def _lauf(**kw) -> SepaLauf:
    basis = dict(dateiname='sepa_2026-08-03.xml', message_id='VTB-20260730-120000',
                 ausfuehrungsdatum='2026-08-03', sequenztyp='RCUR',
                 glaeubiger_id='DE98ZZZ09999999999', glaeubiger_name='VTB Chemnitz e. V.',
                 glaeubiger_iban='DE02100500000054540402', glaeubiger_bic='BELADEBE')
    basis.update(kw)
    return SepaLauf(**basis)


def _position(mitglied_id, quelle_id=7, **kw) -> SepaPosition:
    basis = dict(quelle_typ='beitrag', quelle_id=quelle_id, mitglied_id=mitglied_id,
                 betrag_cent=4250, end_to_end_id=f'B{quelle_id}', mandatsref='1001',
                 mandatsdatum='2019-04-01', iban='DE02120300000000202051',
                 bic='BYLADEM1001', kontoinhaber='Jürgen Müller',
                 verwendungszweck='Beitrag 2026-Q3')
    basis.update(kw)
    return SepaPosition(**basis)


# --- Schema -----------------------------------------------------------------

@pytest.mark.parametrize("tabelle", _SEPA_TABELLEN)
def test_tabellen_existieren(db, tabelle):
    assert _spalten(db, tabelle)


@pytest.mark.parametrize("tabelle", ('fibu_einstellungen', 'fibu_einstellungen_history'))
def test_einstellungen_haben_sepa_spalten_in_tabelle_und_history(db, tabelle):
    assert set(_SEPA_EINSTELLUNGEN) <= _spalten(db, tabelle)


def test_history_spiegelt_die_spalten_der_basistabelle(db):
    """History = Basis minus SERIAL-Eigenheiten; fehlt eine Spalte, bricht der Trigger."""
    for basis, history in (('sepa_lauf', 'sepa_lauf_history'),
                           ('sepa_lauf_position', 'sepa_lauf_position_history')):
        assert _spalten(db, basis) <= _spalten(db, history)


def test_audit_trigger_und_unique_index_vorhanden(db):
    with db.conn.cursor() as cur:
        cur.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        trigger = {r['tgname'] for r in cur.fetchall()}
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        indexe = {r['indexname'] for r in cur.fetchall()}
    assert {'trig_sepa_lauf_audit_insert', 'trig_sepa_lauf_audit_update',
            'trig_sepa_lauf_position_audit_insert',
            'trig_sepa_lauf_position_audit_update'} <= trigger
    assert 'uix_sepa_lauf_position_quelle_aktiv' in indexe


def test_zeitstempel_sind_timestamptz(db):
    with db.conn.cursor() as cur:
        cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = ANY(%s) AND column_name IN "
                    "('created_at','updated_at','deleted_at')", (list(_SEPA_TABELLEN),))
        typen = {(r['table_name'], r['column_name']): r['data_type'] for r in cur.fetchall()}
    assert typen and all(t == 'timestamp with time zone' for t in typen.values()), typen


# --- Verhalten --------------------------------------------------------------

def test_lauf_anlegen_schreibt_header_positionen_und_history(db):
    mid = _mitglied(db)
    lauf = db.sepa.create_lauf(_lauf(), [_position(mid), _position(mid, quelle_id=8)],
                               erstellt_von='kasse')
    assert lauf.id is not None
    assert (lauf.anzahl_positionen, lauf.summe_cent) == (2, 8500)
    assert len(lauf.positionen) == 2
    with db.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM sepa_lauf_history WHERE id = %s", (lauf.id,))
        assert cur.fetchone()['n'] == 1
        cur.execute("SELECT COUNT(*) AS n FROM sepa_lauf_position_history")
        assert cur.fetchone()['n'] == 2


def test_lauf_zaehlt_lastschriften_ueber_die_end_to_end_ids(db):
    """Zwei Posten eines Mandats = zwei Positionen, aber nur EINE Lastschrift."""
    mid = _mitglied(db)
    lauf = db.sepa.create_lauf(
        _lauf(),
        [_position(mid, end_to_end_id='1001-20260803'),
         _position(mid, quelle_id=8, end_to_end_id='1001-20260803')],
        erstellt_von='kasse')
    assert (lauf.anzahl_positionen, lauf.anzahl_lastschriften) == (2, 1)
    assert db.sepa.list_laeufe()[0].anzahl_lastschriften == 1


def test_derselbe_posten_kann_nicht_zweimal_eingezogen_werden(db):
    mid = _mitglied(db)
    db.sepa.create_lauf(_lauf(), [_position(mid)], erstellt_von='kasse')
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.sepa.create_lauf(_lauf(message_id='VTB-20260730-130000'),
                            [_position(mid)], erstellt_von='kasse')


def test_zuruecknehmen_gibt_die_posten_wieder_frei(db):
    mid = _mitglied(db)
    lauf = db.sepa.create_lauf(_lauf(), [_position(mid)], erstellt_von='kasse')
    assert db.sepa.zuruecknehmen(lauf.id, benutzer='kasse') == 1
    zurueckgenommen = db.sepa.get_lauf(lauf.id)
    assert zurueckgenommen.deleted_at is not None
    assert zurueckgenommen.positionen == []          # nur lebende Positionen
    assert [x.id for x in db.sepa.list_laeufe()] == []
    # Derselbe Posten ist wieder einziehbar
    neu = db.sepa.create_lauf(_lauf(message_id='VTB-20260730-140000'),
                              [_position(mid)], erstellt_von='kasse')
    assert neu.anzahl_positionen == 1


def test_get_lauf_wirft_keyerror_wenn_unbekannt(db):
    with pytest.raises(KeyError):
        db.sepa.get_lauf(999999)


def test_einstellungen_roundtrip_ueber_das_repository(db):
    einst = db.fibu_einstellungen.get()
    einst.sepa_glaeubiger_id = 'DE98ZZZ09999999999'
    einst.sepa_glaeubiger_name = 'VTB Chemnitz e. V.'
    einst.sepa_iban = 'DE02100500000054540402'
    einst.sepa_bic = 'BELADEBE'
    einst.sepa_vorlauftage = 3
    gespeichert = db.fibu_einstellungen.update(einst, updated_by='kasse')
    assert gespeichert.sepa_glaeubiger_id == 'DE98ZZZ09999999999'
    assert gespeichert.sepa_vorlauftage == 3
    # Der Config-Audit-Trigger muss die neuen Spalten mitschreiben
    with db.conn.cursor() as cur:
        cur.execute("SELECT sepa_iban FROM fibu_einstellungen_history "
                    "WHERE version = %s", (gespeichert.version,))
        assert cur.fetchone()['sepa_iban'] == 'DE02100500000054540402'


def test_kandidaten_ignorieren_bereits_eingezogene_posten(db):
    """Ein Posten in einem lebenden Lauf darf nicht mehr als Kandidat auftauchen."""
    mid = _mitglied(db)
    with db.conn.cursor() as cur:
        cur.execute("UPDATE mitglied SET zahlungsart='lastschrift', "
                    "iban='DE02120300000000202051', eintrittsdatum='2019-04-01' "
                    "WHERE id = %s", (mid,))
        cur.execute("INSERT INTO beitragsregel (name, betrag_pro_monat, einzug_turnus, "
                    "gueltig_ab, created_by) "
                    "VALUES ('Beitrag Erwachsene', 14.17, 'quartal', '2026-01-01', %s) "
                    "RETURNING id", (_MARKE,))
        regel_id = cur.fetchone()['id']
        cur.execute("INSERT INTO beitrag_sollstellung "
                    "(mitglied_id, beitragsregel_id, zeitraum, betrag_soll, "
                    " faelligkeitsdatum, created_by) "
                    "VALUES (%s, %s, '2026-Q3', 42.5, '2026-07-01', %s) RETURNING id",
                    (mid, regel_id, _MARKE))
        soll_id = cur.fetchone()['id']

    # Nur die eigenen Kandidaten prüfen – in der geteilten Wegwerf-DB können offene
    # Posten anderer Testmodule stehen.
    def eigene():
        return [r['quelle_id'] for r in db.sepa.list_kandidaten('2026-08-03')
                if r['mitglied_id'] == mid]

    assert eigene() == [soll_id]

    db.sepa.create_lauf(_lauf(), [_position(mid, quelle_id=soll_id)], erstellt_von='kasse')
    assert eigene() == []
