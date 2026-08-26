"""Tests für den Aufgaben-Hinweis an Kacheln und Nav-Punkten (Ticket #133).

Die Zahl ist nur dann etwas wert, wenn sie zu der Liste passt, die sich hinter
der Kachel öffnet: gleicher Rechte-/Abteilungs-Scope, gleicher Status. Darum
wird hier vor allem geprüft, *welchen* Scope die Zählung ans Repository gibt.

Bewusst ohne DB (Fakes wie in test_ul_stunden_uebersicht.py) – die SQL-Seite
deckt test_rechnungen.py::test_anzahl_zur_freigabe_zaehlt_wie_die_liste ab.
"""
import sys
from pathlib import Path

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.permission import Permission  # noqa: E402
from backend.api.aufgaben import offene_aufgaben  # noqa: E402
from backend.api.ul_stunden import anzahl_zu_bestaetigen  # noqa: E402


class _User:
    """Rechte lenient (has_permission) und scoped (allowed_abteilungen)."""

    def __init__(self, *perms, scoped=None, id=1):
        self._perms = set(perms)
        self._scoped = scoped or {}
        self.id = id                         # Termin-Zählung fragt nach dem Konto

    def has_permission(self, p):
        return p in self._perms or p in self._scoped

    def has_permission_global(self, p):
        return p in self._perms

    def allowed_abteilungen(self, p):
        if p in self._perms:
            return None                      # global = alle Abteilungen
        return set(self._scoped.get(p, set()))


class _AbrRepo:
    def __init__(self, anzahl=0):
        self.anzahl = anzahl
        self.aufrufe = []

    def count_for_abteilungen(self, abteilungen, status=None):
        self.aufrufe.append((abteilungen, status))
        return self.anzahl


class _RechnungService:
    def __init__(self, anzahl=0):
        self.anzahl = anzahl

    def anzahl_zur_freigabe(self, user):
        return self.anzahl


class _TicketService:
    def __init__(self, anzahl=0):
        self.anzahl = anzahl

    def anzahl_zustaendig(self, user):
        return self.anzahl


class _TerminRepo:
    def __init__(self, anzahl=0):
        self.anzahl = anzahl
        self.aufrufe = []

    def anzahl_offene_meldungen(self, user_id):
        self.aufrufe.append(user_id)
        return self.anzahl


class _DB:
    def __init__(self, ul=0, rechnungen=0, tickets=0, termine=0):
        self.ul_abrechnungen = _AbrRepo(ul)
        self.rechnungen = _RechnungService(rechnungen)
        self.tickets = _TicketService(tickets)
        self.termine = _TerminRepo(termine)


# ------------------------------------------------------- ÜL-Bestätigungen

def test_ul_verwaltung_zaehlt_ohne_abteilungs_scope():
    db = _DB(ul=4)
    user = _User(Permission.UL_STUNDEN_VERWALTEN)
    assert anzahl_zu_bestaetigen(user, db) == 4
    # None = alle Abteilungen; gezählt wird nur, was eingereicht ist.
    assert db.ul_abrechnungen.aufrufe == [(None, 'eingereicht')]


def test_ul_abteilungsleiter_zaehlt_nur_seine_abteilungen():
    db = _DB(ul=2)
    user = _User(scoped={Permission.UL_STUNDEN_BESTAETIGEN: {7}})
    assert anzahl_zu_bestaetigen(user, db) == 2
    assert db.ul_abrechnungen.aufrufe == [({7}, 'eingereicht')]


def test_ul_ohne_bestaetigungsrecht_kein_hinweis():
    """Kein 403 wie in der Liste – ein Badge, das niemand sehen soll, ist 0."""
    db = _DB(ul=99)
    assert anzahl_zu_bestaetigen(_User(), db) == 0
    assert db.ul_abrechnungen.aufrufe == []   # gar nicht erst gefragt


# ----------------------------------------------------------- Aggregation

def test_offene_aufgaben_summiert_die_quellen():
    db = _DB(ul=2, rechnungen=3, tickets=4, termine=5)
    user = _User(Permission.UL_STUNDEN_VERWALTEN)
    assert offene_aufgaben(user, db) == {
        "gesamt": 14,
        "offen": {"rechnungen": 3, "uebungsleiter": 2, "tickets": 4, "termine": 5},
    }


def test_termine_werden_fuer_den_angemeldeten_benutzer_gezaehlt():
    """Die eigene Meldung – gefragt wird mit der eigenen user_id, nicht global."""
    db = _DB(termine=2)
    assert offene_aufgaben(_User(id=42), db)["offen"]["termine"] == 2
    assert db.termine.aufrufe == [42]


def test_ohne_aufgaben_bleibt_alles_null():
    """Jeder Schlüssel wird geliefert – das Frontend blendet bei 0 selbst aus."""
    ergebnis = offene_aufgaben(_User(), _DB())
    assert ergebnis["gesamt"] == 0
    assert set(ergebnis["offen"]) == {"rechnungen", "uebungsleiter", "tickets", "termine"}


def test_eine_kaputte_quelle_reisst_den_rest_nicht_mit():
    """Ein Hinweis am Nav-Punkt ist kein Grund, das Dashboard zu verlieren."""
    db = _DB(ul=2, tickets=1)

    def _explodiert(_user):
        raise RuntimeError("Repository weg")

    db.rechnungen.anzahl_zur_freigabe = _explodiert
    user = _User(Permission.UL_STUNDEN_VERWALTEN)
    assert offene_aufgaben(user, db) == {
        "gesamt": 3,
        "offen": {"rechnungen": 0, "uebungsleiter": 2, "tickets": 1, "termine": 0},
    }


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
