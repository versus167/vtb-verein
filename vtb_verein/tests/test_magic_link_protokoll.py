"""Das Zugriffsprotokoll nennt die angefragte Kennung (Magic-Link).

Vorher stand im Protokoll nur `match` oder `no_match`. Bei `no_match` gab es damit
gar keine Spur: Man sah, dass jemand Kennungen durchprobiert, aber nicht welche —
und bei einem Anwender, der partout keinen Link bekommt, war nicht zu erkennen,
womit er es versucht hat.

Zwei Eigenschaften sind dabei wesentlich und deshalb festgehalten:

* Die Kennung wird **unverändert** protokolliert. Groß-/Kleinschreibung spielt für
  den Abgleich zwar keine Rolle, ein Zeichen zu viel oder ein Leerzeichen im Wort
  aber sehr wohl — genau das sieht man nur am Original.
* Die Antwort nach außen bleibt einheitlich 200. Das Protokoll ist eine interne
  Auskunft, kein Kanal, über den sich vorhandene Konten erraten lassen.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import backend.core.config as cfg  # noqa: E402
from backend.api import auth as api  # noqa: E402


@pytest.fixture(autouse=True)
def smtp_konfiguriert():
    """Ohne SMTP antwortet der Endpunkt mit 503, bevor er irgendetwas protokolliert."""
    alt = (cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD)
    cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD = 'user', 'pass'
    yield
    cfg.settings.SMTP_USERNAME, cfg.settings.SMTP_PASSWORD = alt


@pytest.fixture(autouse=True)
def kein_mailversand(monkeypatch):
    monkeypatch.setattr(api, '_send_magic_link_email', lambda *a, **kw: None)


class _AccessLog:
    def __init__(self):
        self.eintraege = []

    def log(self, event_type, **kw):
        self.eintraege.append({'event_type': event_type, **kw})

    def count(self, **kw):
        return 0

    def detail(self, event_type):
        return next((e.get('detail') for e in self.eintraege
                     if e['event_type'] == event_type), None)


def _db(user=None):
    log = _AccessLog()
    return SimpleNamespace(
        access_log_repository=log,
        get_user_by_kennung=lambda kennung: user,
        auth_token_repository=SimpleNamespace(create_token=lambda **kw: 'tok'),
    )


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='198.51.100.7'),
                           headers={'user-agent': 'pytest'})


def _user(username='maxi', aktiv=True, email='maxi@example.org'):
    return SimpleNamespace(id=5, username=username, active=aktiv, email=email)


def _anfrage(db, kennung):
    return api.request_magic_link(api.MagicLinkRequest(kennung=kennung), _request(), db)


# ------------------------------------------------------------------ Protokoll
def test_treffer_nennt_die_adresse():
    db = _db(_user())
    _anfrage(db, 'maxi@example.org')
    assert db.access_log_repository.detail('magic_link_request') == 'match · maxi@example.org'


def test_fehlschlag_nennt_die_adresse():
    """Der eigentliche Gewinn: Bei no_match ist die Adresse die einzige Spur."""
    db = _db(None)
    _anfrage(db, 'gibtsnicht@example.org')
    assert db.access_log_repository.detail('magic_link_request') == \
        'no_match · gibtsnicht@example.org'


def test_inaktives_konto_gilt_als_fehlschlag():
    db = _db(_user(aktiv=False))
    _anfrage(db, 'ruhend@example.org')
    assert db.access_log_repository.detail('magic_link_request').startswith('no_match ·')


def test_adresse_wird_unveraendert_protokolliert():
    """Tippfehler und Leerzeichen sind der häufigste Grund für ein unerwartetes
    no_match und müssen deshalb im Original sichtbar bleiben."""
    db = _db(None)
    _anfrage(db, '  Maxi@Example.ORG ')
    assert db.access_log_repository.detail('magic_link_request') == \
        'no_match ·   Maxi@Example.ORG '


def test_antwort_bleibt_fuer_beide_faelle_gleich():
    """Das Protokoll ist eine interne Auskunft – nach außen darf sich nichts
    unterscheiden, sonst wäre der Endpunkt ein Verzeichnisdienst."""
    assert _anfrage(_db(_user()), 'da@example.org') == \
        _anfrage(_db(None), 'nicht-da@example.org')


def test_username_steht_weiterhin_im_eigenen_feld():
    """Die Kennung ergänzt das Protokoll, sie ersetzt nichts."""
    db = _db(_user('maxi'))
    _anfrage(db, 'maxi@example.org')
    eintrag = db.access_log_repository.eintraege[0]
    assert eintrag['username'] == 'maxi' and eintrag['user_id'] == 5


# ------------------------------------------------------- Kennung = Name o. Mail
def test_benutzername_fuehrt_zum_konto():
    """Der Kern der Erweiterung: Benutzername und Adresse sind beide eindeutig,
    also taugt auch der Benutzername als Kennung für den Login-Link."""
    db = _db(_user('maxi'))
    _anfrage(db, 'maxi')
    assert db.access_log_repository.detail('magic_link_request') == 'match · maxi'


def test_link_geht_an_die_hinterlegte_adresse(monkeypatch):
    """Der Empfänger steht am Konto, nie in der Eingabe – sonst wäre der
    Benutzername eines anderen genug, um sich dessen Link schicken zu lassen."""
    empfaenger = []
    monkeypatch.setattr(api, '_send_magic_link_email',
                        lambda ziel, *a: empfaenger.append(ziel))
    _anfrage(_db(_user('maxi', email='maxi@example.org')), 'maxi')
    assert empfaenger == ['maxi@example.org']


def test_konto_ohne_adresse_bekommt_nichts():
    """Ein Namensträger ohne App-Zugang (email IS NULL) ist über den Benutzernamen
    jetzt auffindbar – zuzustellen gibt es trotzdem nichts."""
    db = _db(_user('platzwart', email=None))
    _anfrage(db, 'platzwart')
    assert db.access_log_repository.detail('magic_link_request') == 'no_match · platzwart'


def test_getroffenes_konto_steht_auch_ohne_versand_im_protokoll():
    """Sonst ließe sich hinterher nicht erklären, warum jemand keinen Link bekam."""
    db = _db(_user('platzwart', email=None))
    _anfrage(db, 'platzwart')
    eintrag = db.access_log_repository.eintraege[0]
    assert eintrag['username'] == 'platzwart' and eintrag['user_id'] == 5


def test_benutzername_wird_nicht_als_adresse_geprueft():
    """Ohne @ ist ein Benutzername gemeint – die Adress-Formregel darf ihn nicht
    mit 422 abweisen."""
    _anfrage(_db(None), 'gibtsnicht')  # kein Fehler


def test_vertippte_adresse_bekommt_weiterhin_sofort_einen_hinweis():
    """Mit @ ist eine Adresse gemeint – ein Vertipper soll nicht in der
    beruhigenden 200 verschwinden."""
    with pytest.raises(HTTPException) as e:
        _anfrage(_db(None), 'maxi@web')
    assert e.value.status_code == 422


def test_leere_kennung_wird_abgewiesen():
    with pytest.raises(HTTPException) as e:
        _anfrage(_db(None), '   ')
    assert e.value.status_code == 422


# ------------------------------------------------------------------- Bremsen
def test_ip_bremse_nennt_die_adresse():
    db = _db(None)
    db.access_log_repository.count = lambda **kw: api.MAGIC_LINK_MAX_PER_IP
    with pytest.raises(HTTPException) as e:
        _anfrage(db, 'probe@example.org')
    assert e.value.status_code == 429
    assert db.access_log_repository.detail('magic_link_rate_limited') == \
        'ip · probe@example.org'


def test_empfaenger_bremse_nennt_die_adresse():
    db = _db(_user())
    # Erst das IP-Gate passieren lassen, dann beim Empfänger-Limit anschlagen.
    db.access_log_repository.count = lambda **kw: (
        0 if kw.get('ip') else api.MAGIC_LINK_MAX_PER_USER + 1)
    _anfrage(db, 'vielgefragt@example.org')
    assert db.access_log_repository.detail('magic_link_rate_limited') == \
        'user · vielgefragt@example.org'


# ------------------------------------------------------------------- Eingabe
def test_uebermaessig_lange_adresse_wird_abgewiesen():
    """Die Kennung landet im dauerhaft aufbewahrten Protokoll – ohne Obergrenze
    ließe sich das mit beliebig langen Zeichenketten vollschreiben."""
    with pytest.raises(ValidationError):
        api.MagicLinkRequest(kennung='x' * 255 + '@example.org')


def test_uebliche_adresse_passt_durch():
    assert api.MagicLinkRequest(kennung='vorname.nachname@sehr-langer-verein.example')


def test_alter_feldname_email_bleibt_gueltig():
    """Eine im Browser noch nicht neu geladene App schickt weiter `email` – die
    darf sich nicht plötzlich nicht mehr anmelden können."""
    assert api.MagicLinkRequest(email='maxi@example.org').kennung == 'maxi@example.org'
