"""
API-Ebene des Passwort-Tresors: das Bearbeiten der geheimen Notiz (#162).

Passwort und Notiz liegen in EINEM Ciphertext. Bis #162 ließ sich die Notiz nur
zusammen mit dem Passwort ersetzen – und weil der Bearbeiten-Dialog sie nicht
vorbefüllen konnte, löschte ein Passwortwechsel sie stillschweigend. Geprüft wird
deshalb vor allem, dass jede Hälfte für sich änderbar ist und die jeweils andere
den Vorgang unverändert übersteht.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_schliessanlage_import_api).
"""
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import backend.core.config as cfg  # noqa: E402
from app.models.tresor import TresorEintrag  # noqa: E402
from backend.api import tresor as api  # noqa: E402
from backend.core import vault_crypto  # noqa: E402


@pytest.fixture(autouse=True)
def with_key():
    """Gültiger Tresor-Key für die Dauer des Tests (sonst antwortet die API mit 503)."""
    alt = cfg.settings.VAULT_KEY
    cfg.settings.VAULT_KEY = Fernet.generate_key().decode()
    yield
    cfg.settings.VAULT_KEY = alt


# --------------------------------------------------------------------- Stubs
def _user(role='mitglied'):
    return SimpleNamespace(
        id=1, username='schreiber', role=role, active=True,
        has_permission=lambda p: role == 'admin',
        has_permission_global=lambda p: role == 'admin',
        allowed_abteilungen=lambda p: None,
    )


def _eintrag(**kw):
    daten = dict(id=5, tresor_id=1, titel='Router', benutzername='admin', url=None,
                 version=1, created_at='', created_by='t', updated_at='', updated_by='t')
    daten.update(kw)
    return TresorEintrag(**daten)


class _EintragRepo:
    def __init__(self, eintrag, ciphertext):
        self.eintrag = eintrag
        self.ciphertext = ciphertext
        self.updates = []

    def get(self, eintrag_id):
        return self.eintrag if self.eintrag and self.eintrag.id == eintrag_id else None

    def get_ciphertext(self, eintrag_id):
        return self.ciphertext if self.get(eintrag_id) else None

    def update(self, eintrag_id, titel, benutzername, url, ct, by, expected_version):
        if expected_version != self.eintrag.version:
            return False
        self.updates.append(ct)
        if ct is not None:
            self.ciphertext = ct
        self.eintrag = replace(self.eintrag, titel=titel, benutzername=benutzername,
                               url=url, version=self.eintrag.version + 1, updated_by=by)
        return True


class _DB:
    def __init__(self, *, notiz='PIN 4711', passwort='hunter2', zugriff='write',
                 ciphertext=None):
        ct = ciphertext if ciphertext is not None else vault_crypto.encrypt_secret(passwort, notiz)
        self.tresor_eintraege = _EintragRepo(_eintrag(), ct)
        self.tresore = SimpleNamespace(
            get=lambda tid: SimpleNamespace(id=tid),
            get_access_for_user=lambda uid, tid: zugriff,
        )
        self.protokoll = []
        self.tresor_zugriff_log = SimpleNamespace(
            log=lambda **kw: self.protokoll.append(kw))

    def secret(self):
        return vault_crypto.decrypt_secret(self.tresor_eintraege.ciphertext)


def _update(db, **kw):
    daten = dict(titel='Router', benutzername='admin', url=None, expected_version=1)
    daten.update(kw)
    return api.update_eintrag(5, api.EintragUpdate(**daten), _user(), db)


def _notiz(db, eintrag_id=5, user=None):
    request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'), headers={})
    return api.eintrag_notiz(eintrag_id, request, user or _user(), db)


# ------------------------------------------------------- Notiz zum Bearbeiten
def test_notiz_endpunkt_liefert_die_notiz_ohne_passwort():
    db = _DB(notiz='PIN 4711', passwort='hunter2')
    antwort = _notiz(db)
    assert antwort['notiz'] == 'PIN 4711'
    assert 'passwort' not in antwort


def test_notiz_endpunkt_wird_eigens_auditiert():
    """Im Zugriffslog muss unterscheidbar bleiben, ob jemand ein Passwort angesehen
    oder nur die Notiz zum Bearbeiten geöffnet hat."""
    db = _DB()
    _notiz(db)
    assert [z['aktion'] for z in db.protokoll] == ['reveal_notiz']


def test_notiz_endpunkt_braucht_schreibzugriff():
    db = _DB(zugriff='read')
    with pytest.raises(HTTPException) as e:
        _notiz(db)
    assert e.value.status_code == 403
    assert db.protokoll == []


def test_notiz_endpunkt_ohne_vault_key_meldet_503():
    db = _DB()
    cfg.settings.VAULT_KEY = ''
    with pytest.raises(HTTPException) as e:
        _notiz(db)
    assert e.value.status_code == 503


def test_notiz_endpunkt_meldet_unbekannten_eintrag():
    with pytest.raises(HTTPException) as e:
        _notiz(_DB(), eintrag_id=99)
    assert e.value.status_code == 404


# --------------------------------------------------------------- Speichern
def test_notiz_allein_aenderbar_passwort_bleibt():
    """Der Kern von #162: Notiz ändern, ohne das Passwort zu kennen oder zu senden."""
    db = _DB(passwort='hunter2', notiz='alt')
    _update(db, notiz_aendern=True, notiz='neu')
    assert db.secret() == {'passwort': 'hunter2', 'notiz': 'neu'}


def test_passwortwechsel_loescht_die_notiz_nicht():
    """Der Dialog schickt beim reinen Passwortwechsel eine leere Notiz mit – die darf
    die gespeicherte nicht überschreiben."""
    db = _DB(passwort='alt', notiz='PIN 4711')
    _update(db, passwort_aendern=True, passwort='neu', notiz='')
    assert db.secret() == {'passwort': 'neu', 'notiz': 'PIN 4711'}


def test_beide_haelften_gleichzeitig_aenderbar():
    db = _DB(passwort='alt', notiz='alt')
    _update(db, passwort_aendern=True, passwort='neu', notiz_aendern=True, notiz='neue Notiz')
    assert db.secret() == {'passwort': 'neu', 'notiz': 'neue Notiz'}


def test_notiz_kann_geleert_werden():
    db = _DB(passwort='hunter2', notiz='PIN 4711')
    _update(db, notiz_aendern=True, notiz='')
    assert db.secret() == {'passwort': 'hunter2', 'notiz': ''}


def test_ohne_flags_bleibt_der_ciphertext_unangetastet():
    """Reine Metadaten-Änderung: kein neuer Ciphertext, damit auch ohne Vault-Key
    Titel/URL pflegbar bleiben."""
    db = _DB()
    vorher = db.tresor_eintraege.ciphertext
    _update(db, titel='Router neu')
    assert db.tresor_eintraege.updates == [None]
    assert db.tresor_eintraege.ciphertext is vorher


def test_teilaenderung_mit_altem_key_meldet_409_statt_datenverlust():
    """Passt der alte Ciphertext nicht mehr zum Key, lässt sich die andere Hälfte nicht
    übernehmen – dann lieber Konflikt melden als sie zu verlieren."""
    db = _DB(ciphertext=Fernet(Fernet.generate_key()).encrypt(b'{"passwort":"x","notiz":"y"}'))
    with pytest.raises(HTTPException) as e:
        _update(db, notiz_aendern=True, notiz='neu')
    assert e.value.status_code == 409
    assert db.tresor_eintraege.updates == []


def test_vollersatz_funktioniert_auch_mit_altem_key():
    """Werden beide Hälften ersetzt, wird das alte Geheimnis nicht gebraucht – so bleibt
    ein Eintrag nach einem Key-Wechsel reparierbar."""
    db = _DB(ciphertext=Fernet(Fernet.generate_key()).encrypt(b'{"passwort":"x","notiz":"y"}'))
    _update(db, passwort_aendern=True, passwort='neu', notiz_aendern=True, notiz='auch neu')
    assert db.secret() == {'passwort': 'neu', 'notiz': 'auch neu'}


def test_secret_aenderung_ohne_vault_key_meldet_503():
    db = _DB()
    cfg.settings.VAULT_KEY = ''
    with pytest.raises(HTTPException) as e:
        _update(db, notiz_aendern=True, notiz='neu')
    assert e.value.status_code == 503


def test_versionskonflikt_wird_gemeldet():
    db = _DB()
    with pytest.raises(HTTPException) as e:
        _update(db, notiz_aendern=True, notiz='neu', expected_version=99)
    assert e.value.status_code == 409
