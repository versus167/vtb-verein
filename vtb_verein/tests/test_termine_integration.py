"""Integrationstests der Mannschafts-Termine (#95, Spielbetrieb Etappe 1) gegen echtes PostgreSQL.

Prüft das Schema v68 (termine + History-Trigger + CHECKs + partieller extern_ref-Unique),
das Repository-CRUD (versions-gegatetes Update, set_status, Soft-Delete) und vor allem
die Kader-ACL „wer darf die Termine welcher Mannschaft?" inkl. der Aktiv-am-Stichtag-
Semantik (von/bis) und der Rollen-Stufen (spieler=lesen, betreuer/uebungsleiter
=verwalten).

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt – VereinsDB legt
das Schema beim Connect an. Beispiel:
    docker run -d --name vtb-pg-terminetest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=terminetest -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55433/terminetest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_termine_integration.py
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
    d = VereinsDB(_URL, upload_path="/tmp/vtb-termine-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        # Feature-Tabellen samt History leeren (RESTART IDENTITY, damit die
        # (id, version)-PKs der History nicht mit Alt-Läufen kollidieren).
        cur.execute(
            "TRUNCATE termine, termine_history, "
            "mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='Termin'")
        cur.execute("DELETE FROM users WHERE username LIKE 'termintester%'")
        cur.execute("DELETE FROM abteilung WHERE name='Termine-Abt'")
    yield


def _make_mannschaft(db, name="Erste", abteilung="Termine-Abt"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name=%s AND deleted_at IS NULL", (abteilung,))
        row = cur.fetchone()
        if row:
            aid = row['id']
        else:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES (%s,'t','t') RETURNING id", (abteilung,))
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_user_im_kader(db, mannschaft_id, rolle, von=LASTWEEK, bis=None,
                        username="termintester", mit_user=True):
    """User + Mitglied + Kader-Zuordnung. Gibt die user_id (bzw. None ohne User)."""
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                        "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                        (username, f"{username}@x.de"))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('Termin','Tester','lastschrift',%s,'t','t') RETURNING id", (uid,))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,bis,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'t','t')", (mid, mannschaft_id, rolle, von, bis))
    return uid


def _create_termin(db, mannschaft_id, beginn, typ='training', **kw):
    return db.termine.create(
        mannschaft_id, typ, beginn,
        kw.get('ende'), kw.get('ort'), kw.get('treffpunkt'), kw.get('treffpunkt_zeit'),
        kw.get('gegner'), kw.get('heim_auswaerts'), kw.get('beschreibung'), 't',
    )


# --------------------------------------------------------------- Schema/Trigger
def test_history_trigger_und_version_gating(db):
    mid = _make_mannschaft(db)
    t = _create_termin(db, mid, f"{TOMORROW}T19:00", ort="Halle 1")
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termine_history WHERE id=%s", (t.id,))
        assert cur.fetchone()["n"] == 1
    assert db.termine.update(t.id, 'training', f"{TOMORROW}T19:30", None, "Halle 2",
                             None, None, None, None, None, 't', t.version)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termine_history WHERE id=%s", (t.id,))
        assert cur.fetchone()["n"] == 2
    # Falsche Version: kein Update, keine neue History-Zeile
    assert not db.termine.update(t.id, 'training', f"{TOMORROW}T20:00", None, None,
                                 None, None, None, None, None, 't', t.version)
    assert db.termine.get(t.id).ort == "Halle 2"


def test_check_constraints(db):
    mid = _make_mannschaft(db)
    for typ, status, heim_auswaerts in (("party", "geplant", None),
                                        ("training", "vielleicht", None),
                                        ("training", "geplant", "mitte")):
        with pytest.raises(psycopg.errors.CheckViolation):
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO termine (mannschaft_id, typ, beginn, status, heim_auswaerts, "
                    "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, 't', 't')",
                    (mid, typ, f"{TOMORROW}T19:00", status, heim_auswaerts),
                )


def test_extern_ref_unique_nur_fuer_aktive(db):
    mid = _make_mannschaft(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,extern_ref,created_by,updated_by) "
                    "VALUES (%s,'spiel',%s,'DFB-123','t','t') RETURNING id",
                    (mid, f"{TOMORROW}T15:00"))
        erster = cur.fetchone()['id']
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,extern_ref,created_by,updated_by) "
                        "VALUES (%s,'spiel',%s,'DFB-123','t','t')", (mid, f"{NEXTWEEK}T15:00"))
    db.termine.mark_deleted(erster, 't')
    with db.cursor() as cur:  # nach Soft-Delete ist die Kennung wieder frei
        cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,extern_ref,created_by,updated_by) "
                    "VALUES (%s,'spiel',%s,'DFB-123','t','t')", (mid, f"{NEXTWEEK}T15:00"))


# ------------------------------------------------------------------- Repo-CRUD
def test_crud_sortierung_und_zeitraumfilter(db):
    mid = _make_mannschaft(db)
    spaet = _create_termin(db, mid, f"{NEXTWEEK}T19:00")
    frueh = _create_termin(db, mid, f"{TOMORROW}T19:00", typ='spiel',
                           gegner="SV Gegner", heim_auswaerts='heim')
    gestern = _create_termin(db, mid, f"{YESTERDAY}T19:00")

    alle = db.termine.list_for_mannschaft(mid)
    assert [t.id for t in alle] == [gestern.id, frueh.id, spaet.id]  # nach beginn sortiert

    ab_heute = db.termine.list_for_mannschaft(mid, von=date.today().isoformat())
    assert [t.id for t in ab_heute] == [frueh.id, spaet.id]
    # bis ist inklusiv (Datum trifft Termine des gesamten Tages)
    bis_morgen = db.termine.list_for_mannschaft(mid, bis=TOMORROW)
    assert [t.id for t in bis_morgen] == [gestern.id, frueh.id]

    assert frueh.gegner == "SV Gegner" and frueh.heim_auswaerts == 'heim'
    assert frueh.status == 'geplant'


def test_set_status_und_soft_delete(db):
    mid = _make_mannschaft(db)
    t = _create_termin(db, mid, f"{TOMORROW}T19:00")
    assert db.termine.set_status(t.id, 'abgesagt', 't', t.version)
    t2 = db.termine.get(t.id)
    assert t2.status == 'abgesagt' and t2.version == t.version + 1
    assert not db.termine.set_status(t.id, 'geplant', 't', t.version)  # veraltete Version
    assert db.termine.set_status(t.id, 'geplant', 't', t2.version)

    assert db.termine.mark_deleted(t.id, 't')
    assert db.termine.get(t.id) is None
    assert db.termine.list_for_mannschaft(mid) == []


# ------------------------------------------------------------------------- ACL
def test_acl_rollen_stufen(db):
    mid = _make_mannschaft(db)
    fall = (("spieler", 'lesen'),
            ("betreuer", 'verwalten'), ("uebungsleiter", 'verwalten'))
    for i, (rolle, erwartet) in enumerate(fall):
        uid = _make_user_im_kader(db, mid, rolle, username=f"termintester{i}")
        assert db.termine.get_access_for_user(uid, mid) == erwartet, rolle


def test_acl_stichtag_und_fremde(db):
    mid = _make_mannschaft(db)
    abgelaufen = _make_user_im_kader(db, mid, "uebungsleiter", bis=YESTERDAY, username="termintester1")
    zukunft = _make_user_im_kader(db, mid, "uebungsleiter", von=TOMORROW, username="termintester2")
    ohne_kader = _make_user_im_kader(db, _make_mannschaft(db, name="Andere"), "spieler",
                                     username="termintester3")
    assert db.termine.get_access_for_user(abgelaufen, mid) is None
    assert db.termine.get_access_for_user(zukunft, mid) is None
    assert db.termine.get_access_for_user(ohne_kader, mid) is None


def test_acl_doppelrolle_ergibt_hoechste_stufe(db):
    mid = _make_mannschaft(db)
    uid = _make_user_im_kader(db, mid, "spieler")
    with db.cursor() as cur:  # zweite Zuordnung: gleiche Person zusätzlich Übungsleiter
        cur.execute("SELECT mitglied_id FROM mitglied_mannschaft WHERE mannschaft_id=%s", (mid,))
        mitglied_id = cur.fetchone()['mitglied_id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,created_by,updated_by) "
                    "VALUES (%s,%s,'uebungsleiter',%s,'t','t')", (mitglied_id, mid, LASTWEEK))
    assert db.termine.get_access_for_user(uid, mid) == 'verwalten'
    teams = db.termine.list_mannschaften_for_user(uid)
    assert len(teams) == 1 and teams[0]['zugriff'] == 'verwalten'


def test_meine_termine_ueber_mehrere_teams(db):
    m1 = _make_mannschaft(db, name="Erste")
    m2 = _make_mannschaft(db, name="Zweite")
    uid = _make_user_im_kader(db, m1, "spieler")
    with db.cursor() as cur:  # gleiches Mitglied auch im Kader der Zweiten
        cur.execute("SELECT mitglied_id FROM mitglied_mannschaft WHERE mannschaft_id=%s", (m1,))
        mitglied_id = cur.fetchone()['mitglied_id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,created_by,updated_by) "
                    "VALUES (%s,%s,'uebungsleiter',%s,'t','t')", (mitglied_id, m2, LASTWEEK))
    t_gestern = _create_termin(db, m1, f"{YESTERDAY}T19:00")
    t1 = _create_termin(db, m2, f"{TOMORROW}T18:00")
    t2 = _create_termin(db, m1, f"{TOMORROW}T19:00")
    _create_termin(db, _make_mannschaft(db, name="Fremde"), f"{TOMORROW}T20:00")

    meine = db.termine.list_for_user(uid, von=date.today().isoformat())
    assert [t['id'] for t in meine] == [t1.id, t2.id]  # teamübergreifend nach beginn
    assert {t['mannschaft_name'] for t in meine} == {"Erste", "Zweite"}
    assert next(t for t in meine if t['id'] == t1.id)['zugriff'] == 'verwalten'
    assert next(t for t in meine if t['id'] == t2.id)['zugriff'] == 'lesen'

    alle = db.termine.list_for_user(uid)
    assert t_gestern.id in [t['id'] for t in alle]


def test_list_kader_user_ids(db):
    """Empfängerkreis für Benachrichtigungen: aktiver Kader mit Konto, Stichtag-genau."""
    mid = _make_mannschaft(db)
    u1 = _make_user_im_kader(db, mid, "spieler", username="termintester1")
    u2 = _make_user_im_kader(db, mid, "uebungsleiter", username="termintester2")
    _make_user_im_kader(db, mid, "spieler", mit_user=False)              # ohne Konto
    u_alt = _make_user_im_kader(db, mid, "spieler", bis=YESTERDAY,
                                username="termintester3")                # abgelaufen
    _make_user_im_kader(db, _make_mannschaft(db, name="Andere"), "spieler",
                        username="termintester4")                        # fremdes Team
    with db.cursor() as cur:  # Doppelrolle: u2 zusätzlich als betreuer → trotzdem einmal
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,created_by,updated_by) "
                    "VALUES ((SELECT m.id FROM mitglied m WHERE m.user_id=%s),%s,'betreuer',%s,'t','t')",
                    (u2, mid, LASTWEEK))
    assert sorted(db.termine.list_kader_user_ids(mid)) == sorted([u1, u2])
    # Am gestrigen Stichtag war auch das inzwischen ausgeschiedene Mitglied aktiv
    assert sorted(db.termine.list_kader_user_ids(mid, YESTERDAY)) == sorted([u1, u2, u_alt])


def test_mannschaften_listen(db):
    m1 = _make_mannschaft(db, name="Erste")
    _make_mannschaft(db, name="Zweite")
    uid = _make_user_im_kader(db, m1, "spieler")
    eigene = db.termine.list_mannschaften_for_user(uid)
    assert [m['name'] for m in eigene] == ["Erste"]
    assert eigene[0]['zugriff'] == 'lesen' and eigene[0]['abteilung_name'] == 'Termine-Abt'
    alle = db.termine.list_all_mannschaften()
    assert {m['name'] for m in alle} == {"Erste", "Zweite"}
    assert all(m['zugriff'] == 'verwalten' for m in alle)
