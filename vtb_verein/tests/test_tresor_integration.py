"""Integrationstests des Passwort-Tresors (#85) gegen echtes PostgreSQL.

Prüft das Schema v66 (Tabellen + History-Trigger), die verschlüsselte Ablage der Secrets
(BYTEA) und vor allem die ACL-Auflösung „welche Tresore darf ein User?" über Freigaben an
User / Abteilung / Funktion inkl. der Aktiv-am-Stichtag-Semantik (von/bis).

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt – VereinsDB legt
das Schema beim Connect an. Beispiel:
    docker run -d --name vtb-pg-tresortest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=tresortest -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55433/tresortest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_tresor_integration.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-tresor-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE tresor, tresor_history, tresor_freigabe, tresor_freigabe_history, "
            "tresor_eintrag, tresor_eintrag_history, tresor_kontakt, tresor_kontakt_history, "
            "tresor_zugriff_log RESTART IDENTITY CASCADE"
        )
        # Membership-Tabellen samt History leeren – andere Integrationstests machen
        # RESTART IDENTITY auf mitglied_funktion ohne die _history zu räumen, sonst
        # kollidiert unser Insert mit Alt-History (id, version).
        cur.execute(
            "TRUNCATE mitglied_funktion, mitglied_funktion_history, "
            "mitglied_abteilung, mitglied_abteilung_history RESTART IDENTITY"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='ACL'")
        cur.execute("DELETE FROM users WHERE username='acltester'")
        cur.execute("DELETE FROM funktion WHERE key='trainer'")
        cur.execute("DELETE FROM abteilung WHERE name='ACL-Abt'")
    yield


def _fernet_token(passwort: str, notiz: str = "") -> bytes:
    import json
    from cryptography.fernet import Fernet
    return Fernet(Fernet.generate_key()).encrypt(json.dumps({"passwort": passwort, "notiz": notiz}).encode())


def _make_user_with_membership(db):
    """User + Mitglied + aktive Abteilung + aktive Funktion 'trainer'. Gibt (uid, aid, fid)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                    "VALUES ('acltester','acl@x.de','x','mitglied',1,'t','t') RETURNING id")
        uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('ACL','Tester','lastschrift',%s,'t','t') RETURNING id", (uid,))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) VALUES ('ACL-Abt','t','t') RETURNING id")
        aid = cur.fetchone()['id']
        cur.execute("INSERT INTO funktion (key,name,created_by,updated_by) VALUES ('trainer','Trainer','t','t') RETURNING id")
        fid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,status,von,created_by,updated_by) "
                    "VALUES (%s,%s,'aktiv',%s,'t','t')", (mid, aid, LASTWEEK))
        cur.execute("INSERT INTO mitglied_funktion (mitglied_id,funktion,von,created_by,updated_by) "
                    "VALUES (%s,'trainer',%s,'t','t')", (mid, LASTWEEK))
    return uid, aid, fid, mid


def test_history_trigger_on_tresor(db):
    t = db.tresore.create("WLAN", "desc", "t")
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM tresor_history WHERE id=%s", (t.id,))
        assert cur.fetchone()["n"] == 1
    db.tresore.update(t.id, "WLAN neu", None, "t", t.version)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM tresor_history WHERE id=%s", (t.id,))
        assert cur.fetchone()["n"] == 2


def test_encrypted_payload_roundtrips_through_bytea(db):
    import json
    from cryptography.fernet import Fernet
    f = Fernet(Fernet.generate_key())
    t = db.tresore.create("T", None, "t")
    tok = f.encrypt(json.dumps({"passwort": "hunter2", "notiz": "n"}).encode())
    e = db.tresor_eintraege.create(t.id, "Router", "admin", "http://x", tok, "t")
    # Metadaten enthalten kein Secret
    assert not hasattr(e, "secret_ciphertext")
    ct = db.tresor_eintraege.get_ciphertext(e.id)
    assert json.loads(f.decrypt(bytes(ct)))["passwort"] == "hunter2"


def test_update_keeps_password_when_ciphertext_none(db):
    t = db.tresore.create("T", None, "t")
    e = db.tresor_eintraege.create(t.id, "X", None, None, _fernet_token("orig"), "t")
    before = db.tresor_eintraege.get_ciphertext(e.id)
    assert db.tresor_eintraege.update(e.id, "X2", None, None, None, "t", e.version)
    assert bytes(db.tresor_eintraege.get_ciphertext(e.id)) == bytes(before)


def test_acl_resolution_user_abteilung_funktion(db):
    uid, aid, fid, _ = _make_user_with_membership(db)
    t1 = db.tresore.create("T1", None, "t").id
    t2 = db.tresore.create("T2", None, "t").id
    t3 = db.tresore.create("T3", None, "t").id
    t4 = db.tresore.create("T4", None, "t").id
    db.tresor_freigaben.set_freigabe(t1, 'user', uid, 'read', 't')
    db.tresor_freigaben.set_freigabe(t2, 'abteilung', aid, 'write', 't')
    db.tresor_freigaben.set_freigabe(t3, 'funktion', fid, 'read', 't')

    vis = {v['id']: v for v in db.tresore.list_for_user(uid)}
    assert set(vis) == {t1, t2, t3}
    assert vis[t2]['darf_schreiben'] is True
    assert vis[t1]['darf_schreiben'] is False
    assert t4 not in vis
    assert db.tresore.get_access_for_user(uid, t2) == 'write'
    assert db.tresore.get_access_for_user(uid, t1) == 'read'
    assert db.tresore.get_access_for_user(uid, t4) is None


def test_expired_membership_revokes_access(db):
    uid, aid, fid, mid = _make_user_with_membership(db)
    t3 = db.tresore.create("T3", None, "t").id
    db.tresor_freigaben.set_freigabe(t3, 'funktion', fid, 'read', 't')
    assert db.tresore.get_access_for_user(uid, t3) == 'read'
    with db.cursor() as cur:
        cur.execute("UPDATE mitglied_funktion SET bis=%s WHERE mitglied_id=%s", (YESTERDAY, mid))
    assert db.tresore.get_access_for_user(uid, t3) is None


def test_revoke_user_freigabe_keeps_group_freigabe(db):
    uid, aid, fid, _ = _make_user_with_membership(db)
    t1 = db.tresore.create("T1", None, "t").id
    t2 = db.tresore.create("T2", None, "t").id
    db.tresor_freigaben.set_freigabe(t1, 'user', uid, 'read', 't')
    db.tresor_freigaben.set_freigabe(t2, 'abteilung', aid, 'read', 't')
    assert db.tresor_freigaben.revoke_alle_freigaben_fuer_user(uid, 't') == 1
    rest = {v['id'] for v in db.tresore.list_for_user(uid)}
    assert t1 not in rest and t2 in rest


def test_history_lists_versions_and_old_ciphertext(db):
    import json
    from cryptography.fernet import Fernet
    f = Fernet(Fernet.generate_key())
    t = db.tresore.create("T", None, "t")
    e = db.tresor_eintraege.create(
        t.id, "Router", "admin", None,
        f.encrypt(json.dumps({"passwort": "orig", "notiz": ""}).encode()), "t")
    # Passwort ändern -> Version 2 (anderer Bearbeiter)
    db.tresor_eintraege.update(
        e.id, "Router", "admin", None,
        f.encrypt(json.dumps({"passwort": "neu", "notiz": ""}).encode()), "t2", e.version)
    hist = db.tresor_eintraege.list_history(e.id)
    assert [h["version"] for h in hist] == [2, 1]          # neueste zuerst
    assert "secret_ciphertext" not in hist[0]              # Metadaten ohne Secret
    assert hist[0]["updated_by"] == "t2" and hist[1]["updated_by"] == "t"
    # der alte Ciphertext (v1) lässt sich noch entschlüsseln -> "orig"
    ct_v1 = db.tresor_eintraege.get_history_ciphertext(e.id, 1)
    assert json.loads(f.decrypt(bytes(ct_v1)))["passwort"] == "orig"
    assert db.tresor_eintraege.get_history_ciphertext(e.id, 99) is None


def test_restore_old_password_creates_new_version(db):
    import json
    from cryptography.fernet import Fernet
    f = Fernet(Fernet.generate_key())
    t = db.tresore.create("T", None, "t")
    e = db.tresor_eintraege.create(
        t.id, "X", None, None,
        f.encrypt(json.dumps({"passwort": "orig", "notiz": ""}).encode()), "t")
    db.tresor_eintraege.update(
        e.id, "X", None, None,
        f.encrypt(json.dumps({"passwort": "neu", "notiz": ""}).encode()), "t", e.version)
    cur = db.tresor_eintraege.get(e.id)
    assert cur.version == 2
    assert json.loads(f.decrypt(bytes(db.tresor_eintraege.get_ciphertext(e.id))))["passwort"] == "neu"
    # Wiederherstellen von v1: alten Ciphertext als neue Version übernehmen (wie die API)
    ct_v1 = db.tresor_eintraege.get_history_ciphertext(e.id, 1)
    assert db.tresor_eintraege.update(e.id, cur.titel, cur.benutzername, cur.url, ct_v1, "restorer", cur.version)
    after = db.tresor_eintraege.get(e.id)
    assert after.version == 3
    assert json.loads(f.decrypt(bytes(db.tresor_eintraege.get_ciphertext(e.id))))["passwort"] == "orig"
    assert [h["version"] for h in db.tresor_eintraege.list_history(e.id)] == [3, 2, 1]


def test_kontakt_crud_and_history_trigger(db):
    """Tresor-Kontakte (#106): CRUD, Soft-Delete und History-Trigger (v73)."""
    t = db.tresore.create("T", None, "t")
    k = db.tresor_kontakte.create(
        t.id, "Heizung Notdienst", "Herr Meier", "0371 123456",
        "notdienst@heizung.de", "24h erreichbar", "t")
    assert k.name == "Heizung Notdienst" and k.telefon == "0371 123456"
    assert [x.id for x in db.tresor_kontakte.list_for_tresor(t.id)] == [k.id]

    # Kontaktzähler in der Tresor-Liste (#113)
    zeile = next(v for v in db.tresore.list_all() if v['id'] == t.id)
    assert zeile['kontakt_anzahl'] == 1 and zeile['eintrag_anzahl'] == 0

    # Update bumpt Version, History-Trigger schreibt mit
    assert db.tresor_kontakte.update(
        k.id, "Heizung Notdienst", "Frau Schulze", "0371 654321", None, None, "t2", k.version)
    after = db.tresor_kontakte.get(k.id)
    assert after.version == 2 and after.ansprechpartner == "Frau Schulze"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM tresor_kontakt_history WHERE id=%s", (k.id,))
        assert cur.fetchone()["n"] == 2

    # Optimistic Locking: veraltete Version schreibt nicht
    assert not db.tresor_kontakte.update(k.id, "X", None, None, None, None, "t", 1)

    # Soft-Delete: verschwindet aus Liste/Get, Zeile bleibt (deleted_at gesetzt)
    assert db.tresor_kontakte.mark_deleted(k.id, "t")
    assert db.tresor_kontakte.get(k.id) is None
    assert db.tresor_kontakte.list_for_tresor(t.id) == []
    # Soft-gelöschte Kontakte zählen nicht mehr mit (#113)
    assert next(v for v in db.tresore.list_all() if v['id'] == t.id)['kontakt_anzahl'] == 0
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM tresor_kontakt WHERE id=%s", (k.id,))
        assert cur.fetchone()["deleted_at"] is not None


def test_zugriff_log_append(db):
    t = db.tresore.create("T", None, "t")
    e = db.tresor_eintraege.create(t.id, "X", None, None, _fernet_token("p"), "t")
    db.tresor_zugriff_log.log(tresor_id=t.id, eintrag_id=e.id, eintrag_titel="X",
                              user_id=None, username="acltester", aktion="reveal", ip="127.0.0.1")
    logs = db.tresor_zugriff_log.list_recent(limit=10, tresor_id=t.id)
    assert len(logs) == 1 and logs[0].aktion == "reveal"
