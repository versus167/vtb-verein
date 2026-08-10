"""Kalender-Abo-Endpunkte (#153, backend/api/kalender.py).

Der Feed ist der einzige unauthentifizierte Endpunkt der App — der Token in der
URL ist die ganze Anmeldung. Geprüft wird deshalb vor allem, was daraus folgt:
Ein unbekannter Token bekommt nichts zu sehen, der Feed liefert ausschließlich
die Termine des Token-Inhabers, und der Token darf nicht im Access-Log landen.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_zugang_freischalten_api).
"""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from backend.api import kalender as api  # noqa: E402


# --------------------------------------------------------------------- Stubs

class FakeAboRepo:
    def __init__(self, abo=None, token_user=None):
        self._abo = abo
        self._token_user = token_user or {}
        self.erzeugt_fuer = []
        self.widerrufen_fuer = []

    def get_for_user(self, user_id):
        return self._abo

    def create_for_user(self, user_id, actor):
        self.erzeugt_fuer.append((user_id, actor))
        return "TOKEN123"

    def revoke_for_user(self, user_id, actor):
        self.widerrufen_fuer.append((user_id, actor))
        return self._abo is not None

    def resolve_token(self, token):
        return self._token_user.get(token)


class FakeAccessLog:
    def __init__(self):
        self.eintraege = []

    def log(self, event_type, **kw):
        self.eintraege.append((event_type, kw))


class FakeTerminRepo:
    def __init__(self, termine_je_user=None):
        self._termine = termine_je_user or {}
        self.aufrufe = []

    def list_for_user(self, user_id, von=None, bis=None):
        self.aufrufe.append((user_id, von, bis))
        return self._termine.get(user_id, [])


def _db(abo=None, token_user=None, termine=None, mitglied_id=None, antworten=None,
        users=None, alle_abos=None):
    """`mitglied_id=None` = User ohne Mitglied (dann gibt es keine eigene Antwort)."""
    repo = FakeAboRepo(abo, token_user)
    repo.alle = list(alle_abos or [])
    repo.list_all = lambda: repo.alle
    return SimpleNamespace(
        kalender_abos=repo,
        termine=FakeTerminRepo(termine),
        access_log_repository=FakeAccessLog(),
        get_user_by_id=lambda uid: (users or {}).get(uid),
        get_mitglied_by_user_id=lambda uid: (SimpleNamespace(id=mitglied_id)
                                             if mitglied_id else None),
        termin_zusagen=SimpleNamespace(
            answer_for=lambda mid, ids: dict(antworten or {})),
    )


def _user(uid=5, username='spieler', perms=()):
    return SimpleNamespace(id=uid, username=username,
                           has_permission=lambda p: p in perms)


def _request():
    return SimpleNamespace(headers={"user-agent": "pytest"},
                           client=SimpleNamespace(host="1.2.3.4"))


def _termin(**kw):
    basis = {
        'id': 1, 'version': 1, 'typ': 'training', 'beginn': '2026-08-30T13:00',
        'ende': None, 'ort': None, 'gegner': None, 'heim_auswaerts': None,
        'status': 'geplant', 'beschreibung': None, 'treffpunkt': None,
        'treffpunkt_zeit': None, 'mannschaft_name': 'AH',
        'spielstaette_name': None, 'spielstaette_strasse': None,
        'spielstaette_plz': None, 'spielstaette_ort': None,
        'spielstaette_untergrund': None,
    }
    basis.update(kw)
    return basis


@pytest.fixture(autouse=True)
def basis_url(monkeypatch):
    monkeypatch.setattr(api.settings, "BASE_URL", "https://app.example.de", raising=False)
    monkeypatch.setattr(api.settings, "VEREIN_KURZ", "SVN", raising=False)


# ----------------------------------------------------------------- Abo-Pflege

def test_ohne_abo_meldet_der_status_nur_das():
    assert api.abo_status(_user(), _db()) == {"vorhanden": False}


def test_status_zeigt_erstellung_und_letzten_abruf():
    db = _db(abo={"created_at": "2026-08-01T10:00:00+00:00",
                  "letzter_abruf_at": "2026-08-09T04:00:00+00:00", "abrufe": 12})
    ergebnis = api.abo_status(_user(), db)
    assert ergebnis["vorhanden"] is True
    assert ergebnis["abrufe"] == 12
    assert ergebnis["letzter_abruf"] == "2026-08-09T04:00:00+00:00"


def test_status_gibt_die_adresse_nicht_heraus():
    """In der DB liegt nur der Hash – die URL kann es hier gar nicht geben."""
    db = _db(abo={"created_at": "x", "letzter_abruf_at": None, "abrufe": 0})
    assert not any("url" in k for k in api.abo_status(_user(), db))


def test_erzeugen_liefert_feed_und_webcal_adresse():
    db = _db()
    ergebnis = api.abo_erzeugen(_request(), _user(uid=5, username='spieler'), db)
    assert ergebnis["url"] == "https://app.example.de/api/kalender/TOKEN123.ics"
    # webcal:// öffnet auf iOS/macOS den Abo-Dialog statt eines einmaligen Downloads
    assert ergebnis["webcal_url"] == "webcal://app.example.de/api/kalender/TOKEN123.ics"
    assert db.kalender_abos.erzeugt_fuer == [(5, 'spieler')]


def test_widerrufen_reicht_den_handelnden_durch():
    db = _db(abo={"created_at": "x", "letzter_abruf_at": None, "abrufe": 0})
    assert api.abo_widerrufen(_request(), _user(uid=5, username='spieler'), db) \
        == {"widerrufen": True}
    assert db.kalender_abos.widerrufen_fuer == [(5, 'spieler')]


def test_widerrufen_ohne_abo_meldet_false():
    assert api.abo_widerrufen(_request(), _user(), _db()) == {"widerrufen": False}


# ------------------------------------------------------------------ Protokoll

def test_erzeugen_wird_protokolliert():
    """Ein Feed-Link ist eine dauerhafte, anmeldungsfreie Leseberechtigung –
    seine Vergabe gehört ins Protokoll."""
    db = _db()
    api.abo_erzeugen(_request(), _user(username='spieler'), db)
    typ, kw = db.access_log_repository.eintraege[0]
    assert typ == "kalender_abo_erzeugt"
    assert kw["category"] == "kalender"
    assert kw["username"] == "spieler"
    assert kw["ip"] == "1.2.3.4"


def test_neu_erzeugen_ist_im_protokoll_unterscheidbar():
    db = _db(abo={"created_at": "x", "letzter_abruf_at": None, "abrufe": 0})
    api.abo_erzeugen(_request(), _user(), db)
    assert "alte widerrufen" in db.access_log_repository.eintraege[0][1]["detail"]


def test_widerruf_wird_protokolliert():
    db = _db(abo={"created_at": "x", "letzter_abruf_at": None, "abrufe": 0})
    api.abo_widerrufen(_request(), _user(), db)
    assert db.access_log_repository.eintraege[0][0] == "kalender_abo_widerrufen"


def test_widerruf_ohne_abo_schreibt_nichts():
    """Nichts passiert, nichts zu protokollieren – sonst stünde Rauschen drin."""
    db = _db()
    api.abo_widerrufen(_request(), _user(), db)
    assert db.access_log_repository.eintraege == []


def test_abrufe_werden_nicht_protokolliert():
    """Kalender fragen alle paar Stunden nach; jeder Poll im Protokoll wäre
    Rauschen. Wann zuletzt abgerufen wurde, steht am Abo."""
    db = _db(token_user={"GUT": 42}, termine={42: []})
    api.feed("GUT", db)
    assert db.access_log_repository.eintraege == []


# ------------------------------------------------------------------- Aufsicht

def test_uebersicht_braucht_das_protokoll_recht():
    with pytest.raises(HTTPException) as e:
        api.abos_uebersicht(_user(), _db())
    assert e.value.status_code == 403


def test_uebersicht_listet_die_abos():
    db = _db(alle_abos=[{"id": 1, "user_id": 42, "username": "spieler",
                         "abrufe": 7, "letzter_abruf_at": "2026-08-09T04:00:00+00:00"}])
    ergebnis = api.abos_uebersicht(_user(perms=('system.protokoll',)), db)
    assert ergebnis[0]["username"] == "spieler"


def test_uebersicht_gibt_keine_adressen_heraus():
    """In der DB liegt nur der Hash – hier darf nichts Token-Artiges auftauchen."""
    db = _db(alle_abos=[{"id": 1, "user_id": 42, "username": "spieler",
                         "abrufe": 0, "letzter_abruf_at": None}])
    ergebnis = api.abos_uebersicht(_user(perms=('system.protokoll',)), db)
    assert not any('token' in k or 'url' in k for k in ergebnis[0])


def test_fremdwiderruf_braucht_das_protokoll_recht():
    db = _db(users={42: SimpleNamespace(id=42, username='spieler')})
    with pytest.raises(HTTPException) as e:
        api.abo_fremd_widerrufen(42, _request(), _user(), db)
    assert e.value.status_code == 403


def test_fremdwiderruf_nennt_den_betroffenen_im_protokoll():
    db = _db(abo={"created_at": "x", "letzter_abruf_at": None, "abrufe": 0},
             users={42: SimpleNamespace(id=42, username='spieler')})
    api.abo_fremd_widerrufen(42, _request(), _user(username='chef',
                                                   perms=('system.protokoll',)), db)
    typ, kw = db.access_log_repository.eintraege[0]
    # Protokolliert wird der Handelnde, der Betroffene steht im Detail (wie bei
    # den Zugängen) – so beantwortet das Protokoll „wer hat wem was entzogen".
    assert typ == "kalender_abo_widerrufen"
    assert kw["username"] == "chef"
    assert "spieler" in kw["detail"]


def test_fremdwiderruf_bei_unbekanntem_benutzer_ist_404():
    db = _db(users={})
    with pytest.raises(HTTPException) as e:
        api.abo_fremd_widerrufen(99, _request(), _user(perms=('system.protokoll',)), db)
    assert e.value.status_code == 404


def test_fremdwiderruf_ohne_aktives_abo_ist_404():
    db = _db(users={42: SimpleNamespace(id=42, username='spieler')})   # abo=None
    with pytest.raises(HTTPException) as e:
        api.abo_fremd_widerrufen(42, _request(), _user(perms=('system.protokoll',)), db)
    assert e.value.status_code == 404


# ---------------------------------------------------------------------- Feed

def test_unbekannter_token_bekommt_404():
    with pytest.raises(HTTPException) as e:
        api.feed("erfunden", _db())
    assert e.value.status_code == 404


def test_feed_liefert_die_termine_des_token_inhabers():
    db = _db(token_user={"GUT": 42}, termine={42: [_termin(id=9)]})
    antwort = api.feed("GUT", db)
    assert antwort.media_type.startswith("text/calendar")
    text = antwort.body.decode("utf-8")
    assert "UID:termin-9@app.example.de" in text
    # Genau die Abfrage von „Meine Termine" – keine zweite Rechtelogik
    assert db.termine.aufrufe[0][0] == 42


def test_feed_holt_ein_begrenztes_zeitfenster():
    db = _db(token_user={"GUT": 42}, termine={42: []})
    api.feed("GUT", db)
    _, von, bis = db.termine.aufrufe[0]
    assert von < bis
    assert von is not None and bis is not None


def test_feed_wird_nicht_zwischengespeichert():
    """Persönliche Daten hinter einem Token gehören in keinen geteilten Cache."""
    db = _db(token_user={"GUT": 42}, termine={42: []})
    antwort = api.feed("GUT", db)
    assert "no-store" in antwort.headers["cache-control"]


def test_feed_traegt_die_eigene_absage_nach():
    """Ohne diesen Schritt sähe ein Training, für das man abgesagt hat, im
    Kalender aus wie jedes andere."""
    db = _db(token_user={"GUT": 42}, termine={42: [_termin(id=9)]},
             mitglied_id=3, antworten={9: 'ab'})
    text = api.feed("GUT", db).body.decode("utf-8")
    assert "SUMMARY:Nicht dabei: Training AH" in text


def test_feed_ohne_mitglied_kommt_ohne_antwort_aus():
    """Ein User ohne verknüpftes Mitglied kann nicht zu-/absagen – der Feed
    darf daran nicht scheitern."""
    db = _db(token_user={"GUT": 42}, termine={42: [_termin(id=9)]}, mitglied_id=None)
    text = api.feed("GUT", db).body.decode("utf-8")
    assert "SUMMARY:Training AH" in text


def test_feed_kalendername_traegt_den_verein():
    db = _db(token_user={"GUT": 42}, termine={42: []})
    text = api.feed("GUT", db).body.decode("utf-8")
    assert "X-WR-CALNAME:Meine Termine (SVN)" in text


# ------------------------------------------------------------- Access-Log

def _log_record(pfad):
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                               '%s - "%s %s HTTP/%s" %d', None, None)
    record.args = ("1.2.3.4:5", "GET", pfad, "1.1", 200)
    return record


def test_access_log_maskiert_den_token():
    """Der Token steht in der URL – im Log wäre er im Klartext lesbar."""
    record = _log_record("/api/kalender/GEHEIM123.ics")
    assert api.AccessLogTokenFilter().filter(record) is True
    assert record.args[2] == "/api/kalender/***.ics"
    assert record.args[4] == 200      # Statuscode bleibt sichtbar


def test_access_log_laesst_andere_pfade_unangetastet():
    record = _log_record("/api/termine/meine")
    api.AccessLogTokenFilter().filter(record)
    assert record.args[2] == "/api/termine/meine"
