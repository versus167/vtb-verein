"""Login-Code zum Login-Link (Ticket #208) gegen echtes PostgreSQL.

Die installierte App am Handy bekommt den Link aus der Mail nicht ab — der öffnet
den Browser, dessen Cookie die App nicht sieht. Deshalb trägt dieselbe Mail einen
6-stelligen Code. Was sich nur an einer echten DB zeigt und hier festgehalten ist:

* Link und Code hängen an **einer** Zeile: Wer eins einlöst, verbraucht beides.
* Die Versuchsgrenze hält auch über mehrere Aufrufe (Zähler in der DB, nicht im
  Prozess).
* Nur der jüngste Link zählt, abgelaufene Codes greifen nicht.
* Fresh == Migriert: v125 legt die Spalten auf einer Bestands-DB nach.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MAX = 5


def _hash(code):
    # Im Backend ein HMAC mit dem Server-Geheimnis; für das Repository zählt nur,
    # dass Anlage und Einlösung dieselbe Funktion nutzen.
    return f"h:{code}"


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-logincode-uploads")
    yield d
    d.close()


@pytest.fixture
def user_id(db):
    name = f"code{uuid.uuid4().hex[:8]}"
    return db.create_user(name, f"{name}@example.org", "", "mitglied", "tester").id


def _anlegen(db, user_id, **kw):
    return db.auth_token_repository.create_magic_link_mit_code(user_id, _hash, **kw)


def _einloesen(db, user_id, code):
    return db.auth_token_repository.loese_code_ein(user_id, _hash(code), MAX)


def _falscher(code):
    return f"{(int(code) + 1) % 10 ** 6:06d}"


def test_code_ist_sechsstellig(db, user_id):
    _, code = _anlegen(db, user_id)
    assert len(code) == 6 and code.isdigit()


def test_richtiger_code_meldet_an(db, user_id):
    _, code = _anlegen(db, user_id)
    assert _einloesen(db, user_id, code)


def test_code_verbraucht_den_link(db, user_id):
    """Die Frage aus dem Ticket: Eine Mail = eine Anmeldung, egal auf welchem Weg."""
    token, code = _anlegen(db, user_id)
    assert _einloesen(db, user_id, code)
    assert db.auth_token_repository.validate_and_use_token(token) is None


def test_link_verbraucht_den_code(db, user_id):
    token, code = _anlegen(db, user_id)
    assert db.auth_token_repository.validate_and_use_token(token)
    assert not _einloesen(db, user_id, code)


def test_code_nur_einmal(db, user_id):
    _, code = _anlegen(db, user_id)
    assert _einloesen(db, user_id, code)
    assert not _einloesen(db, user_id, code)


def test_nach_fuenf_fehlversuchen_ist_schluss(db, user_id):
    """Auch der richtige Code hilft danach nicht mehr — sonst wäre die Grenze
    nur eine Verzögerung."""
    _, code = _anlegen(db, user_id)
    for _ in range(MAX):
        assert not _einloesen(db, user_id, _falscher(code))
    assert not _einloesen(db, user_id, code)


def test_vierter_fehlversuch_laesst_den_richtigen_noch_durch(db, user_id):
    _, code = _anlegen(db, user_id)
    for _ in range(MAX - 1):
        assert not _einloesen(db, user_id, _falscher(code))
    assert _einloesen(db, user_id, code)


def test_gesperrter_code_laesst_den_link_leben(db, user_id):
    """Das Raten am Code sperrt nur den Code — wer die Mail hat, kommt über den
    Link weiterhin hinein."""
    token, code = _anlegen(db, user_id)
    for _ in range(MAX):
        _einloesen(db, user_id, _falscher(code))
    assert db.auth_token_repository.validate_and_use_token(token)


def test_abgelaufener_code_greift_nicht(db, user_id):
    token, code = _anlegen(db, user_id, code_minuten=-1)
    assert not _einloesen(db, user_id, code)
    # Der Link lebt 7 Tage, unabhängig vom Code.
    assert db.auth_token_repository.validate_and_use_token(token)


def test_nur_der_juengste_link_zaehlt(db, user_id):
    """Sonst vervielfachte jede weitere Anforderung die erlaubten Rateversuche."""
    _, alt = _anlegen(db, user_id)
    _, neu = _anlegen(db, user_id)
    if alt == neu:  # 1 : 10^6 – dann sagt der Test nichts aus
        pytest.skip("zufällig gleicher Code")
    assert not _einloesen(db, user_id, alt)
    assert _einloesen(db, user_id, neu)


def test_code_gilt_nur_fuer_sein_konto(db, user_id):
    _, code = _anlegen(db, user_id)
    fremd = db.create_user(f"frd{uuid.uuid4().hex[:8]}", None, "", "mitglied", "tester").id
    assert not _einloesen(db, fremd, code)
    assert _einloesen(db, user_id, code)


def test_links_ohne_code_bleiben_unberuehrt(db, user_id):
    """Einladungs-Mails (EmailService.send_magic_link) legen Links ohne Code an –
    die dürfen weder als Code einlösbar sein noch den Code-Pfad stören."""
    token = db.auth_token_repository.create_token(user_id, "magic_link")
    assert not _einloesen(db, user_id, "000000")
    assert db.auth_token_repository.validate_and_use_token(token)


def test_migration_legt_spalten_nach(db, user_id):
    """Zustand vor v125 herstellen (Spalten fort), migrieren, einlösen."""
    with db.cursor() as cur:
        for spalte in ("code_hash", "code_expires_at", "code_versuche"):
            cur.execute(f"ALTER TABLE auth_tokens DROP COLUMN {spalte}")
    db._database._migrate_v124_to_v125()
    _, code = _anlegen(db, user_id)
    assert _einloesen(db, user_id, code)


def test_history_bleibt_ohne_code(db, user_id):
    """Der Code-Hash hat in der dauerhaft aufbewahrten Historie nichts zu suchen."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'auth_tokens_history' AND column_name LIKE 'code%%'"
        )
        assert cur.fetchall() == []
