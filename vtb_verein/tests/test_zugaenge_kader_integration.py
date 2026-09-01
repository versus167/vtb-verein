"""Kader und Aktivitätsstand in der Zugänge-Liste (#183).

Die Freischaltung läuft beim Rollout mannschaftsweise, deshalb liefert
`list_freischaltung` zu jeder Zeile die Mannschaften des Mitglieds *am heutigen
Tag* – und zusätzlich `last_seen` neben `last_login`. Beides steckt in einer
Subquery mit Zeitraums- und DISTINCT-Logik; prüfbar nur an echtem Postgres.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an):
    docker run -d --name vtb-pg-183 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=t183 -p 55483:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55483/t183 \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_zugaenge_kader_integration.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.abteilung import Abteilung  # noqa: E402
from app.models.mitglied import Mitglied  # noqa: E402
from app.models.permission import Permission  # noqa: E402
from app.db.mannschaft_repository import Mannschaft  # noqa: E402
from app.services.user_service import UserService  # noqa: E402
from backend.api import personen as personen_api  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_PRAEFIX = 'kader183-'
_GESTERN = (date.today() - timedelta(days=1)).isoformat()
_MORGEN = (date.today() + timedelta(days=1)).isoformat()
_VORJAHR = (date.today() - timedelta(days=365)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-kader183-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Eigene Zeilen vor UND nach dem Test wegräumen – die Wegwerf-DB teilen sich
    alle Integrationstests."""
    def weg():
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM mitglied_mannschaft_history WHERE mannschaft_id IN "
                        "(SELECT id FROM mannschaft WHERE name LIKE %s)", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mitglied_mannschaft WHERE mannschaft_id IN "
                        "(SELECT id FROM mannschaft WHERE name LIKE %s)", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mannschaft_history WHERE name LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mannschaft WHERE name LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM abteilung_history WHERE name LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM abteilung WHERE name LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mitglied_history WHERE nachname LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM mitglied WHERE nachname LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users_history WHERE username LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users WHERE username LIKE %s", (_PRAEFIX + '%',))
        db.conn.commit()
    weg()
    yield
    weg()


class _Freischalter:
    """Handelnder mit vereinsweitem Freischalt-Recht (Scope-Abfrage entfällt damit)."""
    id = 0
    username = 'tester'
    role = 'mitglied'

    def has_permission(self, p):
        return p in (Permission.PERSONEN_FREISCHALTEN, Permission.PERSONEN_PERMISSIONS)

    def has_permission_global(self, p):
        return self.has_permission(p)

    def allowed_abteilungen(self, p):
        return None


def _mitglied(db, name):
    return db.create_mitglied(
        Mitglied(vorname='Erika', nachname=_PRAEFIX + name, art='mitglied',
                 eintrittsdatum='2020-01-01', zahlungsart='ueberweisung'),
        created_by='tester')


def _mannschaft(db, name, abteilung_name='abt'):
    abt = db.create_abteilung(Abteilung(name=_PRAEFIX + abteilung_name), created_by='tester')
    return db.mannschaften.create(
        Mannschaft(abteilung_id=abt.id, name=_PRAEFIX + name), created_by='tester')


def _zeile(db, mitglied_id):
    zeilen = personen_api.list_freischaltung(_Freischalter(), db)
    return next(z for z in zeilen if z['mitglied_id'] == mitglied_id)


def test_aktiver_kader_steht_in_der_zeile(db):
    m = _mitglied(db, 'aktiv')
    t = _mannschaft(db, 'herren1', 'fussball')
    db.create_mitglied_mannschaft(m.id, t.id, 'spieler', _VORJAHR, None, 'tester')
    kader = _zeile(db, m.id)['mannschaften']
    assert [(k['id'], k['name']) for k in kader] == [(t.id, _PRAEFIX + 'herren1')]
    # Die Abteilung hängt mit dran: gleichnamige Mannschaften verschiedener
    # Abteilungen wären im Filter sonst nicht auseinanderzuhalten.
    assert kader[0]['abteilung'] == _PRAEFIX + 'fussball'


def test_mitglied_ohne_kader_bekommt_leere_liste(db):
    """Kein Kader heißt leere Liste, nicht None – das Frontend filtert darüber."""
    m = _mitglied(db, 'ohne')
    assert _zeile(db, m.id)['mannschaften'] == []


def test_beendeter_und_kuenftiger_kader_bleiben_draussen(db):
    """Stichtag ist heute: abgelaufene Zugehörigkeiten und solche, die erst morgen
    beginnen, gehören nicht in die Rollout-Auswahl."""
    beendet = _mitglied(db, 'beendet')
    kuenftig = _mitglied(db, 'kuenftig')
    t = _mannschaft(db, 'damen1')
    db.create_mitglied_mannschaft(beendet.id, t.id, 'spieler', _VORJAHR, _GESTERN, 'tester')
    db.create_mitglied_mannschaft(kuenftig.id, t.id, 'spieler', _MORGEN, None, 'tester')
    assert _zeile(db, beendet.id)['mannschaften'] == []
    assert _zeile(db, kuenftig.id)['mannschaften'] == []


def test_zwei_rollen_ergeben_einen_eintrag(db):
    """Wer im selben Team spielt und betreut, hat zwei Zeilen in
    mitglied_mannschaft – in der Liste darf das Team trotzdem nur einmal stehen."""
    m = _mitglied(db, 'doppelrolle')
    t = _mannschaft(db, 'ejugend')
    db.create_mitglied_mannschaft(m.id, t.id, 'spieler', _VORJAHR, None, 'tester')
    db.create_mitglied_mannschaft(m.id, t.id, 'betreuer', _VORJAHR, None, 'tester')
    assert len(_zeile(db, m.id)['mannschaften']) == 1


def test_geloeschtes_bleibt_draussen(db):
    """Soft-Delete zählt auf beiden Seiten: die Zuordnung wie die Mannschaft."""
    ohne_zuordnung = _mitglied(db, 'zuordnungweg')
    ohne_team = _mitglied(db, 'teamweg')
    t1 = _mannschaft(db, 'alt1')
    t2 = _mannschaft(db, 'alt2')
    mm = db.create_mitglied_mannschaft(ohne_zuordnung.id, t1.id, 'spieler', _VORJAHR, None, 'tester')
    db.mark_mitglied_mannschaft_deleted(mm.id, 'tester')
    db.create_mitglied_mannschaft(ohne_team.id, t2.id, 'spieler', _VORJAHR, None, 'tester')
    db.mannschaften.mark_deleted(t2.id, 'tester')
    assert _zeile(db, ohne_zuordnung.id)['mannschaften'] == []
    assert _zeile(db, ohne_team.id)['mannschaften'] == []


def test_last_seen_kommt_als_string_neben_last_login(db):
    """„Zuletzt aktiv" ist ein eigener Zeitpunkt (letzter Request), nicht der
    Login – und muss wie last_login als String rausgehen (vgl. #57)."""
    u = UserService(db).create(
        username=_PRAEFIX + 'aktiv', email=f'{_PRAEFIX}aktiv@example.org', role='mitglied',
        active=True, created_by='tester', password='geheim123', send_magic_link=False)
    m = db.create_mitglied(
        Mitglied(vorname='Erika', nachname=_PRAEFIX + 'seen', art='mitglied',
                 eintrittsdatum='2020-01-01', zahlungsart='ueberweisung', user_id=u.id),
        created_by='tester')
    db.update_last_seen(u.id)
    zeile = _zeile(db, m.id)
    assert isinstance(zeile['last_seen'], str)
    # Nie angemeldet, aber schon aktiv gewesen: die beiden Felder sind unabhängig.
    assert zeile['last_login'] is None
