"""`_person_row` baut die Zeile der Personenliste (backend/api/personen.py).

Der Anlass ist ein Fehler in Produktion: Nach dem Entfernen von
`mitglied_abteilung.status` (Schema v105) griff diese Funktion weiter darauf zu –
`AttributeError`, HTTP 500. Betroffen war nicht nur die Liste: Jeder schreibende
Personen-Endpunkt gibt seine Antwort über `_person_row` zurück.

Getestet wird deshalb gegen die **echten Dataclasses**, nicht gegen Stubs mit
frei erfundenen Attributen – nur so fällt eine entfernte Spalte hier auf.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.db.mitglied_abteilung_repository import MitgliedAbteilung  # noqa: E402
from app.db.mitglied_funktion_repository import MitgliedFunktion  # noqa: E402
from app.models.mitglied import Mitglied  # noqa: E402
from app.models.user import User  # noqa: E402
from backend.api.personen import _person_row  # noqa: E402

GESTERN = '2020-01-01'
KUENFTIG = '2099-01-01'


def _mitglied():
    return Mitglied(id=5, vorname='Erika', nachname='Muster',
                    eintrittsdatum='2020-01-01', zahlungsart='lastschrift')


def _zuordnung(**kwargs):
    daten = dict(id=1, mitglied_id=5, abteilung_id=3, abteilung_name='Tischtennis',
                 abteilung_kuerzel='TT', von=GESTERN, bis=None, version=1)
    daten.update(kwargs)
    return MitgliedAbteilung(**daten)


def _funktion(**kwargs):
    daten = dict(id=2, mitglied_id=5, abteilung_id=3, abteilung_name='Tischtennis',
                 funktion='passiv', von=GESTERN, bis=None, version=1)
    daten.update(kwargs)
    return MitgliedFunktion(**daten)


def _user():
    return User(id=9, username='erika', email=None, password_hash='', role='mitglied',
                active=True, last_login=None, version=1, created_at='2020-01-01',
                created_by='test', updated_at='2020-01-01', updated_by='test')


def test_zeile_enthaelt_die_zuordnung(): 
    zeile = _person_row(_user(), _mitglied(), [_zuordnung()], [_funktion()])
    assert [a['abteilung_name'] for a in zeile['abteilungen']] == ['Tischtennis']
    assert [f['funktion'] for f in zeile['funktionen']] == ['passiv']


def test_die_zuordnung_traegt_keinen_status_mehr():
    """Seit v105 sagt die Zuordnung nur noch, von wann bis wann jemand dazugehört.
    Ob er aktiv mitmacht, steht als Funktion `passiv` daneben."""
    zeile = _person_row(_user(), _mitglied(), [_zuordnung()], [])
    assert 'status' not in zeile['abteilungen'][0]
    assert set(zeile['abteilungen'][0]) == {
        'id', 'abteilung_id', 'abteilung_name', 'abteilung_kuerzel', 'von', 'bis'}


def test_abgelaufene_zuordnungen_bleiben_draussen():
    """Nur laufende und künftige gehören in die Liste (Ticket #91)."""
    zeile = _person_row(_user(), _mitglied(),
                        [_zuordnung(id=1, bis='2021-01-01'),
                         _zuordnung(id=2, von=KUENFTIG, abteilung_name='Volleyball')],
                        [_funktion(bis='2021-01-01')])
    assert [a['abteilung_name'] for a in zeile['abteilungen']] == ['Volleyball']
    assert zeile['funktionen'] == []


def test_ohne_mitglied_bleibt_die_zeile_baubar():
    """Reine Benutzerkonten ohne Personendatensatz kommen hier ebenfalls durch."""
    zeile = _person_row(_user(), None, [], [])
    assert zeile['abteilungen'] == [] and zeile['mitglied'] is None
