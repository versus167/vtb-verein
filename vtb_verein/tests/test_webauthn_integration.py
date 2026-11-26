"""Passkeys (WebAuthn) gegen echtes PostgreSQL (Schema v126).

Geprüft wird, was sich nur an einer echten DB zeigt: Fresh == Migriert, dass eine
Challenge genau einmal und nur für ihren Zweck/ihr Konto einlösbar ist, dass nur ihr
Hash in der DB liegt, dass Widerruf soft und historisiert ist, eine Anmeldung aber
keine History schreibt – und dass die Prune-Regeln ausführbares SQL ergeben und die
richtigen Zeilen treffen.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import secrets
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-webauthn-uploads")
    yield d
    d.close()


def _neuer_user(db) -> int:
    name = f"passkeytester_{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                    "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                    (name, f"{name}@example.de"))
        return cur.fetchone()['id']


@pytest.fixture
def user_id(db):
    return _neuer_user(db)


def _cred(db, user_id, **kw):
    werte = dict(credential_id=secrets.token_urlsafe(16), public_key=b"\x01\x02",
                 sign_count=0, transports=["internal", "hybrid"], aaguid=None,
                 backed_up=True,
                 user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1")
    werte.update(kw)
    return db.webauthn.anlegen(user_id, **werte)


# ------------------------------------------------------------------- Struktur

def _struktur(db):
    with db.cursor() as cur:
        cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_name IN ('webauthn_credential','webauthn_credential_history',"
                    "'webauthn_challenge') ORDER BY 1, 2")
        spalten = [tuple(r.values()) for r in cur.fetchall()]
        cur.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'webauthn_credential'::regclass "
                    "AND NOT tgisinternal ORDER BY tgname")
        trigger = [r['tgname'] for r in cur.fetchall()]
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename LIKE 'webauthn%%' "
                    "ORDER BY indexname")
        indexe = [r['indexname'] for r in cur.fetchall()]
    return spalten, trigger, indexe


def test_migration_baut_dieselbe_struktur_wie_der_frischaufbau(db):
    vorher = _struktur(db)
    assert vorher[1] == ['trig_webauthn_credential_audit_insert',
                         'trig_webauthn_credential_audit_update']
    with db.cursor() as cur:
        cur.execute("DROP TABLE webauthn_credential_history, webauthn_credential, "
                    "webauthn_challenge CASCADE")
    db._database._migrate_v125_to_v126()
    assert _struktur(db) == vorher


def test_migration_ist_idempotent(db):
    db._database._migrate_v125_to_v126()
    db._database._migrate_v125_to_v126()


def test_created_at_ist_timestamptz(db):
    spalten = {(t, c): typ for t, c, typ in _struktur(db)[0]}
    assert spalten[('webauthn_credential', 'created_at')] == 'timestamp with time zone'
    assert spalten[('webauthn_credential', 'revoked_at')] == 'timestamp with time zone'


# ----------------------------------------------------------------- Challenges

def _bis():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def test_challenge_nur_als_hash_gespeichert(db):
    ch = secrets.token_bytes(32)
    assert db.webauthn.challenge_verbrauchen(ch, 'login', None, _bis()) is True
    with db.cursor() as cur:
        cur.execute("SELECT challenge_hash, used_at FROM webauthn_challenge ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    assert ch.hex() not in row['challenge_hash'] and len(row['challenge_hash']) == 64
    assert row['used_at'] is not None


def test_challenge_genau_einmal_einloesbar(db, user_id):
    ch = secrets.token_bytes(32)
    assert db.webauthn.challenge_verbrauchen(ch, 'register', user_id, _bis()) is True
    assert db.webauthn.challenge_verbrauchen(ch, 'register', user_id, _bis()) is False
    # auch nicht unter anderem Zweck/Konto – verbraucht ist verbraucht
    assert db.webauthn.challenge_verbrauchen(ch, 'login', None, _bis()) is False


# ---------------------------------------------------------------- Credentials

def test_anlegen_und_finden(db, user_id):
    c = _cred(db, user_id)
    assert c['geraet_label'] and c['transports'] == 'internal,hybrid'
    gefunden = db.webauthn.aktiv_nach_credential_id(c['credential_id'])
    assert gefunden['user_id'] == user_id and bytes(gefunden['public_key']) == b"\x01\x02"
    assert db.webauthn.credential_ids_for_user(user_id) == [c['credential_id']]


def test_liste_liefert_keinen_schluessel(db, user_id):
    _cred(db, user_id)
    assert 'public_key' not in db.webauthn.list_active_for_user(user_id)[0]


def test_login_fuehrt_zaehler_ohne_history(db, user_id):
    c = _cred(db, user_id)
    db.webauthn.nach_login(c['id'], 7, False)
    with db.cursor() as cur:
        cur.execute("SELECT sign_count, backed_up, last_used_at, version "
                    "FROM webauthn_credential WHERE id = %s", (c['id'],))
        row = cur.fetchone()
        cur.execute("SELECT count(*) n FROM webauthn_credential_history WHERE id = %s", (c['id'],))
        n = cur.fetchone()['n']
    assert (row['sign_count'], row['backed_up'], row['version']) == (7, False, 1)
    assert row['last_used_at'] is not None
    assert n == 1  # nur die Anlage


def test_umbenennen_nur_eigene(db, user_id):
    c = _cred(db, user_id)
    assert db.webauthn.umbenennen(c['id'], _neuer_user(db), 'fremd') is False
    assert db.webauthn.umbenennen(c['id'], user_id, 'Mein iPhone') is True
    assert db.webauthn.list_active_for_user(user_id)[0]['geraet_label'] == 'Mein iPhone'


def test_widerruf_soft_und_historisiert(db, user_id):
    c = _cred(db, user_id)
    assert db.webauthn.widerrufen(c['id'], _neuer_user(db), 'x') is False
    assert db.webauthn.widerrufen(c['id'], user_id, 'tester') is True
    assert db.webauthn.widerrufen(c['id'], user_id, 'tester') is False
    assert db.webauthn.aktiv_nach_credential_id(c['credential_id']) is None
    assert db.webauthn.list_active_for_user(user_id) == []
    with db.cursor() as cur:
        cur.execute("SELECT revoked_by, version FROM webauthn_credential WHERE id = %s", (c['id'],))
        row = cur.fetchone()
        cur.execute("SELECT version FROM webauthn_credential_history WHERE id = %s "
                    "ORDER BY version", (c['id'],))
        versionen = [r['version'] for r in cur.fetchall()]
    assert row['revoked_by'] == 'tester' and versionen == [1, 2]


def test_credential_id_eindeutig(db, user_id):
    import psycopg
    c = _cred(db, user_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _cred(db, user_id, credential_id=c['credential_id'])


# ---------------------------------------------------------------------- Prune

def test_prune_registry_kennt_die_tabellen():
    from app.services.prune_service import LOG_BY_NAME, PRUNE_REGISTRY
    assert {'webauthn_credential', 'webauthn_credential_history',
            'webauthn_challenge'} <= set(LOG_BY_NAME)
    user = next(e for e in PRUNE_REGISTRY if e.name == 'user')
    kinder = {(c.table, c.fk) for c in user.children}
    assert {('webauthn_credential', 'user_id'), ('webauthn_challenge', 'user_id')} <= kinder


def _faellig(db, regel, tage=0):
    from app.services.prune_service import LOG_BY_NAME, build_log_due_count_sql
    rule = LOG_BY_NAME[regel]
    with db.cursor() as cur:
        cur.execute(build_log_due_count_sql(rule), (tage,))
        return cur.fetchone()['n']


def test_prune_trifft_widerrufene_und_ihre_ganze_history(db, user_id):
    aktiv = _cred(db, user_id)
    weg = _cred(db, user_id)
    db.webauthn.umbenennen(weg['id'], user_id, 'altes Handy')
    db.webauthn.widerrufen(weg['id'], user_id, 'tester')
    with db.cursor() as cur:
        cur.execute("UPDATE webauthn_credential SET revoked_at = now() - interval '400 days' "
                    "WHERE id = %s", (weg['id'],))
        cur.execute("UPDATE webauthn_credential_history SET revoked_at = now() - interval '400 days' "
                    "WHERE id = %s AND revoked_at IS NOT NULL", (weg['id'],))
        cur.execute("SELECT id FROM webauthn_credential WHERE "
                    "NULLIF((revoked_at)::text, '')::timestamptz < now() - make_interval(days => 365)")
        haupt = {r['id'] for r in cur.fetchall()}
    assert weg['id'] in haupt and aktiv['id'] not in haupt

    from app.services.prune_service import LOG_BY_NAME, build_log_delete_sql
    with db.cursor() as cur:
        cur.execute(build_log_delete_sql(LOG_BY_NAME['webauthn_credential_history']), (365,))
        cur.execute("SELECT id, count(*) n FROM webauthn_credential_history "
                    "WHERE id IN (%s, %s) GROUP BY id", (weg['id'], aktiv['id']))
        rest = {r['id']: r['n'] for r in cur.fetchall()}
    assert weg['id'] not in rest          # alle drei Versionen (Anlage, Umbenennen, Widerruf)
    assert rest[aktiv['id']] == 1         # aktive bleiben


def test_prune_sql_aller_regeln_laeuft(db):
    for regel in ('webauthn_credential', 'webauthn_credential_history', 'webauthn_challenge'):
        assert _faellig(db, regel, 30) >= 0


def test_prune_trifft_verbrauchte_challenges(db):
    vorher = _faellig(db, 'webauthn_challenge')
    db.webauthn.challenge_verbrauchen(secrets.token_bytes(32), 'login', None, _bis())
    assert _faellig(db, 'webauthn_challenge') == vorher + 1
    assert _faellig(db, 'webauthn_challenge', 30) < vorher + 1
