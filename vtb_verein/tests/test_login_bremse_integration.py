"""Zählung der Anmelde-Fehlversuche gegen echtes PostgreSQL.

Die Bremse selbst ist in test_login_bremse_api mit Stubs geprüft. Hier geht es um
das, was sich nur an einer echten DB zeigt: dass die SQL wirklich **exakt** nach
dem Benutzernamen vergleicht und nicht als Teilstring wie der Protokollfilter.
Genau daran hängt, ob ein Angreifer fremde Konten aussperren kann, ohne sie
anzutippen — ein Stub kann diesen Unterschied nicht beweisen.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB, Muster wie
test_kalender_abo_integration).
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
    d = VereinsDB(_URL, upload_path="/tmp/vtb-loginbremse-uploads")
    yield d
    d.close()


@pytest.fixture
def namen():
    """Frisches Namenspaar je Test, bei dem einer im anderen enthalten ist."""
    kurz = f"max{uuid.uuid4().hex[:6]}"
    return kurz, kurz + "imilian"


def _schreibe_fehlversuche(db, username, anzahl, *, ip="198.51.100.7", vor_minuten=1):
    ts = datetime.now(timezone.utc) - timedelta(minutes=vor_minuten)
    with db.cursor() as cur:
        for _ in range(anzahl):
            cur.execute(
                "INSERT INTO access_log (event_type, category, username, ip, created_at) "
                "VALUES ('login_failed', 'auth', %s, %s, %s)",
                (username, ip, ts),
            )


def _fenster(minuten=15):
    return (datetime.now(timezone.utc) - timedelta(minutes=minuten)).isoformat()


def test_teiltreffer_zaehlt_nicht_auf_das_kuerzere_konto(db, namen):
    """Der sicherheitskritische Unterschied zum Protokollfilter."""
    kurz, lang = namen
    _schreibe_fehlversuche(db, lang, 5)
    assert db.access_log_repository.count_login_failures(
        since=_fenster(), username=kurz) == 0
    assert db.access_log_repository.count_login_failures(
        since=_fenster(), username=lang) == 5


def test_protokollfilter_wuerde_hier_falsch_zaehlen(db, namen):
    """Gegenprobe, die den Grund für die eigene Methode festhält: Der bequeme
    Filter aus count() liefert für denselben Fall einen Treffer — wer die Bremse
    darauf aufsetzt, baut die Aussperr-Waffe gleich mit ein."""
    kurz, lang = namen
    _schreibe_fehlversuche(db, lang, 3)
    assert db.access_log_repository.count(
        event_type="login_failed", username=kurz, since=_fenster()) == 3


def test_gross_klein_und_leerzeichen_treffen_dasselbe_konto(db, namen):
    kurz, _ = namen
    _schreibe_fehlversuche(db, f"  {kurz.upper()}  ", 4)
    assert db.access_log_repository.count_login_failures(
        since=_fenster(), username=kurz) == 4


def test_alte_eintraege_fallen_aus_dem_fenster(db, namen):
    kurz, _ = namen
    _schreibe_fehlversuche(db, kurz, 6, vor_minuten=120)
    assert db.access_log_repository.count_login_failures(
        since=_fenster(15), username=kurz) == 0
    assert db.access_log_repository.count_login_failures(
        since=_fenster(240), username=kurz) == 6


def test_ip_zaehlung_geht_ueber_konten_hinweg(db, namen):
    kurz, lang = namen
    eigene_ip = f"203.0.113.{uuid.uuid4().int % 200 + 10}"
    _schreibe_fehlversuche(db, kurz, 2, ip=eigene_ip)
    _schreibe_fehlversuche(db, lang, 3, ip=eigene_ip)
    assert db.access_log_repository.count_login_failures(
        since=_fenster(), ip=eigene_ip) == 5


def test_letzter_erfolg_wird_gefunden_und_grenzt_ab(db, namen):
    """Setzt die Zählung zurück: Fehlversuche *vor* dem Erfolg zählen nicht mehr."""
    kurz, _ = namen
    _schreibe_fehlversuche(db, kurz, 4, vor_minuten=10)
    erfolg_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO access_log (event_type, category, username, ip, created_at) "
            "VALUES ('login_success', 'auth', %s, '198.51.100.7', %s)",
            (kurz, erfolg_ts),
        )
    _schreibe_fehlversuche(db, kurz, 2, vor_minuten=1)

    letzter = db.access_log_repository.last_login_success_at(kurz)
    assert letzter is not None
    seit = max(_fenster(15), letzter)
    assert db.access_log_repository.count_login_failures(
        since=seit, username=kurz) == 2


def test_ohne_erfolg_gibt_es_keinen_zeitpunkt(db, namen):
    kurz, _ = namen
    assert db.access_log_repository.last_login_success_at(kurz) is None
