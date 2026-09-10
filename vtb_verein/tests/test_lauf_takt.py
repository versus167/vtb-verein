"""Ist ein Sidecar-Lauf fällig? — die Entscheidung ohne DB und ohne Uhr.

Wichtig sind die Ränder: kein Merker (erster Lauf nach dem Update), ein Merker aus
der Zukunft (zurückgestellte Uhr) und ein unlesbarer Wert. In allen drei Fällen muss
die Antwort „lauf" heißen — eine ausgelassene Erinnerung ist teurer als eine, die
einmal zu früh kommt.

Dazu die Toleranz: Ein Sidecar tickt in festen Abständen, und ohne sie schöbe sich
ein 24-Stunden-Lauf mit jedem Tag um eine Tick-Länge nach hinten.
"""
from datetime import datetime, timedelta, timezone

from app.services.lauf_takt import ist_faellig

JETZT = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)
TAG = timedelta(hours=24)


def _vor(**kwargs) -> str:
    return (JETZT - timedelta(**kwargs)).isoformat()


def test_ohne_merker_ist_faellig():
    assert ist_faellig(None, JETZT, TAG) is True


def test_frischer_merker_ist_nicht_faellig():
    assert ist_faellig(_vor(hours=2), JETZT, TAG) is False


def test_nach_dem_intervall_ist_faellig():
    assert ist_faellig(_vor(hours=24), JETZT, TAG) is True


def test_merker_als_datetime_wird_auch_verstanden():
    """psycopg liefert TIMESTAMPTZ als datetime, nicht als ISO-String."""
    assert ist_faellig(JETZT - timedelta(hours=25), JETZT, TAG) is True
    assert ist_faellig(JETZT - timedelta(hours=1), JETZT, TAG) is False


def test_naiver_merker_gilt_als_utc():
    """Ältere Zeilen können ohne Zone geschrieben worden sein — das darf nicht
    in einen TypeError laufen."""
    naiv = (JETZT - timedelta(hours=25)).replace(tzinfo=None)
    assert ist_faellig(naiv, JETZT, TAG) is True


def test_unlesbarer_merker_laesst_laufen():
    assert ist_faellig("kein Zeitstempel", JETZT, TAG) is True


def test_merker_aus_der_zukunft_laesst_laufen():
    """Zurückgestellte Uhr: Ohne diese Regel stünden die Erinnerungen still,
    bis die Zukunft eingeholt ist."""
    assert ist_faellig((JETZT + timedelta(days=3)).isoformat(), JETZT, TAG) is True


def test_knapp_vor_dem_intervall_laeuft_schon():
    """Der Tick trifft den Zeitpunkt nie genau. Ohne Toleranz wanderte der Lauf
    mit jedem Tag um eine Tick-Länge nach hinten, bis er nachts läge."""
    assert ist_faellig(_vor(hours=23, minutes=59), JETZT, TAG) is True


def test_deutlich_vor_dem_intervall_laeuft_nicht():
    assert ist_faellig(_vor(hours=23, minutes=30), JETZT, TAG) is False
