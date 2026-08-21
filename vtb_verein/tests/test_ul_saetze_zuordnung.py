"""Tests für die Zuordnung von Vergütungssätzen an einzelne Übungsleiter (#84).

Der Kern des Tickets: Einzelne ÜL werden anders behandelt als der Rest. Das Mittel
dafür ist ein `ul_satz` mit gesetztem `mitglied_id` – er schlägt in der Auflösung
jeden Abteilungs- und Vereinssatz. Diese Tests decken den Weg dorthin über die API
ab, inklusive der ÜL-Liste, aus der die Oberfläche ihren Picker füllt: Ohne sie
lässt sich der individuelle Satz nicht anlegen, und ein 403 fiele im Frontend nur
als leere Auswahl auf.
"""
import sys
from pathlib import Path

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from app.models.ul_stunden import ULSatz  # noqa: E402
from backend.api.ul_stunden import (  # noqa: E402
    SatzCreate, SatzUpdate, create_satz, update_satz, list_uebungsleiter,
)


class _User:
    def __init__(self, *perms, admin=False, id=1):
        self._perms = set(perms)
        self._admin = admin
        self.id = id
        self.username = 'tester'

    def has_permission(self, p):
        return self._admin or p in self._perms


class _SatzRepo:
    def __init__(self, vorhanden=None):
        self.gespeichert = {}
        self._vorhanden = vorhanden or {}

    def create(self, s: ULSatz, created_by: str):
        s.id = 42
        self.gespeichert[42] = s
        return s

    def get(self, id):
        return self.gespeichert.get(id) or self._vorhanden.get(id)

    def update(self, s: ULSatz, updated_by: str):
        self.gespeichert[s.id] = s
        return True


class _DB:
    def __init__(self, satz_repo=None, uebungsleiter=()):
        self.ul_saetze = satz_repo or _SatzRepo()
        self._uebungsleiter = list(uebungsleiter)

    def list_mitglieder_mit_funktion(self, *funktionen):
        self.gefragte_funktionen = funktionen
        return list(self._uebungsleiter)


_UL_LISTE = [
    {'id': 7, 'vorname': 'Uwe', 'nachname': 'Ürig', 'mitgliedsnummer': 101,
     'lizenz_aktuell_gueltig': True},
]


class TestUebungsleiterListe:
    """Die Auswahlliste des Pickers. Sie war bisher nur für die Fremderfassung da –
    wer Sätze pflegt, braucht sie genauso."""

    def test_verwalter_darf_die_liste_laden(self):
        db = _DB(uebungsleiter=_UL_LISTE)
        assert list_uebungsleiter(_User(Permission.UL_STUNDEN_VERWALTEN), db) == _UL_LISTE

    def test_liste_umfasst_beide_ul_funktionen(self):
        # 'uebungsleiter_lizenz' entsteht über den SPG-Import und zählt gleichwertig (#65).
        db = _DB(uebungsleiter=_UL_LISTE)
        list_uebungsleiter(_User(admin=True), db)
        assert set(db.gefragte_funktionen) == {'uebungsleiter', 'uebungsleiter_lizenz'}

    def test_ohne_recht_kein_zugriff(self):
        with pytest.raises(HTTPException) as e:
            list_uebungsleiter(_User(), _DB())
        assert e.value.status_code == 403


class TestSatzEinemUlZuordnen:
    def test_individueller_satz_wird_mit_mitglied_gespeichert(self):
        db = _DB()
        data = SatzCreate(verguetungsart='monatspauschale', satz=150.0, mitglied_id=7)
        create_satz(data, _User(Permission.UL_STUNDEN_VERWALTEN), db)

        gespeichert = db.ul_saetze.gespeichert[42]
        assert gespeichert.mitglied_id == 7
        assert gespeichert.verguetungsart == 'monatspauschale'
        assert gespeichert.satz == 150.0
        # Ohne Lizenzangabe gilt der Satz für beide Lizenzlagen – sonst verlöre ein ÜL
        # seine Vereinbarung beim Ablauf der Trainerlizenz.
        assert gespeichert.lizenz_klassifikation is None

    def test_individueller_satz_kann_auf_eine_abteilung_begrenzt_werden(self):
        db = _DB()
        data = SatzCreate(satz=18.0, mitglied_id=7, abteilung_id=3)
        create_satz(data, _User(Permission.UL_STUNDEN_VERWALTEN), db)

        gespeichert = db.ul_saetze.gespeichert[42]
        assert (gespeichert.mitglied_id, gespeichert.abteilung_id) == (7, 3)

    def test_ohne_ul_bleibt_der_satz_allgemein(self):
        db = _DB()
        create_satz(SatzCreate(satz=12.0), _User(Permission.UL_STUNDEN_VERWALTEN), db)
        assert db.ul_saetze.gespeichert[42].mitglied_id is None

    def test_zuordnung_ist_nachtraeglich_aenderbar(self):
        bestand = ULSatz(id=5, satz=12.0, mitglied_id=None, version=1)
        db = _DB(satz_repo=_SatzRepo(vorhanden={5: bestand}))
        update_satz(5, SatzUpdate(satz=12.0, mitglied_id=7, expected_version=1),
                    _User(Permission.UL_STUNDEN_VERWALTEN), db)
        assert db.ul_saetze.gespeichert[5].mitglied_id == 7

    def test_zuordnung_ist_wieder_loesbar(self):
        bestand = ULSatz(id=5, satz=12.0, mitglied_id=7, version=1)
        db = _DB(satz_repo=_SatzRepo(vorhanden={5: bestand}))
        update_satz(5, SatzUpdate(satz=12.0, mitglied_id=None, expected_version=1),
                    _User(Permission.UL_STUNDEN_VERWALTEN), db)
        assert db.ul_saetze.gespeichert[5].mitglied_id is None

    def test_ohne_verwaltungsrecht_kein_satz(self):
        with pytest.raises(HTTPException) as e:
            create_satz(SatzCreate(satz=12.0, mitglied_id=7),
                        _User(Permission.UL_STUNDEN_ERFASSEN), _DB())
        assert e.value.status_code == 403
