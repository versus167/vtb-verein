"""Das Startpasswort des Erst-Admins ist kein bekannter Wert mehr.

Bis hierher legte ``_seed_data`` den Admin mit einem fest verdrahteten
'admin123' an — einem Passwort, das in jeder öffentlichen Kopie des Quellcodes
steht. Jede frisch aufgesetzte Instanz war damit übernehmbar, bis jemand daran
dachte, es zu wechseln; die Anmelde-Bremse greift dagegen nicht, weil das
Passwort ja stimmt.

Geprüft wird deshalb das, was sich nur am echten Frischaufbau zeigt:

* Der Seed-Admin lässt sich **nicht** mit 'admin123' anmelden.
* Ohne Env ist das Passwort ein Zufallswert — zwei frische Datenbanken bekommen
  verschiedene Hashes (ein fester Wert fiele hier auf, auch wenn er nicht
  'admin123' hieße).
* ``VTB_ADMIN_INITIAL_PASSWORT`` wird respektiert, wenn gesetzt.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB, Muster wie
test_kalender_abo_integration).
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


def _frische_db(name: str):
    """Legt eine leere Datenbank neben der Test-DB an und baut das Schema auf.

    Der Seed läuft nur beim Frischaufbau, also braucht jeder Fall hier seine
    eigene Datenbank — eine einmal geseedete lässt sich nicht noch einmal seeden.
    """
    import psycopg
    from app.db.datastore import VereinsDB

    teile = urlsplit(_URL)
    verwaltung = urlunsplit((*teile[:2], "/postgres", "", ""))
    with psycopg.connect(verwaltung, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    ziel = urlunsplit((*teile[:2], f"/{name}", "", ""))
    return VereinsDB(ziel, upload_path="/tmp/vtb-erstadmin-uploads")


def _admin_hash(db) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE username = 'admin'")
        return cur.fetchone()["password_hash"]


@pytest.fixture
def ohne_env(monkeypatch):
    monkeypatch.delenv("VTB_ADMIN_INITIAL_PASSWORT", raising=False)


def test_seed_admin_nicht_mit_admin123(ohne_env):
    """Das alte Standardpasswort öffnet den Erst-Admin nicht mehr."""
    import bcrypt
    db = _frische_db("sec_seed_a")
    try:
        hash_ = _admin_hash(db)
        assert not bcrypt.checkpw(b"admin123", hash_.encode())
    finally:
        db.close()


def test_startpasswort_ist_zufaellig(ohne_env):
    """Zwei frische Datenbanken bekommen verschiedene Passwörter.

    Bcrypt salzt, also unterscheiden sich die Hashes ohnehin — verglichen wird
    deshalb über checkpw kreuzweise: Das Passwort der einen DB darf den Admin
    der anderen nicht öffnen.
    """
    import bcrypt
    db_a = _frische_db("sec_seed_b")
    db_b = _frische_db("sec_seed_c")
    try:
        hash_a, hash_b = _admin_hash(db_a), _admin_hash(db_b)
        assert hash_a != hash_b
        # Ein fest verdrahteter Wert (welcher auch immer) würde hier passen.
        assert not bcrypt.checkpw(b"admin123", hash_b.encode())
    finally:
        db_a.close()
        db_b.close()


def test_env_passwort_wird_genommen(monkeypatch):
    """Wer VTB_ADMIN_INITIAL_PASSWORT setzt, bekommt genau dieses Passwort."""
    import bcrypt
    monkeypatch.setenv("VTB_ADMIN_INITIAL_PASSWORT", "start-geheim-2026")
    db = _frische_db("sec_seed_d")
    try:
        assert bcrypt.checkpw(b"start-geheim-2026", _admin_hash(db).encode())
    finally:
        db.close()


def test_zu_langes_env_passwort_bricht_verstaendlich_ab(monkeypatch):
    """Über 72 Byte wirft bcrypt – der Abbruch muss die Ursache nennen.

    Ohne diese Prüfung stürbe der Schema-Aufbau an einer bcrypt-Meldung, die
    nicht verrät, dass eine Env-Variable schuld ist.
    """
    monkeypatch.setenv("VTB_ADMIN_INITIAL_PASSWORT", "x" * 73)
    with pytest.raises(ValueError, match="VTB_ADMIN_INITIAL_PASSWORT"):
        _frische_db("sec_seed_e")
