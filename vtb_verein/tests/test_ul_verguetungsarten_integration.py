"""
Integrationstest der ÜL-Vergütungsarten gegen echtes PostgreSQL – Ticket #84.

Nicht jeder Übungsleiter wird nach Stunden bezahlt: Es gibt den Monatsfestbetrag und
den ÜL, der gar nicht über die App abgerechnet wird. Erfasst werden die Stunden in
allen Fällen – nur die Betragsformel und der Fibu-Export hängen an der
`verguetungsart` der Vereinbarung.

Geprüft werden beide Schema-Pfade (Frischaufbau und Migration v105→v106) sowie die
beiden Stellen, an denen die Art wirkt: die Satz-Auflösung (`ul_saetze.resolve`) und
das Export-SQL (`_SQL_UL`) – Letzteres trägt die Betragsformel ein zweites Mal, in
SQL, und ist damit die Stelle, die stillschweigend auseinanderlaufen kann.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt:
    docker run -d --name vtb-pg-v106 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=v106test -p 55444:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55444/v106test \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_ul_verguetungsarten_integration.py
"""
import os
from contextlib import contextmanager

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# created_by-Stempel aller hier angelegten Zeilen – die Wegwerf-DB teilen sich alle
# Integrationstests, daran erkennt die Aufräum-Fixture das Eigene.
_MARKE = 'verguetungsarttest'

# Spaltensatz der ul_satz-/ul_abrechnung-Audit-Funktionen VOR v106 – für den Nachbau
# des v105-Stands.
_V105_SATZ_COLS = (
    "id, version, mitglied_id, abteilung_id, lizenz_klassifikation, satz, gueltig_ab, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)
_V105_ABRECHNUNG_COLS = (
    "id, version, mitglied_id, abteilung_id, zeitraum_von, zeitraum_bis, status, "
    "lizenz_klassifikation, foerder_klassifikation, verguetung_pro_stunde, "
    "trainerlizenz_nr, qualifikation, "
    "eingereicht_am, eingereicht_von, bestaetigt_am, bestaetigt_von, abgelehnt_grund, "
    "exportiert_in_export_id, storno_exportiert_in_export_id, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-verguetungsart-uploads")
    yield d
    d.close()


@contextmanager
def _cur(db):
    """Cursor mit Commit/Rollback wie in BaseRepository (dieser Test fährt rohes SQL)."""
    with db.conn.cursor() as cur:
        try:
            yield cur
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise


@pytest.fixture(autouse=True)
def sauber(db):
    """Räumt vor und nach jedem Test alles mit unserer Marke weg."""
    def putzen():
        with _cur(db) as cur:
            for tabelle in ('ul_stunde', 'ul_abrechnung', 'ul_satz'):
                cur.execute(f"DELETE FROM {tabelle}_history WHERE created_by = %s", (_MARKE,))
                cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (_MARKE,))
            cur.execute("DELETE FROM mitglied WHERE created_by = %s", (_MARKE,))
            cur.execute("DELETE FROM abteilung WHERE created_by = %s", (_MARKE,))
    putzen()
    yield
    putzen()


def _spalte(cur, tabelle: str, spalte: str) -> dict:
    cur.execute(
        """
        SELECT data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (tabelle, spalte),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _stammdaten(cur):
    """Ein Mitglied und eine Abteilung, an denen die Abrechnungen hängen."""
    cur.execute(
        "INSERT INTO abteilung (name, kuerzel, created_by, updated_by) "
        "VALUES (%s, 'VGA', %s, %s) RETURNING id",
        (f'{_MARKE}-Abteilung', _MARKE, _MARKE))
    abteilung_id = cur.fetchone()['id']
    cur.execute(
        "INSERT INTO mitglied (vorname, nachname, mitgliedsnummer, zahlungsart, "
        "                      created_by, updated_by) "
        "VALUES ('Uwe', %s, 990084, 'ueberweisung', %s, %s) RETURNING id",
        (f'{_MARKE}-UL', _MARKE, _MARKE))
    return cur.fetchone()['id'], abteilung_id


def _satz(cur, *, mitglied_id=None, abteilung_id=None, lizenz=None,
          art='stundensatz', satz=10.0):
    cur.execute(
        """
        INSERT INTO ul_satz (mitglied_id, abteilung_id, lizenz_klassifikation,
                             verguetungsart, satz, created_by, updated_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        (mitglied_id, abteilung_id, lizenz, art, satz, _MARKE, _MARKE))
    return cur.fetchone()['id']


def _abrechnung(cur, mitglied_id, abteilung_id, *, von, bis, art, satz,
                monate=None, status='bestaetigt'):
    cur.execute(
        """
        INSERT INTO ul_abrechnung
            (mitglied_id, abteilung_id, zeitraum_von, zeitraum_bis, status,
             lizenz_klassifikation, verguetungsart, verguetung_pro_stunde,
             verguetung_monate, eingereicht_am, eingereicht_von,
             bestaetigt_am, bestaetigt_von, created_by, updated_by)
        VALUES (%s,%s,%s,%s,%s,'ohne_lizenz',%s,%s,%s,
                CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP,%s,%s,%s)
        RETURNING id
        """,
        (mitglied_id, abteilung_id, von, bis, status, art, satz, monate,
         _MARKE, _MARKE, _MARKE, _MARKE))
    return cur.fetchone()['id']


def _stunde(cur, abrechnung_id, datum, stunden=2.0):
    cur.execute(
        "INSERT INTO ul_stunde (abrechnung_id, datum, stunden, created_by, updated_by) "
        "VALUES (%s,%s,%s,%s,%s)",
        (abrechnung_id, datum, stunden, _MARKE, _MARKE))


# ---------------------------------------------------------------------------
# Schema: Frischaufbau
# ---------------------------------------------------------------------------

def test_frischaufbau_kennt_die_verguetungsart(db):
    """Die Art hängt an Vereinbarung UND Abrechnungs-Snapshot, jeweils mit History."""
    with _cur(db) as cur:
        for tabelle in ('ul_satz', 'ul_abrechnung'):
            spalte = _spalte(cur, tabelle, 'verguetungsart')
            assert spalte is not None, f"{tabelle}.verguetungsart fehlt"
            assert spalte['is_nullable'] == 'NO'
            assert "'stundensatz'" in spalte['column_default']
            assert _spalte(cur, f'{tabelle}_history', 'verguetungsart') is not None


def test_frischaufbau_macht_die_lizenz_am_satz_optional(db):
    """NULL = „gilt für beide" – sonst fällt eine individuelle Festbetrags-Vereinbarung
    still auf den vereinsweiten Stundensatz zurück, sobald die Lizenz ausläuft."""
    with _cur(db) as cur:
        spalte = _spalte(cur, 'ul_satz', 'lizenz_klassifikation')
        assert spalte['is_nullable'] == 'YES'
        assert spalte['column_default'] is None
        # An der Abrechnung bleibt sie Pflicht: dort ist sie immer abgeleitet.
        assert _spalte(cur, 'ul_abrechnung', 'lizenz_klassifikation')['is_nullable'] == 'NO'


# ---------------------------------------------------------------------------
# Schema: Migration v105 → v106 (Fresh == Migriert)
# ---------------------------------------------------------------------------

def test_migration_v105_v106_holt_den_frischaufbau_ein(db):
    """Der eigentliche Prüfstein: Eine gewachsene DB muss danach exakt so aussehen
    wie eine frisch angelegte – inklusive Audit-Trigger, der die neue Spalte
    mitschreibt (der Fehler aus v78→v79, den es nicht wieder geben soll)."""
    interessant = (('ul_satz', 'verguetungsart'), ('ul_satz', 'lizenz_klassifikation'),
                   ('ul_satz_history', 'verguetungsart'),
                   ('ul_abrechnung', 'verguetungsart'),
                   ('ul_abrechnung', 'verguetung_monate'),
                   ('ul_abrechnung_history', 'verguetungsart'),
                   ('ul_abrechnung_history', 'verguetung_monate'))

    with _cur(db) as cur:
        frisch = {(t, s): _spalte(cur, t, s) for t, s in interessant}

    # --- v105-Stand nachbauen ---
    with _cur(db) as cur:
        # Ein Bestands-Satz, wie er unter v105 entstanden wäre (Lizenz war Pflicht).
        cur.execute(
            "INSERT INTO ul_satz (lizenz_klassifikation, satz, created_by, updated_by) "
            "VALUES ('mit_lizenz', 17.5, %s, %s) RETURNING id", (_MARKE, _MARKE))
        alt_satz_id = cur.fetchone()['id']

        for tabelle in ('ul_satz', 'ul_satz_history',
                        'ul_abrechnung', 'ul_abrechnung_history'):
            cur.execute(f"ALTER TABLE {tabelle} DROP COLUMN IF EXISTS verguetungsart")
        for tabelle in ('ul_abrechnung', 'ul_abrechnung_history'):
            cur.execute(f"ALTER TABLE {tabelle} DROP COLUMN IF EXISTS verguetung_monate")
        cur.execute("ALTER TABLE ul_satz ALTER COLUMN lizenz_klassifikation "
                    "SET DEFAULT 'ohne_lizenz'")
        cur.execute("ALTER TABLE ul_satz ALTER COLUMN lizenz_klassifikation SET NOT NULL")
        for name, cols in (('ul_satz', _V105_SATZ_COLS),
                           ('ul_abrechnung', _V105_ABRECHNUNG_COLS)):
            vals = ", ".join("NEW." + c.strip() for c in cols.split(","))
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_{name}_audit_insert() RETURNS TRIGGER
                LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO {name}_history ({cols}) VALUES ({vals});
                    RETURN NEW;
                END; $$;
            """)
        cur.execute("UPDATE schema_version SET version = 105 WHERE id = 1")

    # --- migrieren ---
    db._database._migrate_v105_to_v106()

    with _cur(db) as cur:
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()['version'] == 106

        for schluessel, erwartet in frisch.items():
            assert _spalte(cur, *schluessel) == erwartet, \
                f"{schluessel[0]}.{schluessel[1]} weicht vom Frischaufbau ab"

        # Altbestand rechnet unverändert weiter – nach Stunden.
        cur.execute("SELECT verguetungsart, lizenz_klassifikation FROM ul_satz WHERE id = %s",
                    (alt_satz_id,))
        alt = cur.fetchone()
        assert alt['verguetungsart'] == 'stundensatz'
        assert alt['lizenz_klassifikation'] == 'mit_lizenz'

    # Audit-Trigger schreibt die neue Spalte jetzt mit.
    with _cur(db) as cur:
        neu_id = _satz(cur, art='monatspauschale', satz=150.0)
    with _cur(db) as cur:
        cur.execute("SELECT verguetungsart FROM ul_satz_history WHERE id = %s", (neu_id,))
        assert cur.fetchone()['verguetungsart'] == 'monatspauschale'


# ---------------------------------------------------------------------------
# Satz-Auflösung
# ---------------------------------------------------------------------------

def test_resolve_liefert_die_vereinbarung_samt_art(db):
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, mitglied_id=mitglied_id, art='monatspauschale', satz=150.0)

    gefunden = db.ul_saetze.resolve(mitglied_id, abteilung_id, 'ohne_lizenz')
    assert gefunden.verguetungsart == 'monatspauschale' and gefunden.satz == 150.0


def test_individuelle_vereinbarung_ueberlebt_den_lizenzablauf(db):
    """Der Grund für die optionale Lizenz: Ein ÜL mit Festbetrag behält ihn auch,
    wenn seine Trainerlizenz ausläuft und die Abrechnung auf 'ohne_lizenz' kippt."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, mitglied_id=mitglied_id, lizenz=None,
              art='monatspauschale', satz=200.0)                  # gilt für beide
        _satz(cur, abteilung_id=abteilung_id, lizenz='ohne_lizenz', satz=9.0)
        _satz(cur, lizenz='ohne_lizenz', satz=8.0)                # vereinsweit

    for lizenz in ('mit_lizenz', 'ohne_lizenz'):
        gefunden = db.ul_saetze.resolve(mitglied_id, abteilung_id, lizenz)
        assert gefunden.satz == 200.0, f"{lizenz}: individuelle Vereinbarung übergangen"
        assert gefunden.verguetungsart == 'monatspauschale'


def test_exakte_lizenz_schlaegt_jede_lizenz_auf_gleicher_stufe(db):
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, abteilung_id=abteilung_id, lizenz=None, satz=11.0)
        _satz(cur, abteilung_id=abteilung_id, lizenz='mit_lizenz', satz=22.0)

    assert db.ul_saetze.resolve(mitglied_id, abteilung_id, 'mit_lizenz').satz == 22.0
    assert db.ul_saetze.resolve(mitglied_id, abteilung_id, 'ohne_lizenz').satz == 11.0


# ---------------------------------------------------------------------------
# Fibu-Export: die Betragsformel in SQL
# ---------------------------------------------------------------------------

def _ul_positionen(db):
    return {r['quelle_id']: r for r in db.fibu_exporte.list_neue_positionen()
            if r['quelle_typ'] == 'ul_abrechnung'}


def test_export_rechnet_stundensatz_nach_stunden(db):
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        aid = _abrechnung(cur, mitglied_id, abteilung_id, von='2026-06-01',
                          bis='2026-06-30', art='stundensatz', satz=12.5)
        _stunde(cur, aid, '2026-06-02', 2.0)
        _stunde(cur, aid, '2026-06-09', 2.0)

    assert float(_ul_positionen(db)[aid]['betrag_soll']) == 50.0


def test_export_rechnet_monatspauschale_nach_eingefrorenen_monaten(db):
    """3 Monate × 150 € = 450 €, egal wie viele Stunden darin stecken. Die Monatszahl
    kommt aus dem Snapshot – das Export-SQL multipliziert nur noch."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        aid = _abrechnung(cur, mitglied_id, abteilung_id, von='2026-06-15',
                          bis='2026-08-03', art='monatspauschale', satz=150.0, monate=3)
        _stunde(cur, aid, '2026-06-16', 2.0)

    assert float(_ul_positionen(db)[aid]['betrag_soll']) == 450.0


def test_export_rechnet_monatspauschale_im_einzelmonat(db):
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        aid = _abrechnung(cur, mitglied_id, abteilung_id, von='2026-06-01',
                          bis='2026-06-30', art='monatspauschale', satz=150.0, monate=1)
        _stunde(cur, aid, '2026-06-16', 2.0)

    assert float(_ul_positionen(db)[aid]['betrag_soll']) == 150.0


def test_export_laesst_abrechnungen_ohne_verguetung_aussen_vor(db):
    """Reiner Stundennachweis: Die Auszahlung läuft außerhalb der App, es darf
    also gar keine Kreditor-Buchung entstehen – auch keine über 0,00 €."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        aid = _abrechnung(cur, mitglied_id, abteilung_id, von='2026-06-01',
                          bis='2026-06-30', art='ohne_verguetung', satz=0.0)
        _stunde(cur, aid, '2026-06-02', 2.0)

    assert aid not in _ul_positionen(db)


# ---------------------------------------------------------------------------
# Snapshot lösen
# ---------------------------------------------------------------------------

def test_zuruecksetzen_loest_auch_die_art_aus_dem_snapshot(db):
    """Wer zurückzieht, bekommt beim erneuten Einreichen die dann gültige
    Vereinbarung – die Art darf also nicht als Rest der alten stehenbleiben."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        aid = _abrechnung(cur, mitglied_id, abteilung_id, von='2026-06-01',
                          bis='2026-06-30', art='monatspauschale', satz=150.0,
                          status='eingereicht')
        _stunde(cur, aid, '2026-06-02', 2.0)

    assert db.ul_abrechnungen.zuruecksetzen(aid, updated_by=_MARKE)

    zurueck = db.ul_abrechnungen.get(aid)
    assert zurueck.status == 'entwurf'
    assert zurueck.verguetungsart == 'stundensatz'      # Spalten-Default
    assert zurueck.verguetung_pro_stunde is None


# ---------------------------------------------------------------------------
# Monats-Abgrenzung über zwei Abrechnungen (der Fall aus #84)
# ---------------------------------------------------------------------------

def _durchlauf(db, mitglied_id, abteilung_id, von, bis):
    """Abrechnung anlegen, einen Termin erfassen, einreichen und bestätigen –
    der volle Weg, weil die Monats-Abgrenzung beim Einreichen entschieden wird."""
    from app.services.ul_stunden_service import ULStundenService
    svc = ULStundenService(db)
    a = svc.create_abrechnung(mitglied_id=mitglied_id, abteilung_id=abteilung_id,
                              von=von, bis=bis, erstellt_von=_MARKE)
    svc.add_stunde(a, datum=von, stunden=2.0, angebot=None, bemerkung=None,
                   erstellt_von=_MARKE)
    svc.einreichen(a, eingereicht_von=_MARKE)
    assert db.ul_abrechnungen.bestaetigen(a.id, bestaetigt_von=_MARKE)
    return a.id


def test_geteilter_monat_wird_nur_einmal_verguetet(db):
    """15.05.–15.06. und 16.06.–10.07.: Der Juni gehört der ersten Abrechnung.
    Zusammen drei Pauschalen (Mai, Juni, Juli) – nicht vier.

    Die Sperr-Logik lässt genau diesen Anschluss zu (erfassbar_ab = 16.06.), sie
    rechnet tagegenau. Ohne eigene Monats-Abgrenzung würde der Juni doppelt bezahlt.
    """
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, mitglied_id=mitglied_id, art='monatspauschale', satz=150.0)

    erste = _durchlauf(db, mitglied_id, abteilung_id, '2026-05-15', '2026-06-15')
    zweite = _durchlauf(db, mitglied_id, abteilung_id, '2026-06-16', '2026-07-10')

    assert db.ul_abrechnungen.get(erste).verguetung_monate == 2      # Mai + Juni
    assert db.ul_abrechnungen.get(zweite).verguetung_monate == 1     # nur Juli

    positionen = _ul_positionen(db)
    assert float(positionen[erste]['betrag_soll']) == 300.0
    assert float(positionen[zweite]['betrag_soll']) == 150.0
    gesamt = sum(float(positionen[i]['betrag_soll']) for i in (erste, zweite))
    assert gesamt == 450.0, "Juni wurde ein zweites Mal vergütet"


def test_nachtrag_im_schon_verguteten_monat_kostet_nichts(db):
    """Zweite Abrechnung komplett innerhalb eines bereits vergüteten Monats:
    Stunden werden erfasst, eine zweite Pauschale gibt es nicht."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, mitglied_id=mitglied_id, art='monatspauschale', satz=150.0)

    _durchlauf(db, mitglied_id, abteilung_id, '2026-06-01', '2026-06-15')
    zweite = _durchlauf(db, mitglied_id, abteilung_id, '2026-06-16', '2026-06-30')

    a = db.ul_abrechnungen.get(zweite)
    assert a.verguetung_monate == 0
    # Gar keine Buchung statt einer über 0,00 € – sonst müllt jeder Nachtrag die Fibu zu.
    assert zweite not in _ul_positionen(db)
    # Der Stundennachweis bleibt trotzdem vollständig – darum geht es bei der Pauschale.
    assert len(db.ul_abrechnungen.list_stunden(zweite)) == 1


def test_spaetere_nachbarabrechnung_verschiebt_den_betrag_nicht(db):
    """Der Snapshot ist der Punkt: Was beim Einreichen entschieden wurde, muss
    stehenbleiben, auch wenn danach weitere Abrechnungen dazukommen."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        _satz(cur, mitglied_id=mitglied_id, art='monatspauschale', satz=150.0)

    erste = _durchlauf(db, mitglied_id, abteilung_id, '2026-05-15', '2026-06-15')
    vorher = float(_ul_positionen(db)[erste]['betrag_soll'])

    _durchlauf(db, mitglied_id, abteilung_id, '2026-06-16', '2026-07-10')

    assert float(_ul_positionen(db)[erste]['betrag_soll']) == vorher == 300.0


def test_andere_abteilung_bekommt_ihren_eigenen_monat(db):
    """Zwei Vereinbarungen, zwei Pauschalen: Wer in Fußball und Turnen eine
    Monatspauschale hat, bekommt im selben Monat beide."""
    with _cur(db) as cur:
        mitglied_id, abteilung_id = _stammdaten(cur)
        cur.execute(
            "INSERT INTO abteilung (name, kuerzel, created_by, updated_by) "
            "VALUES (%s, 'VGB', %s, %s) RETURNING id",
            (f'{_MARKE}-Abteilung-2', _MARKE, _MARKE))
        zweite_abteilung = cur.fetchone()['id']
        _satz(cur, mitglied_id=mitglied_id, art='monatspauschale', satz=150.0)

    a = _durchlauf(db, mitglied_id, abteilung_id, '2026-06-01', '2026-06-30')
    b = _durchlauf(db, mitglied_id, zweite_abteilung, '2026-06-01', '2026-06-30')

    assert db.ul_abrechnungen.get(a).verguetung_monate == 1
    assert db.ul_abrechnungen.get(b).verguetung_monate == 1
