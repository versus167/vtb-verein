"""API-Verdrahtung des `benachrichtigen`-Flags (backend/api/termine.py).

Ruft die Endpunkt-Funktionen direkt mit Stub-DB/-User auf (Muster wie
test_ul_stunden_meine) und prüft: Flag an → notify_termin mit korrekter
Aktion (und beim Update mit echtem Diff), Flag aus bzw. No-Op-Update →
kein Versand. Der eigentliche Nachrichtentext ist in
test_termin_notification abgedeckt.
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

from app.models.termin import Termin  # noqa: E402
from app.services import termin_notification_service as tn  # noqa: E402
from backend.api import termine as api  # noqa: E402


def _termin(**kw):
    basis = dict(id=1, mannschaft_id=5, serie_id=None, typ='training',
                 beginn='2026-07-22T18:30', ende=None, ort='Halle 1',
                 treffpunkt=None, treffpunkt_zeit=None, gegner=None,
                 heim_auswaerts=None, extern_ref=None, status='geplant',
                 beschreibung=None, version=1, created_at='x', created_by='t',
                 updated_at='x', updated_by='t')
    basis.update(kw)
    return Termin(**basis)


class _TermineRepo:
    def __init__(self, termin):
        self.termin = termin

    def get(self, termin_id):
        return self.termin

    def create(self, mannschaft_id, typ, beginn, ende, ort, treffpunkt,
               treffpunkt_zeit, gegner, heim_auswaerts, beschreibung, created_by):
        self.termin = _termin(mannschaft_id=mannschaft_id, typ=typ, beginn=beginn,
                              ende=ende, ort=ort, treffpunkt=treffpunkt,
                              treffpunkt_zeit=treffpunkt_zeit, gegner=gegner,
                              heim_auswaerts=heim_auswaerts, beschreibung=beschreibung)
        return self.termin

    def update(self, termin_id, typ, beginn, ende, ort, treffpunkt,
               treffpunkt_zeit, gegner, heim_auswaerts, beschreibung,
               updated_by, expected_version):
        self.termin = replace(self.termin, typ=typ, beginn=beginn, ende=ende,
                              ort=ort, treffpunkt=treffpunkt,
                              treffpunkt_zeit=treffpunkt_zeit, gegner=gegner,
                              heim_auswaerts=heim_auswaerts,
                              beschreibung=beschreibung,
                              version=self.termin.version + 1)
        return True

    def set_status(self, termin_id, status, updated_by, expected_version):
        self.termin = replace(self.termin, status=status,
                              version=self.termin.version + 1)
        return True


class _DB:
    def __init__(self, termin):
        self.termine = _TermineRepo(termin)

    def get_mannschaft(self, mannschaft_id):
        return SimpleNamespace(id=mannschaft_id, name='Erste')


_ADMIN = SimpleNamespace(role='admin', username='chef', id=1,
                         has_permission=lambda p: True)


@pytest.fixture
def notify_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api.terminmeldung, 'notify_termin',
        lambda db, termin, aktion, actor_user_id, aenderungen=None:
            calls.append((aktion, actor_user_id, aenderungen)))
    return calls


def _update_payload(t, benachrichtigen, **kw):
    felder = dict(typ=t.typ, beginn=t.beginn, ende=t.ende, ort=t.ort,
                  treffpunkt=t.treffpunkt, treffpunkt_zeit=t.treffpunkt_zeit,
                  gegner=t.gegner, heim_auswaerts=t.heim_auswaerts,
                  beschreibung=t.beschreibung)
    felder.update(kw)
    return api.TerminUpdate(expected_version=t.version,
                            benachrichtigen=benachrichtigen, **felder)


def test_create_mit_flag_benachrichtigt(notify_calls):
    db = _DB(None)
    data = api.TerminCreate(beginn='2026-07-22T18:30', benachrichtigen=True)
    api.create_termin(5, data, _ADMIN, db)
    assert notify_calls == [(tn.AKTION_NEU, _ADMIN.id, None)]


def test_create_ohne_flag_schweigt(notify_calls):
    api.create_termin(5, api.TerminCreate(beginn='2026-07-22T18:30'), _ADMIN, _DB(None))
    assert notify_calls == []


def test_update_mit_flag_meldet_diff(notify_calls):
    t = _termin()
    db = _DB(t)
    api.update_termin(t.id, _update_payload(t, True, ort='Halle 2'), _ADMIN, db)
    aktion, actor, aenderungen = notify_calls[0]
    assert aktion == tn.AKTION_GEAENDERT and actor == _ADMIN.id
    assert aenderungen == ['Ort: Halle 1 → Halle 2']


def test_update_noop_schweigt_trotz_flag(notify_calls):
    t = _termin()
    api.update_termin(t.id, _update_payload(t, True), _ADMIN, _DB(t))
    assert notify_calls == []


def test_update_ohne_flag_schweigt(notify_calls):
    t = _termin()
    api.update_termin(t.id, _update_payload(t, False, ort='Halle 2'), _ADMIN, _DB(t))
    assert notify_calls == []


def test_absagen_und_reaktivieren_mit_flag(notify_calls):
    t = _termin()
    db = _DB(t)
    api.absagen(t.id, api.TerminAktion(expected_version=1, benachrichtigen=True),
                _ADMIN, db)
    api.reaktivieren(t.id, api.TerminAktion(expected_version=2, benachrichtigen=True),
                     _ADMIN, db)
    assert [c[0] for c in notify_calls] == [tn.AKTION_ABGESAGT, tn.AKTION_REAKTIVIERT]


def test_absagen_ohne_flag_schweigt(notify_calls):
    t = _termin()
    api.absagen(t.id, api.TerminAktion(expected_version=1), _ADMIN, _DB(t))
    assert notify_calls == []
