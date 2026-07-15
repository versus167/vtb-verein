"""Integrationstests der Termin-Zusagen (RSVP, #95 Spielbetrieb Etappe 2) gegen echtes PostgreSQL.

Prüft Schema v69 (termin_zusage + History-Trigger + CHECK + partieller aktiver Unique),
das Repository (Upsert = Insert/Update mit version-Bump, Soft-Delete/Reaktivierung,
Zähler, eigene Antwort, Kader-mit-Antwort) und die neuen Kader-ACL-Helfer
(get_kader_mitglied_id / is_mitglied_in_kader) inkl. Aktiv-am-Stichtag-Semantik.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` auf einer (leeren) Wegwerf-DB – VereinsDB legt das
Schema beim Connect an. Beispiel:
    docker run -d --name vtb-pg-zusagetest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=zusagetest -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55433/zusagetest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_termin_zusage_integration.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
NEXTWEEK = (date.today() + timedelta(days=7)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-zusage-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE termin_zusage, termin_zusage_history, termine, termine_history, "
            "mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='Zusage'")
        cur.execute("DELETE FROM users WHERE username LIKE 'zusagetester%'")
        cur.execute("DELETE FROM abteilung WHERE name='Zusage-Abt'")
    yield


def _make_mannschaft(db, name="Erste", abteilung="Zusage-Abt"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name=%s AND deleted_at IS NULL", (abteilung,))
        row = cur.fetchone()
        aid = row['id'] if row else None
        if aid is None:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES (%s,'t','t') RETURNING id", (abteilung,))
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_kader_mitglied(db, mannschaft_id, rolle="spieler", von=LASTWEEK, bis=None,
                         username="zusagetester", nachname="Tester", mit_user=True):
    """User (optional) + Mitglied + Kader-Zuordnung. Gibt (user_id | None, mitglied_id)."""
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                        "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                        (username, f"{username}@x.de"))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('Zusage',%s,'lastschrift',%s,'t','t') RETURNING id", (nachname, uid))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,bis,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'t','t')", (mid, mannschaft_id, rolle, von, bis))
    return uid, mid


def _termin(db, mannschaft_id, beginn=f"{TOMORROW}T19:00"):
    return db.termine.create(mannschaft_id, 'training', beginn, None, None, None,
                             None, None, None, None, 't')


# --------------------------------------------------------------- Schema/Trigger
def test_history_trigger_und_version_bump(db):
    mid = _make_mannschaft(db)
    _uid, mit = _make_kader_mitglied(db, mid)
    t = _termin(db, mid)

    z = db.termin_zusagen.set_antwort(t.id, mit, 'zu', None, 'tester')
    assert z.antwort == 'zu' and z.version == 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termin_zusage_history WHERE id=%s", (z.id,))
        assert cur.fetchone()['n'] == 1

    z2 = db.termin_zusagen.set_antwort(t.id, mit, 'ab', 'doch keine Zeit', 'tester')
    assert z2.id == z.id and z2.antwort == 'ab' and z2.version == 2   # gleiche Zeile, Upsert
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termin_zusage_history WHERE id=%s", (z.id,))
        assert cur.fetchone()['n'] == 2


def test_check_constraint_antwort(db):
    mid = _make_mannschaft(db)
    _uid, mit = _make_kader_mitglied(db, mid)
    t = _termin(db, mid)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO termin_zusage (termin_id,mitglied_id,antwort,created_by,updated_by) "
                        "VALUES (%s,%s,'egal','t','t')", (t.id, mit))


def test_aktiver_unique_und_soft_delete_gibt_slot_frei(db):
    mid = _make_mannschaft(db)
    _uid, mit = _make_kader_mitglied(db, mid)
    t = _termin(db, mid)
    db.termin_zusagen.set_antwort(t.id, mit, 'zu', None, 'tester')
    # zweite AKTIVE Zeile für (termin, mitglied) verstößt gegen den partiellen Unique
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO termin_zusage (termin_id,mitglied_id,antwort,created_by,updated_by) "
                        "VALUES (%s,%s,'ab','t','t')", (t.id, mit))
    # nach Zurücknahme ist der Slot frei -> erneutes Setzen klappt, genau eine aktive Zeile
    assert db.termin_zusagen.remove_antwort(t.id, mit, 'tester')
    db.termin_zusagen.set_antwort(t.id, mit, 'vielleicht', None, 'tester')
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termin_zusage "
                    "WHERE termin_id=%s AND mitglied_id=%s AND deleted_at IS NULL", (t.id, mit))
        assert cur.fetchone()['n'] == 1
    assert db.termin_zusagen.answer_for(mit, [t.id]) == {t.id: 'vielleicht'}


# ------------------------------------------------------------------- Zähler/Lesen
def test_counts_und_answer_for(db):
    mid = _make_mannschaft(db)
    _u1, m1 = _make_kader_mitglied(db, mid, username="zusagetester1", nachname="Eins")
    _u2, m2 = _make_kader_mitglied(db, mid, username="zusagetester2", nachname="Zwei")
    _u3, m3 = _make_kader_mitglied(db, mid, username="zusagetester3", nachname="Drei")
    t = _termin(db, mid)
    andere = _termin(db, mid, beginn=f"{NEXTWEEK}T19:00")

    db.termin_zusagen.set_antwort(t.id, m1, 'zu', None, 't')
    db.termin_zusagen.set_antwort(t.id, m2, 'zu', None, 't')
    db.termin_zusagen.set_antwort(t.id, m3, 'ab', None, 't')

    counts = db.termin_zusagen.counts_for_termine([t.id, andere.id])
    assert counts[t.id] == {'zu': 2, 'vielleicht': 0, 'ab': 1}
    assert counts[andere.id] == {'zu': 0, 'vielleicht': 0, 'ab': 0}   # ohne Antworten: Nullen
    assert db.termin_zusagen.answer_for(m1, [t.id, andere.id]) == {t.id: 'zu'}
    assert db.termin_zusagen.counts_for_termine([]) == {}


def test_kader_mit_zusage_inklusive_offen(db):
    mid = _make_mannschaft(db)
    _u1, m1 = _make_kader_mitglied(db, mid, rolle="trainer", username="zusagetester1", nachname="Alpha")
    _u2, m2 = _make_kader_mitglied(db, mid, rolle="spieler", username="zusagetester2", nachname="Beta")
    _u3, m3 = _make_kader_mitglied(db, mid, rolle="spieler", username="zusagetester3", nachname="Gamma")
    # Mitglied außerhalb des Kaders zählt nicht mit
    _make_kader_mitglied(db, _make_mannschaft(db, name="Andere"), username="zusagetester9", nachname="Fremd")
    t = _termin(db, mid)
    db.termin_zusagen.set_antwort(t.id, m1, 'zu', None, 't')
    db.termin_zusagen.set_antwort(t.id, m2, 'ab', 'im Urlaub', 't')

    kader = db.termin_zusagen.list_kader_with_zusage(t.id)
    assert len(kader) == 3
    by_id = {k['mitglied_id']: k for k in kader}
    assert by_id[m1]['antwort'] == 'zu' and 'trainer' in by_id[m1]['rollen']
    assert by_id[m1]['kommentar'] is None
    assert by_id[m2]['antwort'] == 'ab' and by_id[m2]['kommentar'] == 'im Urlaub'
    assert by_id[m3]['antwort'] is None                       # offen
    assert by_id[m1]['name'] == 'Zusage Alpha'


# ------------------------------------------------------------------- ACL-Helfer
def test_get_kader_mitglied_id_und_stichtag(db):
    mid = _make_mannschaft(db)
    uid, mit = _make_kader_mitglied(db, mid, rolle="spieler")
    assert db.termine.get_kader_mitglied_id(uid, mid) == mit
    # abgelaufene Zugehörigkeit -> am heutigen Stichtag kein Kader-Mitglied
    abg_uid, _abg_mit = _make_kader_mitglied(db, mid, rolle="spieler", bis=YESTERDAY,
                                             username="zusagetester1", nachname="Weg")
    assert db.termine.get_kader_mitglied_id(abg_uid, mid) is None
    # fremde Mannschaft
    other = _make_mannschaft(db, name="Andere")
    assert db.termine.get_kader_mitglied_id(uid, other) is None


def test_is_mitglied_in_kader(db):
    mid = _make_mannschaft(db)
    _uid, mit = _make_kader_mitglied(db, mid, rolle="spieler")
    assert db.termine.is_mitglied_in_kader(mit, mid) is True
    # am Stichtag in der Zukunft (Zugehörigkeit erst ab morgen) nicht aktiv
    _uid2, mit2 = _make_kader_mitglied(db, mid, rolle="spieler", von=TOMORROW,
                                       username="zusagetester1", nachname="Kuenftig")
    assert db.termine.is_mitglied_in_kader(mit2, mid) is False
    assert db.termine.is_mitglied_in_kader(mit2, mid, stichtag=TOMORROW) is True
