"""Spitzname am Kader-Eintrag, Schema v119 (#194) – Fresh == Migriert.

Der Spitzname hängt an ``mitglied_mannschaft`` und nicht am Mitglied, damit ihn
die Mannschaft selbst pflegen kann (Kader-Schreibrecht) und er nicht in
Vereinsunterlagen auswandert. Geprüft wird beides: der Frischaufbau (VereinsDB
legt v119 beim Connect an) und der Upgrade-Pfad aus einer nachgestellten
v118-Datenbank.

Der Fallstrick ist der übliche: Eine neue Spalte an einer auditierten Tabelle
braucht auch die neuen Audit-Funktionen. Wer nur `ALTER TABLE` macht, bekommt
eine History, die den Spitznamen nicht kennt – ohne dass irgendetwas kracht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB). Beispiel:
    docker run -d --rm --name vtb-pg-spitzname -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=spitzname -p 55492:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55492/spitzname \\
        ./venv/bin/python -m pytest \\
        vtb_verein/tests/test_kader_spitzname_integration.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()

# Spaltenstand vor v119 – Grundlage der zurückgedrehten Audit-Funktionen.
_V118_COLS = ("id, version, mitglied_id, mannschaft_id, rolle, von, bis, "
              "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-spitzname-uploads")
    yield d
    d.close()


def _reste_weg(db):
    """Alles wegräumen, was diese Tests anlegen – Kind vor Eltern.

    Die verwaisten *_history-Zeilen müssen mit: Die Wegwerf-DB ist über alle
    Testdateien geteilt, und ein TRUNCATE ... RESTART IDENTITY anderswo lässt ids
    erneut vergeben – eine übrig gebliebene History-Zeile kollidierte dann mit
    dem Primärschlüssel (id, version) der Neuanlage.
    """
    with db.cursor() as cur:
        cur.execute("DELETE FROM mitglied_mannschaft mm USING mannschaft m "
                    "WHERE m.id = mm.mannschaft_id AND m.name LIKE 'Spitzname-%'")
        cur.execute("DELETE FROM mitglied WHERE nachname = 'Spitznamentest'")
        cur.execute("DELETE FROM mannschaft WHERE name LIKE 'Spitzname-%'")
        cur.execute("DELETE FROM abteilung WHERE name = 'Spitzname-Abt'")
        for tabelle, eltern in (("mitglied_mannschaft_history", "mitglied_mannschaft"),
                                ("mitglied_history", "mitglied"),
                                ("mannschaft_history", "mannschaft"),
                                ("abteilung_history", "abteilung")):
            cur.execute(f"DELETE FROM {tabelle} h WHERE NOT EXISTS "
                        f"(SELECT 1 FROM {eltern} e WHERE e.id = h.id)")


@pytest.fixture(autouse=True)
def clean(db):
    _reste_weg(db)
    yield
    _reste_weg(db)


def _mannschaft(db, name="Spitzname-Erste"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name='Spitzname-Abt' AND deleted_at IS NULL")
        row = cur.fetchone()
        aid = row['id'] if row else None
        if aid is None:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES ('Spitzname-Abt','t','t') RETURNING id")
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,created_by,updated_by) "
                    "VALUES (%s,%s,'t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _mitglied(db, vorname="Sebastian"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,created_by,updated_by) "
                    "VALUES (%s,'Spitznamentest','lastschrift','t','t') RETURNING id",
                    (vorname,))
        return cur.fetchone()['id']


def _version(db, zuordnung_id):
    with db.cursor() as cur:
        cur.execute("SELECT version FROM mitglied_mannschaft WHERE id=%s", (zuordnung_id,))
        return cur.fetchone()['version']


# --------------------------------------------------------------- Frischaufbau
def test_spitzname_gilt_fuer_alle_zuordnungen_des_mitglieds(db):
    """Spieler UND Betreuer in derselben Mannschaft = zwei Zeilen, ein Spitzname.

    Lägen sie auseinander, hinge die Anzeige davon ab, welche Zeile eine Abfrage
    zuerst erwischt.
    """
    team = _mannschaft(db)
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    db.create_mitglied_mannschaft(mid, team, 'betreuer', LASTWEEK, None, 't')

    assert db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't') is True

    rollen = {z.rolle: z.spitzname for z in db.list_mannschaft_kader(team)}
    assert rollen == {'spieler': 'Basti', 'betreuer': 'Basti'}
    assert db.mannschaft_spitznamen(team) == {mid: 'Basti'}


def test_leereingabe_loescht_den_spitznamen(db):
    team = _mannschaft(db)
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't', spitzname='Basti')

    db.set_mitglied_mannschaft_spitzname(team, mid, '   ', 't')

    assert db.mannschaft_spitznamen(team) == {}
    assert db.list_mannschaft_kader(team)[0].spitzname is None


def test_unveraenderter_spitzname_erzeugt_keine_history_zeile(db):
    """Kein version-Bump ohne Änderung – sonst wüchse die History beim Speichern
    einer unveränderten Kaderliste um lauter leere Einträge."""
    team = _mannschaft(db)
    mid = _mitglied(db)
    z = db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't')
    vorher = _version(db, z.id)

    assert db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't') is True

    assert _version(db, z.id) == vorher


def test_mitglied_ausserhalb_des_kaders_meldet_sich_ab(db):
    """Rückgabe False = „steht nicht im aktiven Kader" (die API macht daraus 404)."""
    team = _mannschaft(db)
    mid = _mitglied(db)

    assert db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't') is False


def test_beendete_zuordnung_liefert_keinen_spitznamen_mehr(db):
    team = _mannschaft(db)
    mid = _mitglied(db)
    z = db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't',
                                      spitzname='Basti')
    db.mark_mitglied_mannschaft_deleted(z.id, 't')

    assert db.mannschaft_spitznamen(team) == {}


def test_spitzname_ist_je_mannschaft_verschieden(db):
    """Der Spitzname gehört der Mannschaft – zwei Teams, zwei Namen."""
    erste = _mannschaft(db, 'Spitzname-Erste')
    zweite = _mannschaft(db, 'Spitzname-Zweite')
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, erste, 'spieler', LASTWEEK, None, 't')
    db.create_mitglied_mannschaft(mid, zweite, 'spieler', LASTWEEK, None, 't')

    db.set_mitglied_mannschaft_spitzname(erste, mid, 'Basti', 't')
    db.set_mitglied_mannschaft_spitzname(zweite, mid, 'Der Lange', 't')

    assert db.mannschaft_spitznamen(erste) == {mid: 'Basti'}
    assert db.mannschaft_spitznamen(zweite) == {mid: 'Der Lange'}


def test_audit_trigger_schreibt_den_spitznamen_mit(db):
    team = _mannschaft(db)
    mid = _mitglied(db)
    z = db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't')

    with db.cursor() as cur:
        cur.execute("SELECT version, spitzname FROM mitglied_mannschaft_history "
                    "WHERE id=%s ORDER BY version", (z.id,))
        verlauf = [(r['version'], r['spitzname']) for r in cur.fetchall()]

    assert verlauf[0] == (1, None)
    assert verlauf[-1][1] == 'Basti'


# ---------------------------------------------------------------- API-Endpunkt
# Ein Kader-Betreuer OHNE globales mannschaften.write – genau der Fall, für den
# der Spitzname am Kader hängt und nicht am Mitglied.
_BETREUER = SimpleNamespace(id=4242, username='betreuer', role='mitglied',
                            has_permission=lambda p: False)


def _als_betreuer(db, mannschaft_id):
    """Den Endpunkt so aufrufen, als wäre _BETREUER Kader-Betreuer dieses Teams."""
    from backend.api import mannschaften as api
    db.mannschaft_kader_verwalten_ids = lambda uid: {mannschaft_id}
    return api


def test_endpunkt_setzt_spitzname_ohne_personen_recht(db):
    """Der Kern der Entscheidung: Kader-Schreibrecht genügt, `personen.write` nicht nötig."""
    team = _mannschaft(db)
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    api = _als_betreuer(db, team)

    antwort = api.set_spitzname(team, mid, api.SpitznameUpdate(spitzname=' Basti '),
                                _BETREUER, db)

    assert antwort == {'mitglied_id': mid, 'spitzname': 'Basti'}


def test_endpunkt_lehnt_fremden_kader_ab(db):
    from fastapi import HTTPException
    team = _mannschaft(db)
    fremd = _mannschaft(db, 'Spitzname-Zweite')
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, fremd, 'spieler', LASTWEEK, None, 't')
    api = _als_betreuer(db, team)

    with pytest.raises(HTTPException) as exc:
        api.set_spitzname(fremd, mid, api.SpitznameUpdate(spitzname='Basti'), _BETREUER, db)
    assert exc.value.status_code == 403


def test_endpunkt_lehnt_zu_langen_spitznamen_ab(db):
    from fastapi import HTTPException
    team = _mannschaft(db)
    mid = _mitglied(db)
    db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    api = _als_betreuer(db, team)

    with pytest.raises(HTTPException) as exc:
        api.set_spitzname(team, mid, api.SpitznameUpdate(spitzname='x' * 41),
                          _BETREUER, db)
    assert exc.value.status_code == 422


def test_endpunkt_meldet_mitglied_ausserhalb_des_kaders(db):
    from fastapi import HTTPException
    team = _mannschaft(db)
    mid = _mitglied(db)
    api = _als_betreuer(db, team)

    with pytest.raises(HTTPException) as exc:
        api.set_spitzname(team, mid, api.SpitznameUpdate(spitzname='Basti'), _BETREUER, db)
    assert exc.value.status_code == 404


# ------------------------------------------------------------ Migration v118→v119
@pytest.fixture()
def auf_v118(db):
    """Das Schema auf den Stand vor v119 zurückdrehen."""
    _reste_weg(db)
    vals = ", ".join("NEW." + c.strip() for c in _V118_COLS.split(","))
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied_mannschaft DROP COLUMN IF EXISTS spitzname")
        cur.execute("ALTER TABLE mitglied_mannschaft_history DROP COLUMN IF EXISTS spitzname")
        for ereignis in ("insert", "update"):
            wache = ("IF NEW.version != OLD.version THEN" if ereignis == "update"
                     else "IF true THEN")
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_{ereignis}()
                RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    {wache}
                        INSERT INTO mitglied_mannschaft_history ({_V118_COLS})
                        VALUES ({vals});
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
    yield
    # Die Modul-DB ist geteilt – für nachfolgende Tests wieder anheben.
    db._database._migrate_v118_to_v119()
    _reste_weg(db)


def _spalte_da(db, tabelle):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s "
                    "AND column_name='spitzname'", (tabelle,))
        return cur.fetchone() is not None


def test_migration_ergaenzt_spalte_in_tabelle_und_history(db, auf_v118):
    assert not _spalte_da(db, 'mitglied_mannschaft')
    assert not _spalte_da(db, 'mitglied_mannschaft_history')

    db._database._migrate_v118_to_v119()

    assert _spalte_da(db, 'mitglied_mannschaft')
    assert _spalte_da(db, 'mitglied_mannschaft_history')


def test_migration_zieht_die_audit_funktionen_nach(db, auf_v118):
    """Der eigentliche Fallstrick: ALTER TABLE allein lässt eine History zurück,
    die den Spitznamen nie sieht – lautlos."""
    db._database._migrate_v118_to_v119()

    team = _mannschaft(db)
    mid = _mitglied(db)
    z = db.create_mitglied_mannschaft(mid, team, 'spieler', LASTWEEK, None, 't')
    db.set_mitglied_mannschaft_spitzname(team, mid, 'Basti', 't')

    with db.cursor() as cur:
        cur.execute("SELECT spitzname FROM mitglied_mannschaft_history "
                    "WHERE id=%s ORDER BY version DESC LIMIT 1", (z.id,))
        assert cur.fetchone()['spitzname'] == 'Basti'


def test_migration_laesst_bestand_ohne_spitzname_stehen(db, auf_v118):
    """Bestehende Zuordnungen bekommen NULL – kein erfundener Anzeigename."""
    team = _mannschaft(db)
    mid = _mitglied(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_mannschaft "
                    "(mitglied_id,mannschaft_id,rolle,von,created_by,updated_by) "
                    "VALUES (%s,%s,'spieler',%s,'t','t') RETURNING id",
                    (mid, team, LASTWEEK))
        zid = cur.fetchone()['id']

    db._database._migrate_v118_to_v119()

    assert db.get_mitglied_mannschaft(zid).spitzname is None
    assert db.mannschaft_spitznamen(team) == {}
