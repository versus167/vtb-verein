"""Obergrenze für den Ticket-Titel (#156).

Der Titel steht in der Listenkarte, in der Kopfleiste des Dialogs und in der
Betreffzeile der Benachrichtigungen — ein eingefügter Absatz zerreißt alle drei.
Das Feld im Frontend begrenzt zwar auf dieselbe Zahl, aber durchsetzen muss es
die API: Ein eigener Client (oder ein gepatchtes Formular) geht daran vorbei.

Reiner Modell-Test, keine DB: Geprüft wird die Pydantic-Schicht, die jeden
Schreibzugriff passieren muss.
"""
import sys
from pathlib import Path

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.api.tickets import TITEL_MAX_LAENGE, TicketUpdate, TicketWrite  # noqa: E402


def test_titel_bis_zur_grenze_geht_durch():
    ticket = TicketWrite(titel='x' * TITEL_MAX_LAENGE, beschreibung='')
    assert len(ticket.titel) == TITEL_MAX_LAENGE


def test_ein_zeichen_zu_viel_wird_abgewiesen():
    with pytest.raises(ValidationError):
        TicketWrite(titel='x' * (TITEL_MAX_LAENGE + 1), beschreibung='')


def test_grenze_gilt_auch_beim_bearbeiten():
    """TicketUpdate erbt von TicketWrite — die Grenze darf dabei nicht verloren
    gehen, sonst ließe sich ein kurzer Titel nachträglich beliebig verlängern."""
    with pytest.raises(ValidationError):
        TicketUpdate(titel='x' * (TITEL_MAX_LAENGE + 1), beschreibung='',
                     expected_version=1)


def test_bestehende_titel_passen_in_die_grenze():
    """Der längste Titel im Bestand hat 87 Zeichen. Die Grenze ist bewusst
    darüber gewählt: Sie soll den eingefügten Absatz abfangen, nicht die
    gewachsene Praxis brechen."""
    assert TITEL_MAX_LAENGE >= 100


def test_beschreibung_bleibt_unbegrenzt():
    """Ausführliches gehört in die Beschreibung — die wird nicht gedeckelt."""
    ticket = TicketWrite(titel='kurz', beschreibung='y' * 50_000)
    assert len(ticket.beschreibung) == 50_000
