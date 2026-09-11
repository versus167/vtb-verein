"""Ist ein Sidecar-Lauf fällig? — die Entscheidung ohne DB und ohne Uhr.

Wichtig sind die Ränder: kein Merker (erster Lauf nach dem Update), ein Merker aus
der Zukunft (zurückgestellte Uhr) und ein unlesbarer Wert. In allen drei Fällen muss
die Antwort „lauf" heißen — eine ausgelassene Erinnerung ist teurer als eine, die
einmal zu früh kommt.

Dazu die Toleranz: Ein Sidecar tickt in festen Abständen, und ohne sie schöbe sich
ein 24-Stunden-Lauf mit jedem Tag um eine Tick-Länge nach hinten.

Mit der Wunschstunde (v122) kommt die zweite Hälfte der Frage dazu: nicht nur wie
oft, sondern wann. Der Kern ist der Anker — der Abstand zählt ab der Wunschstunde
des letzten Lauftags, nicht ab dessen tatsächlicher Uhrzeit. Sonst bliebe ein Lauf,
der nach einer Störung erst abends durchkam, für immer am Abend stehen.
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


# ------------------------------------------------------------- Wunschstunde (v122)
# Ortszeit des Containers (Sommer in Berlin) – die Wunschstunde meint die Uhr an der
# Wand, nicht UTC. 7:13 ist der erste Tick nach 7 Uhr bei 30-Minuten-Takt.
ORTSZEIT = timezone(timedelta(hours=2))
MORGENS = datetime(2026, 9, 10, 7, 13, tzinfo=ORTSZEIT)


def test_vor_der_wunschstunde_laeuft_nichts():
    """Auch ein längst überfälliger Lauf wartet – sonst wäre die Stunde wertlos."""
    nachts = MORGENS.replace(hour=3, minute=43)
    assert ist_faellig(nachts - 3 * TAG, nachts, TAG, 7) is False


def test_ab_der_wunschstunde_ist_faellig():
    assert ist_faellig(MORGENS - TAG, MORGENS, TAG, 7) is True


def test_zweiter_tick_am_selben_tag_laeuft_nicht():
    """Der Lauf um 7:13 ist vermerkt – der Tick um 7:43 darf nicht noch einmal."""
    assert ist_faellig(MORGENS, MORGENS.replace(minute=43), TAG, 7) is False


def test_verspaeteter_lauf_faengt_sich_wieder_ein():
    """Der eigentliche Grund für den Anker: Ein Lauf, der gestern erst um 22 Uhr
    durchkam, darf den heutigen nicht mit in den Abend ziehen."""
    gestern_abend = (MORGENS - TAG).replace(hour=22)
    assert ist_faellig(gestern_abend, MORGENS, TAG, 7) is True


def test_lauf_von_hand_verschiebt_den_taeglichen_nicht():
    """Heute ist danach Ruhe, morgen früh läuft es trotzdem zur Wunschzeit."""
    von_hand = MORGENS.replace(hour=12)
    assert ist_faellig(von_hand, von_hand.replace(hour=18), TAG, 7) is False
    assert ist_faellig(von_hand, MORGENS + TAG, TAG, 7) is True


def test_merker_aus_der_db_wird_in_ortszeit_verankert():
    """psycopg liefert den Merker als TIMESTAMPTZ in UTC. Verankert wird er in der
    Zone von `jetzt` – sonst läge der Anker im Sommer zwei Stunden daneben und der
    Lauf käme erst um neun."""
    gestern_utc = (MORGENS - TAG).astimezone(timezone.utc)
    assert ist_faellig(gestern_utc, MORGENS, TAG, 7) is True


def test_ohne_merker_laeuft_es_auch_vor_der_wunschstunde():
    """Kein Merker heißt fällig – und fängt sich am nächsten Tag von selbst ein."""
    assert ist_faellig(None, MORGENS.replace(hour=2), TAG, 7) is True


def test_unsinnige_stunde_haelt_den_lauf_nicht_an():
    """Vor einem kaputten Wert gilt dieselbe Regel wie vor einem kaputten Merker:
    lieber ein Lauf zu viel als eine ausgelassene Erinnerung."""
    assert ist_faellig(MORGENS - TAG, MORGENS, TAG, 99) is True


def test_kurzer_takt_behaelt_die_abstands_regel():
    """Unter 24 h trägt der Tagesanker nicht; die Stunde sagt dann nur, wann der
    erste Lauf des Tages frühestens darf."""
    sechs = timedelta(hours=6)
    assert ist_faellig(MORGENS.replace(hour=1), MORGENS, sechs, 7) is True
    assert ist_faellig(MORGENS, MORGENS.replace(hour=9), sechs, 7) is False


def test_ohne_stunde_bleibt_alles_beim_alten():
    """Die Wunschstunde ist optional – ohne sie zählt weiter der reine Abstand."""
    gestern_abend = (MORGENS - TAG).replace(hour=22)
    assert ist_faellig(gestern_abend, MORGENS, TAG) is False
