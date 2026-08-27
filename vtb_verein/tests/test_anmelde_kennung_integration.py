"""Anmelde-Kennung in der Datenbank: Benutzername ODER E-Mail-Adresse.

Beide Merkmale sind im Bestand eindeutig (partielle Unique-Indizes
`uix_users_username_active` / `uix_users_email_active`), also darf man sich mit
beiden anmelden — der Passwort-Login nimmt die Adresse, der Login-Link den
Benutzernamen. Niemand muss sich merken, welches der beiden Merkmale an welcher
Stelle gemeint war.

Warum echtes Postgres: Der Kern steckt in SQL, nicht in Python — das ODER über
zwei Spalten, der Vergleich ohne Rücksicht auf Groß-/Kleinschreibung und vor
allem die feste Reihenfolge (`_kennung_order`), die auch bei einer Kennung, die
auf zwei Konten passt, immer dasselbe Konto liefert. Genau das zeigt kein Stub.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-kennung -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=kennung -p 55434:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55434/kennung \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_anmelde_kennung_integration.py
"""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.user_service import UserService  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_PRAEFIX = 'kennung-'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-kennung-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    """Eigene Zeilen vor UND nach dem Test wegräumen – andere Integrationstests
    zählen User und stolpern sonst über unsere."""
    def weg():
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM users_history WHERE username LIKE %s", (_PRAEFIX + '%',))
            cur.execute("DELETE FROM users WHERE username LIKE %s", (_PRAEFIX + '%',))
        db.conn.commit()
    weg()
    yield
    weg()


def _anlegen(db, name, *, email=None, password='geheim123'):
    return UserService(db).create(
        username=_PRAEFIX + name, email=email, role='mitglied', active=True,
        created_by='tester', password=password, send_magic_link=False,
    )


# --- Beide Merkmale finden dasselbe Konto -----------------------------------
def test_benutzername_findet_das_konto(db):
    angelegt = _anlegen(db, 'maxi', email='maxi@example.org')
    assert db.get_user_by_kennung(_PRAEFIX + 'maxi').id == angelegt.id


def test_adresse_findet_dasselbe_konto(db):
    """Der eigentliche Punkt: Die Adresse ist genauso eindeutig wie der Name."""
    angelegt = _anlegen(db, 'maxi', email='maxi@example.org')
    assert db.get_user_by_kennung('maxi@example.org').id == angelegt.id


def test_grossschreibung_spielt_bei_beidem_keine_rolle(db):
    """Auf dem Handy schreibt die Tastatur das erste Zeichen gern groß – daran
    darf keine Anmeldung scheitern."""
    angelegt = _anlegen(db, 'maxi', email='maxi@example.org')
    assert db.get_user_by_kennung((_PRAEFIX + 'maxi').upper()).id == angelegt.id
    assert db.get_user_by_kennung('Maxi@Example.ORG').id == angelegt.id


def test_umliegende_leerzeichen_stoeren_nicht(db):
    angelegt = _anlegen(db, 'maxi', email='maxi@example.org')
    assert db.get_user_by_kennung('  maxi@example.org  ').id == angelegt.id


def test_leere_kennung_trifft_niemanden(db):
    """Konten ohne Zugang haben email IS NULL – eine leer abgeschickte Anmeldung
    darf davon keines treffen."""
    _anlegen(db, 'platzwart', email=None)
    for leer in ('', '   ', None):
        assert db.get_user_by_kennung(leer) is None


def test_unbekannte_kennung_trifft_niemanden(db):
    _anlegen(db, 'maxi', email='maxi@example.org')
    assert db.get_user_by_kennung('gibtsnicht@example.org') is None
    assert db.get_user_by_kennung(_PRAEFIX + 'gibtsnicht') is None


# --- Anmeldung selbst -------------------------------------------------------
def test_passwort_login_nimmt_auch_die_adresse(db):
    angelegt = _anlegen(db, 'maxi', email='maxi@example.org', password='geheim123')
    service = UserService(db)
    assert service.authenticate('maxi@example.org', 'geheim123').id == angelegt.id
    assert service.authenticate(_PRAEFIX + 'maxi', 'geheim123').id == angelegt.id
    assert service.authenticate('maxi@example.org', 'falsch') is None


# --- Eindeutigkeit bei Kollision -------------------------------------------
# Kollision: ein Benutzername, der wie die Adresse eines *anderen* Kontos aussieht.
# Der Unique-Index verhindert das nicht – er gilt je Spalte. Der UserService lässt
# es deshalb gar nicht erst zu (siehe unten); die Auflösung muss trotzdem eindeutig
# sein, für Altbestand und für den Fall, dass jemand direkt in die DB schreibt.
_DOPPELT = _PRAEFIX + 'a@example.org'


def _kollision(db):
    """`fremd` trägt die Adresse als *Benutzernamen*, `inhaber` als Adresse.

    Absichtlich am UserService vorbei per SQL – über ihn ginge es nicht mehr.
    """
    fremd = _anlegen(db, 'a@example.org', email=None)
    inhaber = _anlegen(db, 'inhaber', email=None)
    with db.conn.cursor() as cur:
        cur.execute("UPDATE users SET email = %s WHERE id = %s", (_DOPPELT, inhaber.id))
    db.conn.commit()
    assert fremd.username == _DOPPELT and fremd.id != inhaber.id
    return fremd, db.get_user_by_id(inhaber.id)


def test_kennung_mit_at_meint_zuerst_die_adresse(db):
    """Passt eine Kennung auf zwei Konten, gewinnt bei einem @ die Adresse.
    Übernehmen lässt sich damit nichts – danach entscheidet weiterhin das Passwort
    bzw. die Zustellung an die hinterlegte Adresse."""
    _fremd, inhaber = _kollision(db)
    assert db.get_user_by_kennung(_DOPPELT).id == inhaber.id


def test_konto_ohne_adresse_bleibt_ueber_sein_passwort_erreichbar(db):
    """Der Verlierer der Kollision ist nicht ausgesperrt: Sein Passwort gilt
    weiter – nur der Vorrang der Kennung ist entschieden."""
    fremd, inhaber = _kollision(db)
    angemeldet = UserService(db).authenticate(_DOPPELT, 'geheim123')
    assert angemeldet.id == inhaber.id
    assert UserService(db).authenticate(fremd.username, 'geheim123').id == inhaber.id


def test_zaehlschluessel_und_konto_stimmen_ueberein(db):
    """Die Anmelde-Bremse benutzt den schlanken Lookup. Liefe der auch nur im
    Kollisionsfall anders, zählte die Bremse auf ein anderes Konto als das,
    gegen das geprüft wird."""
    _fremd, inhaber = _kollision(db)
    for kennung in (_DOPPELT, _DOPPELT.upper(), _PRAEFIX + 'inhaber'):
        assert db.get_username_by_kennung(kennung) == db.get_user_by_kennung(kennung).username
    assert db.get_username_by_kennung(_DOPPELT) == inhaber.username


def test_ohne_treffer_liefert_der_schlanke_lookup_nichts(db):
    assert db.get_username_by_kennung('gibtsnicht@example.org') is None
    assert db.get_username_by_kennung('  ') is None


# --- Kollisionen lassen sich gar nicht erst anlegen -------------------------
def test_benutzername_darf_nicht_die_adresse_eines_anderen_sein(db):
    """Die eigentliche Absicherung: Beides sind Anmelde-Kennungen, also darf keine
    davon auf zwei Konten zeigen."""
    _anlegen(db, 'inhaber', email=_DOPPELT)
    with pytest.raises(ValueError, match='Anmelde-Kennung'):
        _anlegen(db, 'a@example.org', email=None)


def test_adresse_darf_nicht_der_benutzername_eines_anderen_sein(db):
    """Dieselbe Regel von der anderen Seite."""
    _anlegen(db, 'a@example.org', email=None)
    with pytest.raises(ValueError, match='Anmelde-Kennung'):
        _anlegen(db, 'inhaber', email=_DOPPELT)


def test_grossschreibung_hilft_beim_umgehen_nicht(db):
    """Verglichen wird ohne Rücksicht auf Groß-/Kleinschreibung – sonst wäre die
    Regel mit einer Umschaltung ausgehebelt."""
    _anlegen(db, 'inhaber', email=_DOPPELT.upper())
    with pytest.raises(ValueError, match='Anmelde-Kennung'):
        _anlegen(db, 'a@example.org', email=None)


def test_eigene_adresse_als_benutzername_bleibt_erlaubt(db):
    """Beide Wege führen zum selben Konto – daran ist nichts mehrdeutig."""
    angelegt = _anlegen(db, 'a@example.org', email=_DOPPELT)
    assert db.get_user_by_kennung(_DOPPELT).id == angelegt.id


def test_aendern_stolpert_nicht_ueber_das_eigene_konto(db):
    """Sonst ließe sich ein Konto mit Benutzername = eigener Adresse nie wieder
    bearbeiten."""
    angelegt = _anlegen(db, 'a@example.org', email=_DOPPELT)
    UserService(db).update(
        user_id=angelegt.id, username=angelegt.username, email=_DOPPELT,
        role='mitglied', active=True, updated_by='tester',
        expected_version=angelegt.version,
    )
    assert db.get_user_by_id(angelegt.id).email == _DOPPELT


def test_aendern_faengt_die_kollision_ebenfalls(db):
    """Die Regel gilt nicht nur beim Anlegen – sonst wäre sie in zwei Schritten
    umgangen."""
    _anlegen(db, 'inhaber', email=_DOPPELT)
    spaeter = _anlegen(db, 'harmlos', email=None)
    with pytest.raises(ValueError, match='Anmelde-Kennung'):
        UserService(db).update(
            user_id=spaeter.id, username=_DOPPELT, email=None,
            role='mitglied', active=True, updated_by='tester',
            expected_version=spaeter.version,
        )


def test_gewoehnliche_konten_stoeren_einander_nicht(db):
    """Die Regel darf den Normalfall nicht behindern."""
    a = _anlegen(db, 'maxi', email='maxi@example.org')
    b = _anlegen(db, 'moritz', email='moritz@example.org')
    assert db.get_user_by_kennung('maxi@example.org').id == a.id
    assert db.get_user_by_kennung(_PRAEFIX + 'moritz').id == b.id
