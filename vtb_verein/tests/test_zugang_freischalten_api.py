"""Zugang freischalten (Recht `personen.freischalten`, backend/api/personen.py).

Das Recht ist bewusst schmal: Es schaltet einem bestehenden Mitglied den Login frei,
ohne Rechte zu vergeben, Passwörter zu setzen oder Stammdaten zu ändern. Getestet
wird genau diese Enge – wer darf, was dabei entstehen darf und wo abgeriegelt wird.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_gastspieler_api).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.mitglied import Mitglied  # noqa: E402
from app.models.permission import BASE_PERMISSIONS, Permission  # noqa: E402
from backend.api import personen as api  # noqa: E402


# --------------------------------------------------------------------- Stubs

def _user(*perms, role='mitglied', uid=1, username='helfer', scoped=None):
    """Handelnder User. `scoped` = Abteilungs-IDs, falls das Recht nur dort gilt."""
    keys = set(perms)

    def has_permission(p):
        return role == 'admin' or p in keys

    def has_permission_global(p):
        if role == 'admin':
            return True
        return p in keys and not (scoped and p == Permission.PERSONEN_FREISCHALTEN)

    def allowed_abteilungen(p):
        if has_permission_global(p):
            return None
        return set(scoped or ())

    return SimpleNamespace(
        id=uid, username=username, role=role, active=True,
        has_permission=has_permission,
        has_permission_global=has_permission_global,
        allowed_abteilungen=allowed_abteilungen,
    )


def _mitglied(mid=5, user_id=None):
    return Mitglied(id=mid, vorname='Erika', nachname='Muster', user_id=user_id,
                    eintrittsdatum='2020-01-01')


class _Cursor:
    """Minimaler Cursor-Ersatz: liefert für die Belegt-Prüfung eine feste Zeile."""

    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


def _db(mitglied=None, mail_belegt_von=None, ziel_user=None,
        ziel_permissions=frozenset(), scope_ids=None, kontakte=()):
    calls = []

    def get_mitglied(mid):
        if mitglied is None or mitglied.id != mid:
            raise KeyError(mid)
        return mitglied

    def update_mitglied(m, updated_by):
        calls.append(('update_mitglied', m.user_id))
        return True

    row = {'username': mail_belegt_von} if mail_belegt_von else None

    class _ScopeCursor(_Cursor):
        """Deckt beide SQL-Zugriffe des Endpunkts ab: den Abteilungs-Scope
        (visible_mitglied_ids, liest fetchall) und die Belegt-Prüfung (fetchone)."""

        def fetchall(self):
            return [{'mitglied_id': i} for i in (scope_ids or ())]

    def cursor():
        return _ScopeCursor(row)

    return SimpleNamespace(
        conn=SimpleNamespace(cursor=cursor),
        get_mitglied=get_mitglied,
        update_mitglied=update_mitglied,
        get_user_by_id=lambda uid: ziel_user,
        list_mitglied_kontakte=lambda mid: list(kontakte),
        create_mitglied_kontakt=lambda *a: calls.append(('kontakt', a)),
        update_mitglied_kontakt=lambda *a: calls.append(('kontakt_update', a)) or True,
        auth_token_repository=SimpleNamespace(
            entwerte_offene_tokens=lambda uid, typ=None: calls.append(('entwertet', uid, typ))),
        set_mitglied_primaer_kontakt=lambda *a: calls.append(('primaer', a)),
        list_mitglied_abteilungen=lambda mid: [],
        list_mitglied_funktionen=lambda mid: [],
        permissions=SimpleNamespace(
            get_effective_permissions=lambda uid: SimpleNamespace(
                keys=lambda: set(ziel_permissions)),
        ),
        access_log_repository=SimpleNamespace(log=lambda *a, **k: calls.append(('log', k))),
        calls=calls,
    )


class _PersonServiceStub:
    """Ersetzt PersonService: hält fest, mit welchen Argumenten der User entstünde."""

    letzte_anlage = None

    def __init__(self, db):
        self.db = db

    def _generate_username(self, vorname, nachname):
        return f'{vorname}.{nachname}'.lower()

    def create_user_only(self, **kwargs):
        _PersonServiceStub.letzte_anlage = kwargs
        return SimpleNamespace(id=99, username=kwargs['username'], email=kwargs['email'],
                               role=kwargs['role'], active=kwargs['active'],
                               last_login=None, last_seen=None, version=1,
                               updated_at=None)


@pytest.fixture(autouse=True)
def _person_service(monkeypatch):
    _PersonServiceStub.letzte_anlage = None
    monkeypatch.setattr(api, 'PersonService', _PersonServiceStub)
    return _PersonServiceStub


_REQUEST = SimpleNamespace(headers={}, client=SimpleNamespace(host='127.0.0.1'))


# ---------------------------------------------------------------- Berechtigung

def test_ohne_recht_kein_freischalten():
    db = _db(_mitglied())
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='a@b.de'), _REQUEST,
                                _user(Permission.PERSONEN_READ), db)
    assert e.value.status_code == 403


def test_ohne_recht_keine_liste():
    with pytest.raises(HTTPException) as e:
        api.list_freischaltung(_user(Permission.PERSONEN_READ), _db())
    assert e.value.status_code == 403


def test_freischalten_recht_genuegt(_person_service):
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert _person_service.letzte_anlage['email'] == 'neu@example.org'


def test_permissions_recht_bleibt_obermenge(_person_service):
    """Wer Rechte vergeben darf, durfte Logins schon immer anlegen."""
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_PERMISSIONS), db)
    assert _person_service.letzte_anlage is not None


# ------------------------------------------------------- Was entstehen darf

def test_immer_mitglied_ohne_passwort(_person_service):
    """Kein Admin, kein Passwort, aktiv – unabhängig von jeder Eingabe."""
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    anlage = _person_service.letzte_anlage
    assert anlage['role'] == 'mitglied'
    assert anlage['password'] is None
    assert anlage['active'] is True


def test_schema_kennt_keine_rolle():
    """role/active/password sind im Schema nicht vorgesehen – Admin-Anlage ist
    strukturell ausgeschlossen, nicht bloß per Prüfung untersagt."""
    felder = set(api.ZugangFreischalten.model_fields)
    assert felder == {'email'}


def test_neue_mail_kommt_als_zusatzkontakt_dazu(_person_service):
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    kontakte = [c[1] for c in db.calls if c[0] == 'kontakt']
    assert kontakte and kontakte[0][1:3] == ('email', 'neu@example.org')
    assert kontakte[0][4] is False, 'darf sich nicht zum Primärkontakt machen'


def test_vorhandene_primaeradresse_bleibt_unangetastet(_person_service):
    """Der Freischalter darf Stammdaten nicht wegnehmen: Eine gepflegte (z. B.
    Familien-)Adresse muss die Freischaltung überleben."""
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert not [c for c in db.calls if c[0] == 'primaer']


def test_bekannte_mail_legt_keinen_zweitkontakt_an(_person_service):
    """Wird eine bereits hinterlegte Adresse gewählt, ändert sich an den Kontakten nichts."""
    vorhanden = SimpleNamespace(typ='email', wert='Bekannt@Example.org')
    db = _db(_mitglied(), kontakte=[vorhanden])
    api.zugang_freischalten(5, api.ZugangFreischalten(email='bekannt@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert not [c for c in db.calls if c[0] == 'kontakt']


def test_freischalten_wird_protokolliert(_person_service):
    db = _db(_mitglied())
    api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'), _REQUEST,
                            _user(Permission.PERSONEN_FREISCHALTEN), db)
    logs = [c[1] for c in db.calls if c[0] == 'log']
    assert logs and logs[0]['category'] == 'zugang'
    assert logs[0]['username'] == 'helfer'


# ------------------------------------------------------------------ Grenzen

def test_belegte_mail_nennt_den_inhaber():
    """Eine Adresse trägt genau ein Konto – bei Familienadressen muss erkennbar
    sein, wem sie schon gehört."""
    db = _db(_mitglied(), mail_belegt_von='papa.muster')
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='familie@example.org'),
                                _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 409
    assert 'papa.muster' in e.value.detail


def test_bestehender_zugang_wird_nicht_ueberschrieben():
    db = _db(_mitglied(user_id=42))
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='neu@example.org'),
                                _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 409


def test_leere_mail_abgelehnt():
    db = _db(_mitglied())
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='  '), _REQUEST,
                                _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 422


def test_unbekanntes_mitglied():
    db = _db(None)
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='a@b.de'), _REQUEST,
                                _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 404


# -------------------------------------------------------------- Abteilungs-Scope

def test_scope_sperrt_fremde_abteilung():
    """Über eine abteilungsgebundene Funktion geerbtes Recht wirkt nur dort (Stufe E)."""
    db = _db(_mitglied(mid=5), scope_ids=[7, 8])
    handelnder = _user(Permission.PERSONEN_FREISCHALTEN, scoped={3})
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email='a@b.de'), _REQUEST,
                                handelnder, db)
    assert e.value.status_code == 403


def test_scope_erlaubt_eigene_abteilung(_person_service):
    db = _db(_mitglied(mid=5), scope_ids=[5, 8])
    handelnder = _user(Permission.PERSONEN_FREISCHALTEN, scoped={3})
    api.zugang_freischalten(5, api.ZugangFreischalten(email='a@b.de'), _REQUEST,
                            handelnder, db)
    assert _person_service.letzte_anlage is not None


# ------------------------------------------------------------------ Einladung

def test_einladung_ohne_zugang_404():
    db = _db(_mitglied())
    with pytest.raises(HTTPException) as e:
        api.zugang_einladung_senden(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 404


def test_einladung_bei_deaktiviertem_zugang_409():
    ziel = SimpleNamespace(id=42, username='erika.muster', email='e@x.de',
                           role='mitglied', active=False, version=1)
    db = _db(_mitglied(user_id=42), ziel_user=ziel)
    with pytest.raises(HTTPException) as e:
        api.zugang_einladung_senden(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 409


# ------------------------------------------------------- Aufbau der Adresse

@pytest.mark.parametrize("adresse", ['max.mustermannweb.de', 'max@web', 'max @web.de'])
def test_freischalten_lehnt_kaputte_adresse_ab(adresse, _person_service):
    """Ohne Prüfung entstünde ein Zugang, an den nie eine Mail gehen kann."""
    db = _db(_mitglied())
    with pytest.raises(HTTPException) as e:
        api.zugang_freischalten(5, api.ZugangFreischalten(email=adresse), _REQUEST,
                                _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 422
    assert _person_service.letzte_anlage is None


# ------------------------------------------------------- Login-Adresse ändern

class _UserServiceStub:
    """UserService-Ersatz: hält die Änderung fest und spielt den Mailversand."""

    letzte_aenderung = None
    gesendet_an = None
    versand_klappt = True

    def __init__(self, db):
        pass

    def update(self, **kwargs):
        _UserServiceStub.letzte_aenderung = kwargs
        return True

    def send_magic_link(self, email):
        _UserServiceStub.gesendet_an = email
        return _UserServiceStub.versand_klappt


@pytest.fixture
def _user_service(monkeypatch):
    _UserServiceStub.letzte_aenderung = None
    _UserServiceStub.gesendet_an = None
    _UserServiceStub.versand_klappt = True
    monkeypatch.setattr(api, 'UserService', _UserServiceStub)
    return _UserServiceStub


def _wechsel_db(*, last_login=None, role='mitglied', permissions=BASE_PERMISSIONS,
                belegt_von=None, kontakte=(), uid=42):
    ziel = SimpleNamespace(id=uid, username='erika.muster', email='alt@web.de',
                           role=role, active=True, version=3, last_login=last_login)
    return _db(_mitglied(user_id=uid), ziel_user=ziel, ziel_permissions=permissions,
               mail_belegt_von=belegt_von, kontakte=kontakte)


def test_mailwechsel_setzt_adresse_und_laedt_neu_ein(_user_service):
    db = _wechsel_db()
    antwort = api.zugang_mailadresse_aendern(
        5, api.ZugangMailadresse(email='neu@web.de'), _REQUEST,
        _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert antwort['email'] == 'neu@web.de'
    assert _user_service.letzte_aenderung['email'] == 'neu@web.de'
    assert _user_service.gesendet_an == 'neu@web.de'
    # Der alte Link darf nach dem Wechsel nicht mehr ins Konto führen.
    assert ('entwertet', 42, 'magic_link') in db.calls


def test_mailwechsel_nur_vor_der_ersten_anmeldung(_user_service):
    """Ab der ersten Anmeldung wäre eine neue Login-Adresse eine Kontoübernahme."""
    db = _wechsel_db(last_login='2026-08-01T10:00:00+00:00')
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 409
    assert _user_service.letzte_aenderung is None


def test_mailwechsel_prueft_den_aufbau(_user_service):
    db = _wechsel_db()
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu.web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 422
    assert _user_service.letzte_aenderung is None


def test_mailwechsel_auf_fremde_adresse_abgelehnt(_user_service):
    db = _wechsel_db(belegt_von='anderer.nutzer')
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='belegt@web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 409
    assert _user_service.letzte_aenderung is None


def test_mailwechsel_schont_admin_konten(_user_service):
    db = _wechsel_db(role='admin')
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 403


def test_mailwechsel_schont_konten_mit_weiteren_rechten(_user_service):
    db = _wechsel_db(permissions=BASE_PERMISSIONS | {Permission.BEITRAEGE_WRITE})
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 403


def test_mailwechsel_am_eigenen_zugang_abgelehnt(_user_service):
    db = _wechsel_db(uid=1)
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                       _REQUEST,
                                       _user(Permission.PERSONEN_FREISCHALTEN, uid=1), db)
    assert e.value.status_code == 400


def test_mailwechsel_meldet_versandfehler_trotz_geaenderter_adresse(_user_service):
    """502, aber die Adresse steht schon – die Oberfläche muss den neuen Stand zeigen."""
    _user_service.versand_klappt = False
    db = _wechsel_db()
    with pytest.raises(HTTPException) as e:
        api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                       _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 502
    assert _user_service.letzte_aenderung['email'] == 'neu@web.de'


def test_mailwechsel_korrigiert_den_login_kontakt(_user_service):
    """Der beim Freischalten angelegte Kontakt trägt die falsche Adresse – er wird
    korrigiert statt einen zweiten daneben zu stellen."""
    alt = SimpleNamespace(id=7, typ='email', wert='alt@web.de', label='Login',
                          ist_primaer=True, version=1)
    db = _wechsel_db(kontakte=(alt,))
    api.zugang_mailadresse_aendern(5, api.ZugangMailadresse(email='neu@web.de'),
                                   _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    updates = [c for c in db.calls if c[0] == 'kontakt_update']
    assert updates and updates[0][1][2] == 'neu@web.de'
    assert not [c for c in db.calls if c[0] == 'kontakt']


# --------------------------------------------------------------- Deaktivieren

def _deaktivier_db(ziel_role='mitglied', ziel_permissions=BASE_PERMISSIONS):
    ziel = SimpleNamespace(id=42, username='erika.muster', email='e@x.de',
                           role=ziel_role, active=True, version=3)
    return _db(_mitglied(user_id=42), ziel_user=ziel, ziel_permissions=ziel_permissions)


def test_deaktivieren_schont_admin_konten():
    db = _deaktivier_db(ziel_role='admin')
    with pytest.raises(HTTPException) as e:
        api.zugang_deaktivieren(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 403


def test_deaktivieren_schont_konten_mit_weiteren_rechten():
    """Sonst könnte ein Freischalter der Buchhaltung den Zugang entziehen."""
    db = _deaktivier_db(ziel_permissions=BASE_PERMISSIONS | {Permission.BEITRAEGE_WRITE})
    with pytest.raises(HTTPException) as e:
        api.zugang_deaktivieren(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert e.value.status_code == 403


def test_deaktivieren_eigener_zugang_abgelehnt():
    ziel = SimpleNamespace(id=1, username='helfer', email='h@x.de',
                           role='mitglied', active=True, version=1)
    db = _db(_mitglied(user_id=1), ziel_user=ziel, ziel_permissions=BASE_PERMISSIONS)
    with pytest.raises(HTTPException) as e:
        api.zugang_deaktivieren(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN, uid=1), db)
    assert e.value.status_code == 400


def test_deaktivieren_reines_mitgliedskonto(monkeypatch):
    db = _deaktivier_db()
    gesetzt = {}

    class _UserServiceStub:
        def __init__(self, db):
            pass

        def update(self, **kwargs):
            gesetzt.update(kwargs)
            return True

    monkeypatch.setattr(api, 'UserService', _UserServiceStub)
    antwort = api.zugang_deaktivieren(5, _REQUEST, _user(Permission.PERSONEN_FREISCHALTEN), db)
    assert antwort == {'ok': True}
    assert gesetzt['active'] is False
    assert gesetzt['role'] == 'mitglied'      # Rolle bleibt unangetastet
