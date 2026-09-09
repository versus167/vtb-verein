"""Welcher Sync-Lauf ist fällig? (#61)

Die Entscheidung des Sync-Sidecars – ohne DB und ohne Uhr, beides kommt von außen.
Wichtig sind die Ränder: Was passiert ohne Merker, bei einer zurückgestellten Uhr und
bei einem unlesbaren Zeitstempel? In allen drei Fällen muss die Antwort „lauf" heißen,
denn ein ausgelassener Lauf heißt ausgelassene Alarme.
"""
from datetime import datetime, timedelta, timezone

from app.services.zutritt_takt import LOGS, VOLL, faelliger_lauf

JETZT = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _lauf(voll=None, logs=None, stunden=4, minuten=15):
    return faelliger_lauf(JETZT, letzter_voll_sync_at=voll, letzter_log_sync_at=logs,
                          sync_intervall_stunden=stunden, logs_intervall_minuten=minuten)


def _vor(**kwargs):
    return (JETZT - timedelta(**kwargs)).isoformat()


def test_ohne_merker_laeuft_der_volle_lauf():
    """Erster Tick nach dem Update: Es gibt noch keine Merker."""
    assert _lauf() == VOLL


def test_frische_merker_ergeben_nichts_zu_tun():
    assert _lauf(voll=_vor(hours=1), logs=_vor(minutes=2)) is None


def test_alter_log_merker_ergibt_den_log_lauf():
    assert _lauf(voll=_vor(hours=1), logs=_vor(minutes=20)) == LOGS


def test_der_volle_lauf_hat_vorrang():
    """Ist beides fällig, reicht der volle Lauf – er holt die Logs mit."""
    assert _lauf(voll=_vor(hours=5), logs=_vor(minutes=20)) == VOLL


def test_voller_lauf_auch_bei_frischem_log_merker():
    assert _lauf(voll=_vor(hours=5), logs=_vor(seconds=30)) == VOLL


def test_exakt_erreichtes_intervall_ist_faellig():
    """Sonst rutschte der Lauf bei jedem Tick um eine Tickbreite nach hinten."""
    assert _lauf(voll=_vor(hours=4), logs=_vor(seconds=1)) == VOLL
    assert _lauf(voll=_vor(minutes=1), logs=_vor(minutes=15)) == LOGS


def test_eingestellter_takt_wird_beachtet():
    """Sechs Stunden sind das Maximum – nach fünf ist noch nichts fällig."""
    assert _lauf(voll=_vor(hours=5), logs=_vor(minutes=2), stunden=6) is None
    assert _lauf(voll=_vor(hours=5), logs=_vor(minutes=2), stunden=4) == VOLL
    assert _lauf(voll=_vor(hours=1), logs=_vor(minutes=20), minuten=30) is None


def test_zeitstempel_ohne_zone_gilt_als_utc():
    """Ältere Zeilen können ohne Zone geschrieben worden sein."""
    ohne_zone = (JETZT - timedelta(minutes=2)).replace(tzinfo=None).isoformat()
    assert _lauf(voll=_vor(hours=1), logs=ohne_zone) is None


def test_unlesbarer_merker_gilt_als_nie():
    assert _lauf(voll="kaputt", logs=_vor(seconds=1)) == VOLL


def test_merker_aus_der_zukunft_blockiert_nicht():
    """Zurückgestellte Uhr: Ohne diese Regel stünde der Sync bis zum Einholen still."""
    morgen = (JETZT + timedelta(days=1)).isoformat()
    assert _lauf(voll=morgen, logs=morgen) == VOLL
    assert _lauf(voll=_vor(minutes=5), logs=morgen) == LOGS
