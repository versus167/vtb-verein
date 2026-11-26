"""Passkey-Endpunkte (WebAuthn) mit einem Software-Authenticator und Stubs.

Der Authenticator hier tut, was ein Handy tut: Er erzeugt ein P-256-Schlüsselpaar,
baut authenticatorData und clientDataJSON und signiert. Damit laufen echte
Prüfungen durch py_webauthn – Origin, RP-ID, UV-Flag, Signatur, Zähler – ohne
Browser. Die DB-Seite (Einlösen, Widerruf, History, Prune) prüft
test_webauthn_integration gegen echtes PostgreSQL; hier steht ein Stub mit
derselben Semantik.
"""
import base64
import hashlib
import json
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cbor2  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi import BackgroundTasks, HTTPException, Response  # noqa: E402

from backend.api import passkeys as api  # noqa: E402
from backend.core.config import settings  # noqa: E402

RP_ID = settings.WEBAUTHN_RP_ID
ORIGIN = settings.WEBAUTHN_ORIGINS[0]

UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Handy:
    """Software-Authenticator (Plattform, mit Biometrie)."""

    def __init__(self, user_handle: bytes | None = None):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = hashlib.sha256(str(id(self)).encode()).digest()[:16]
        self.user_handle = user_handle
        self.zaehler = 0

    def _cose(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1,
                            -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    @staticmethod
    def _client_data(typ, options, origin):
        return json.dumps({"type": typ, "challenge": options["challenge"],
                           "origin": origin, "crossOrigin": False}).encode()

    def registrieren(self, options, *, flags=UP | UV | BE | BS, origin=ORIGIN):
        self.user_handle = ub64(options["user"]["id"])
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest()
                     + bytes([flags | AT]) + struct.pack(">I", self.zaehler)
                     + b"\x00" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id
                     + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options, origin)),
                "attestationObject": b64(att),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {}, "authenticatorAttachment": "platform",
        }

    def anmelden(self, options, *, flags=UP | UV | BE | BS, origin=ORIGIN, zaehler=None,
                 user_handle=None):
        self.zaehler = self.zaehler if zaehler is None else zaehler
        auth_data = (hashlib.sha256(options["rpId"].encode()).digest()
                     + bytes([flags]) + struct.pack(">I", self.zaehler))
        client_data = self._client_data("webauthn.get", options, origin)
        sig = self.key.sign(auth_data + hashlib.sha256(client_data).digest(),
                            ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(sig),
                "userHandle": b64(user_handle if user_handle is not None else self.user_handle),
            },
            "clientExtensionResults": {}, "authenticatorAttachment": "platform",
        }


# --------------------------------------------------------------------- Stubs

class _AccessLog:
    def __init__(self):
        self.eintraege = []
        self.zaehler = 0

    def log(self, event_type, **kw):
        self.eintraege.append({'event_type': event_type, **kw})

    def count(self, **kw):
        return self.zaehler

    def typen(self):
        return [e['event_type'] for e in self.eintraege]


class _WebAuthnRepo:
    """Gleiche Semantik wie WebAuthnRepository, im Speicher."""

    def __init__(self):
        self.creds = {}
        self.verbraucht = set()
        self.schreibzugriffe = 0

    def challenge_verbrauchen(self, challenge, zweck, user_id, expires_at):
        self.schreibzugriffe += 1
        h = hashlib.sha256(challenge).hexdigest()
        if h in self.verbraucht:
            return False
        self.verbraucht.add(h)
        return True

    def anlegen(self, user_id, credential_id, public_key, sign_count, transports,
                aaguid, backed_up, user_agent):
        cid = len(self.creds) + 1
        self.creds[cid] = dict(id=cid, user_id=user_id, credential_id=credential_id,
                               public_key=public_key, sign_count=sign_count,
                               transports=",".join(transports), backed_up=backed_up,
                               geraet_label="Safari auf iOS", last_used_at=None,
                               created_at=datetime.now(timezone.utc), revoked=False)
        return dict(self.creds[cid])

    def aktiv_nach_credential_id(self, credential_id):
        for c in self.creds.values():
            if c["credential_id"] == credential_id and not c["revoked"]:
                return dict(c)
        return None

    def list_active_for_user(self, user_id):
        return [dict(c) for c in self.creds.values() if c["user_id"] == user_id and not c["revoked"]]

    def credential_ids_for_user(self, user_id):
        return [c["credential_id"] for c in self.list_active_for_user(user_id)]

    def nach_login(self, cred_id, sign_count, backed_up):
        self.creds[cred_id].update(sign_count=sign_count, backed_up=backed_up,
                                   last_used_at=datetime.now(timezone.utc))

    def umbenennen(self, cred_id, user_id, label):
        c = self.creds.get(cred_id)
        if not c or c["user_id"] != user_id or c["revoked"]:
            return False
        c["geraet_label"] = label
        return True

    def widerrufen(self, cred_id, user_id, revoked_by):
        c = self.creds.get(cred_id)
        if not c or c["user_id"] != user_id or c["revoked"]:
            return False
        c["revoked"] = True
        return True


class _Sessions:
    def __init__(self, alter_min=1):
        self.alter_min = alter_min
        self.angelegt = []

    def get_active_session(self, sid):
        return {"created_at": datetime.now(timezone.utc) - timedelta(minutes=self.alter_min)}

    def create_session(self, **kw):
        self.angelegt.append(kw)
        return "sid-neu"


def _user(uid=5, aktiv=True):
    return SimpleNamespace(id=uid, username=f'maxi{uid}', active=aktiv, email='maxi@example.org',
                           role='user', permissions=set())


def _db(*users, session_alter_min=1):
    alle = {u.id: u for u in users}
    return SimpleNamespace(
        access_log_repository=_AccessLog(),
        webauthn=_WebAuthnRepo(),
        user_session_repository=_Sessions(session_alter_min),
        get_user_by_id=lambda uid: alle.get(uid),
        get_mitglied_by_user_id=lambda uid: None,
        update_last_login=lambda uid: None,
    )


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='198.51.100.7'),
                           headers={'user-agent': 'Mozilla/5.0 (iPhone) Safari'})


def _einrichten(db, user, handy=None, **kw):
    handy = handy or Handy()
    options = api.registrieren_optionen(user, "sid", db)
    antwort = handy.registrieren(options, **kw)
    bg = BackgroundTasks()
    info = api.registrieren(api.RegistrierenAntwort(credential=antwort), _request(), bg, user, db)
    return handy, info, bg


def _anmelden(db, handy, options=None, **kw):
    options = options or api.anmelden_optionen()
    resp = Response()
    ergebnis = api.anmelden(api.AnmeldenAntwort(credential=handy.anmelden(options, **kw)),
                            _request(), resp, db)
    return ergebnis, resp


@pytest.fixture(autouse=True)
def _umgebung(monkeypatch):
    monkeypatch.setattr(api, "_smtp_configured", lambda: True)
    monkeypatch.setattr(settings, "SECRET_KEY", "test-schluessel-mit-ausreichender-laenge")


# ------------------------------------------------------------- Einrichten

def test_einrichten_speichert_den_schluessel_und_kuendigt_mail_an():
    user = _user()
    db = _db(user)
    handy, info, bg = _einrichten(db, user)
    gespeichert = db.webauthn.creds[info.id]
    assert gespeichert["credential_id"] == b64(handy.cred_id)
    assert gespeichert["transports"] == "internal,hybrid"
    assert info.synchronisiert is True
    assert [t.func for t in bg.tasks] == [api._hinweis_mail]
    assert "passkey_registered" in db.access_log_repository.typen()


def test_optionen_verlangen_biometrie_und_eingebauten_sensor():
    user = _user()
    db = _db(user)
    o = api.registrieren_optionen(user, "sid", db)
    sel = o["authenticatorSelection"]
    assert sel["userVerification"] == "required"
    assert sel["residentKey"] == "required"
    assert sel["authenticatorAttachment"] == "platform"
    assert o["rp"]["id"] == RP_ID and ub64(o["user"]["id"]) == b"5"


def test_vorhandene_passkeys_werden_ausgeschlossen():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    o = api.registrieren_optionen(user, "sid", db)
    assert [c["id"] for c in o["excludeCredentials"]] == [b64(handy.cred_id)]


def test_einrichten_nur_kurz_nach_der_anmeldung():
    user = _user()
    db = _db(user, session_alter_min=api.REGISTRIERUNG_FENSTER_MIN + 1)
    with pytest.raises(HTTPException) as e:
        api.registrieren_optionen(user, "sid", db)
    assert e.value.status_code == 403 and e.value.detail["code"] == "neu_anmelden"


def test_einrichten_ohne_session_id_geht_nicht():
    user = _user()
    with pytest.raises(HTTPException) as e:
        api.registrieren_optionen(user, None, _db(user))
    assert e.value.status_code == 403


def test_einrichten_ohne_biometrie_wird_abgelehnt():
    user = _user()
    db = _db(user)
    with pytest.raises(HTTPException) as e:
        _einrichten(db, user, flags=UP)
    assert e.value.status_code == 400 and db.webauthn.creds == {}


def test_einrichten_von_fremder_seite_wird_abgelehnt():
    user = _user()
    db = _db(user)
    with pytest.raises(HTTPException):
        _einrichten(db, user, origin="https://boese.example")
    assert db.webauthn.creds == {}


def test_registrier_challenge_gilt_nur_fuer_ihr_konto():
    a, b = _user(5), _user(6)
    db = _db(a, b)
    options = api.registrieren_optionen(a, "sid", db)
    antwort = Handy().registrieren(options)
    with pytest.raises(HTTPException) as e:
        api.registrieren(api.RegistrierenAntwort(credential=antwort), _request(),
                         BackgroundTasks(), b, db)
    assert e.value.status_code == 400


def test_login_challenge_taugt_nicht_zum_einrichten():
    user = _user()
    db = _db(user)
    options = api.registrieren_optionen(user, "sid", db)
    options["challenge"] = api.anmelden_optionen()["challenge"]
    with pytest.raises(HTTPException):
        api.registrieren(api.RegistrierenAntwort(credential=Handy().registrieren(options)),
                         _request(), BackgroundTasks(), user, db)


def test_eigener_name_beim_einrichten():
    user = _user()
    db = _db(user)
    options = api.registrieren_optionen(user, "sid", db)
    info = api.registrieren(api.RegistrierenAntwort(credential=Handy().registrieren(options),
                                                    name="  Mein iPhone "),
                            _request(), BackgroundTasks(), user, db)
    assert info.name == "Mein iPhone"


def test_ohne_mailadresse_keine_mail():
    user = _user()
    user.email = None
    db = _db(user)
    _, _, bg = _einrichten(db, user)
    assert bg.tasks == []


# --------------------------------------------------------------- Anmelden

def test_anmelden_legt_session_an_und_fuehrt_zaehler():
    user = _user()
    db = _db(user)
    handy, info, _ = _einrichten(db, user)
    ergebnis, resp = _anmelden(db, handy, zaehler=3)
    assert ergebnis.id == user.id
    assert settings.COOKIE_NAME in resp.headers.get("set-cookie", "")
    assert db.user_session_repository.angelegt[0]["user_id"] == user.id
    assert db.webauthn.creds[info.id]["sign_count"] == 3
    assert "passkey_login" in db.access_log_repository.typen()


def test_challenge_eines_anderen_schluessels_ist_wertlos(monkeypatch):
    """Ein neuer SECRET_KEY (oder eine andere Instanz) entwertet ausgegebene Challenges."""
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    options = api.anmelden_optionen()
    monkeypatch.setattr(settings, "SECRET_KEY", "ein-ganz-anderes-geheimnis-mit-laenge")
    with pytest.raises(HTTPException):
        _anmelden(db, handy, options)


def test_login_optionen_schreiben_nichts_in_die_db():
    o = api.anmelden_optionen()
    assert o["userVerification"] == "required" and o["rpId"] == RP_ID
    assert o.get("allowCredentials", []) == []
    # anmelden_optionen bekommt gar keine DB – mehr Beweis braucht es nicht.


def test_challenge_nur_einmal():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    options = api.anmelden_optionen()
    _anmelden(db, handy, options)
    with pytest.raises(HTTPException) as e:
        _anmelden(db, handy, options)
    assert e.value.status_code == 401
    assert db.access_log_repository.eintraege[-1]["detail"] == "challenge"


def test_abgelaufene_challenge(monkeypatch):
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    monkeypatch.setattr(api, "CHALLENGE_MINUTEN", -1)
    with pytest.raises(HTTPException) as e:
        _anmelden(db, handy)
    assert e.value.status_code == 401
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('challenge')


def test_manipulierte_challenge():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    options = api.anmelden_optionen()
    roh = bytearray(ub64(options["challenge"]))
    roh[20] ^= 0x01            # Ablaufzeit verlängern wollen
    options["challenge"] = b64(bytes(roh))
    with pytest.raises(HTTPException):
        _anmelden(db, handy, options)
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('challenge')


def test_falsche_herkunft():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    with pytest.raises(HTTPException) as e:
        _anmelden(db, handy, origin="https://boese.example")
    assert e.value.status_code == 401
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('pruefung')
    assert db.access_log_repository.eintraege[-1]["event_type"] == "passkey_failed"


def test_ohne_biometrie_keine_anmeldung():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    with pytest.raises(HTTPException):
        _anmelden(db, handy, flags=UP | BE | BS)
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('pruefung')


def test_fremder_schluessel_scheitert_an_der_signatur():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    dieb = Handy(user_handle=handy.user_handle)
    dieb.cred_id = handy.cred_id
    with pytest.raises(HTTPException):
        _anmelden(db, dieb)
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('pruefung')


def test_zaehler_rueckwaerts_wird_abgelehnt():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    _anmelden(db, handy, zaehler=5)
    with pytest.raises(HTTPException):
        _anmelden(db, handy, zaehler=3)
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('pruefung')


def test_synchronisierte_passkeys_mit_zaehler_null_gehen_wiederholt():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    _anmelden(db, handy, zaehler=0)
    _anmelden(db, handy, zaehler=0)


def test_user_handle_muss_passen():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    with pytest.raises(HTTPException):
        _anmelden(db, handy, user_handle=b"6")
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('user_handle')


def test_entfernter_passkey_meldet_sich_verstaendlich():
    user = _user()
    db = _db(user)
    handy, info, _ = _einrichten(db, user)
    api.entfernen(info.id, _request(), user, db)
    with pytest.raises(HTTPException) as e:
        _anmelden(db, handy)
    assert e.value.status_code == 401 and "Login-Link" in e.value.detail


def test_inaktives_konto():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    user.active = False
    with pytest.raises(HTTPException):
        _anmelden(db, handy)
    assert db.access_log_repository.eintraege[-1]['detail'].startswith('user_inactive')


def test_ip_bremse():
    user = _user()
    db = _db(user)
    handy, _, _ = _einrichten(db, user)
    db.access_log_repository.zaehler = api.FEHLER_MAX_PER_IP
    with pytest.raises(HTTPException) as e:
        _anmelden(db, handy)
    assert e.value.status_code == 429


# --------------------------------------------------------------- Verwalten

def test_liste_umbenennen_entfernen():
    user, fremd = _user(5), _user(6)
    db = _db(user, fremd)
    _, info, _ = _einrichten(db, user)
    assert [p.id for p in api.meine_passkeys(user, db)] == [info.id]
    assert api.meine_passkeys(fremd, db) == []
    assert api.umbenennen(info.id, api.Umbenennen(name="Tablet"), user, db).name == "Tablet"
    with pytest.raises(HTTPException):
        api.umbenennen(info.id, api.Umbenennen(name="x"), fremd, db)
    with pytest.raises(HTTPException):
        api.entfernen(info.id, _request(), fremd, db)
    api.entfernen(info.id, _request(), user, db)
    assert api.meine_passkeys(user, db) == []
    assert "passkey_revoked" in db.access_log_repository.typen()


# ------------------------------------------------------------ Diagnose

def test_fehlschlag_beim_einrichten_steht_im_protokoll():
    user = _user()
    db = _db(user)
    with pytest.raises(HTTPException):
        _einrichten(db, user, origin="https://boese.example")
    eintrag = db.access_log_repository.eintraege[-1]
    assert eintrag["event_type"] == "passkey_register_failed"
    assert eintrag["detail"].startswith("server: InvalidRegistrationResponse")


def test_kaputte_antwort_gibt_400_statt_500():
    user = _user()
    db = _db(user)
    options = api.registrieren_optionen(user, "sid", db)
    antwort = Handy().registrieren(options)
    antwort["response"]["attestationObject"] = b64(b"kein cbor")
    with pytest.raises(HTTPException) as e:
        api.registrieren(api.RegistrierenAntwort(credential=antwort), _request(),
                         BackgroundTasks(), user, db)
    assert e.value.status_code == 400
    assert db.access_log_repository.typen()[-1] == "passkey_register_failed"


def test_abgelaufene_einrichtung_steht_im_protokoll(monkeypatch):
    user = _user()
    db = _db(user)
    monkeypatch.setattr(api, "CHALLENGE_MINUTEN", -1)
    with pytest.raises(HTTPException):
        _einrichten(db, user)
    assert db.access_log_repository.eintraege[-1]["detail"] == "server: challenge"


def test_geraetefehler_melden():
    user = _user()
    db = _db(user)
    api.einrichten_fehler_melden(
        api.ClientFehler(name="NotAllowedError", code="ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY",
                         message="The operation either timed out or was not allowed."),
        _request(), user, db)
    eintrag = db.access_log_repository.eintraege[-1]
    assert eintrag["event_type"] == "passkey_register_failed" and eintrag["user_id"] == user.id
    assert eintrag["detail"] == ("geraet: NotAllowedError / ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY: "
                                 "The operation either timed out or was not allowed.")


def test_geraetefehler_ohne_angaben():
    user = _user()
    db = _db(user)
    api.einrichten_fehler_melden(api.ClientFehler(), _request(), user, db)
    assert db.access_log_repository.eintraege[-1]["detail"] == "geraet: unbekannt"


def test_geraetefehler_laenge_begrenzt():
    with pytest.raises(Exception):
        api.ClientFehler(message="x" * 301)
