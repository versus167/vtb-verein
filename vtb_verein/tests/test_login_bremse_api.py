"""Anmelde-Bremse: der Passwort-Login bekommt eine Grenze für Fehlversuche.

Der Magic-Link war seit jeher doppelt begrenzt (pro IP und pro Empfänger), der
Passwort-Login gar nicht. bcrypt bremst zwar, aber gegen ein schwaches Passwort
reichen ein paar tausend Versuche — die hat man in Stunden.

Zwei Dinge sind hier wichtiger als die Zahlen selbst und deshalb eigens geprüft:

* Die Zählung vergleicht den Benutzernamen **exakt**. Der Protokollfilter
  (`count(username=…)`) macht das als Teilstring; darauf aufzusetzen hieße, dass
  Fehlversuche gegen „maximilian" das Konto „max" aussperren — ein Angreifer
  könnte fremde Konten sperren, ohne sie je anzutippen.
* Die Antwort ist für existierende und erfundene Konten dieselbe, sonst wäre die
  Bremse ein Auskunftsdienst darüber, welche Konten es gibt.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_tresor_api).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.api import auth as api  # noqa: E402


# --------------------------------------------------------------------- Stubs
class _AccessLog:
    """Protokoll-Stub, der wie das echte Repository exakt vergleicht."""

    def __init__(self, eintraege=()):
        # Einträge: (event_type, username, ip, zeitpunkt)
        self.eintraege = list(eintraege)

    def log(self, event_type, **kw):
        self.eintraege.append((event_type, kw.get('username'), kw.get('ip'),
                               datetime.now(timezone.utc)))

    @staticmethod
    def _norm(u):
        return (u or "").strip().lower()

    def count_login_failures(self, *, since, username=None, ip=None):
        grenze = datetime.fromisoformat(since)
        return sum(
            1 for (typ, u, i, ts) in self.eintraege
            if typ == 'login_failed' and ts >= grenze
            and (username is None or self._norm(u) == self._norm(username))
            and (ip is None or i == ip)
        )

    def last_login_success_at(self, username):
        treffer = [ts for (typ, u, _i, ts) in self.eintraege
                   if typ == 'login_success' and self._norm(u) == self._norm(username)]
        return max(treffer).isoformat() if treffer else None


def _db(eintraege=()):
    return SimpleNamespace(access_log_repository=_AccessLog(eintraege))


def _request(ip='198.51.100.7'):
    return SimpleNamespace(
        client=SimpleNamespace(host=ip),
        headers={'user-agent': 'pytest'},
    )


def _fehlversuche(n, username='max', ip='198.51.100.7', vor_minuten=1):
    ts = datetime.now(timezone.utc) - timedelta(minutes=vor_minuten)
    return [('login_failed', username, ip, ts) for _ in range(n)]


def _bremse(db, username='max', ip='198.51.100.7'):
    api._pruefe_login_bremse(db, _request(ip), username, ip)


# ------------------------------------------------------------- Konto-Grenze
def test_unterhalb_der_grenze_geht_der_login_durch():
    _bremse(_db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO - 1)))  # kein Fehler


def test_an_der_grenze_wird_abgewiesen():
    with pytest.raises(HTTPException) as e:
        _bremse(_db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO)))
    assert e.value.status_code == 429


def test_alte_fehlversuche_zaehlen_nicht_mehr():
    """Die Sperre läuft von selbst ab – niemand muss sie aufheben."""
    alt = _fehlversuche(api.LOGIN_MAX_PRO_KONTO,
                        vor_minuten=api.LOGIN_FENSTER_MIN + 5)
    _bremse(_db(alt))  # kein Fehler


def test_erfolgreiche_anmeldung_setzt_die_zaehlung_zurueck():
    """Wer sich viermal vertippt, sich anmeldet und später nochmal danebengreift,
    darf davon nicht ausgesperrt werden."""
    eintraege = _fehlversuche(api.LOGIN_MAX_PRO_KONTO, vor_minuten=10)
    eintraege.append(('login_success', 'max', '198.51.100.7',
                      datetime.now(timezone.utc) - timedelta(minutes=5)))
    eintraege += _fehlversuche(2, vor_minuten=1)
    _bremse(_db(eintraege))  # kein Fehler


# ------------------------------------------------ Exakter Namensvergleich
def test_fremdes_konto_kann_nicht_ueber_teiltreffer_gesperrt_werden():
    """Der Kern: Fehlversuche gegen „maximilian" dürfen „max" nicht sperren.
    Sonst wäre die Bremse selbst die Waffe – ein Angreifer könnte jedes Konto
    aussperren, dessen Name Teil eines anderen ist."""
    # Von einer anderen Adresse aus, damit hier wirklich nur die Konto-Dimension
    # geprüft wird und nicht versehentlich die IP-Grenze zuschlägt.
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO * 3, username='maximilian',
                           ip='203.0.113.9'))
    _bremse(db, username='max')  # kein Fehler


def test_gross_klein_und_leerzeichen_zaehlen_auf_dasselbe_konto():
    """Sonst umginge man die Sperre mit „Max " statt „max"."""
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO, username='MAX  '))
    with pytest.raises(HTTPException) as e:
        _bremse(db, username='max')
    assert e.value.status_code == 429


# ---------------------------------------------------------------- IP-Grenze
def test_ip_grenze_greift_ueber_konten_hinweg():
    """Das Durchprobieren vieler Konten von einer Quelle – jedes Konto für sich
    bleibt unter seiner Grenze."""
    eintraege = []
    for i in range(api.LOGIN_MAX_PRO_IP):
        eintraege += _fehlversuche(1, username=f'opfer{i}')
    with pytest.raises(HTTPException) as e:
        _bremse(_db(eintraege), username='noch_wer')
    assert e.value.status_code == 429


def test_ip_grenze_liegt_deutlich_ueber_der_konto_grenze():
    """Ein Verein sitzt zu großen Teilen hinter einer Adresse (Vereinsheim-WLAN,
    Mobilfunk-NAT). Eine enge IP-Grenze würde beim Trainingsabend die halbe
    Mannschaft aussperren."""
    assert api.LOGIN_MAX_PRO_IP >= 3 * api.LOGIN_MAX_PRO_KONTO


def test_ohne_ermittelbare_ip_greift_nur_die_konto_grenze():
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_IP, username='wer_anders', ip=None))
    api._pruefe_login_bremse(db, _request(), 'max', None)  # kein Fehler


# ------------------------------------------------------------ Keine Auskunft
def test_erfundenes_konto_wird_genauso_gebremst():
    """Sonst verriete allein der Statuscode, welche Konten existieren."""
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO, username='gibtsnicht'))
    with pytest.raises(HTTPException) as e:
        _bremse(db, username='gibtsnicht')
    assert e.value.status_code == 429


def test_abweisung_wird_protokolliert():
    """Ein Angriff soll im Zugriffsprotokoll sichtbar sein, nicht nur beim
    Angreifer."""
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO))
    with pytest.raises(HTTPException):
        _bremse(db)
    assert any(typ == 'login_rate_limited' for (typ, *_r) in db.access_log_repository.eintraege)


# ----------------------------------------------------- Endpunkt-Verdrahtung
def test_login_prueft_die_bremse_vor_der_passwortpruefung():
    """Reihenfolge ist Absicht: Ein abgewiesener Versuch darf keine bcrypt-Runde
    mehr kosten, sonst bleibt die Rechenlast beim Verteidiger."""
    db = _db(_fehlversuche(api.LOGIN_MAX_PRO_KONTO))
    db.users = SimpleNamespace(get_by_username=lambda u: None)

    gerufen = []

    class _Service:
        def __init__(self, _db):
            pass

        def authenticate(self, *a):
            gerufen.append(a)
            return None

    original = api.UserService
    api.UserService = _Service
    try:
        with pytest.raises(HTTPException) as e:
            api.login(_request(), SimpleNamespace(),
                      SimpleNamespace(username='max', password='geheim'),
                      remember_me=False, db=db)
        assert e.value.status_code == 429
        assert gerufen == [], "authenticate() darf gar nicht erst laufen"
    finally:
        api.UserService = original
