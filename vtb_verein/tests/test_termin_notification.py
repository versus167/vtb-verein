"""Tests für termin_notification_service (Opt-in-Kader-Benachrichtigung, #95).

Reine Unit-Tests ohne DB: Formatierung/Diff sind pure Funktionen, der Versand
wird über einen Stub-Datastore und gepatchtes NotificationService.send_notification_async
geprüft (Empfängerkreis: dedupliziert, ohne Auslöser, ohne inaktive/fehlende User).
"""
from types import SimpleNamespace

import pytest

from app.services import termin_notification_service as tn


def _termin(**kw):
    basis = dict(id=1, mannschaft_id=5, typ='training', beginn='2026-07-22T18:30',
                 ende=None, ort=None, treffpunkt=None, treffpunkt_zeit=None,
                 gegner=None, heim_auswaerts=None, beschreibung=None, status='geplant')
    basis.update(kw)
    return SimpleNamespace(**basis)


# ------------------------------------------------------------------ Formatierung
def test_format_datum_und_wandzeit():
    assert tn.format_datum('2026-07-22') == 'Mi., 22.07.2026'
    assert tn.format_wandzeit('2026-07-22T18:30') == 'Mi., 22.07.2026 18:30'
    assert tn.format_datum(None) == '–'
    assert tn.format_wandzeit(None) == '–'


def test_termin_titel():
    assert tn.termin_titel(_termin()) == 'Training'
    assert tn.termin_titel(_termin(typ='sonstiges')) == 'Sonstiges'
    spiel = _termin(typ='spiel', gegner='SV Gegner', heim_auswaerts='heim')
    assert tn.termin_titel(spiel) == 'Spiel vs. SV Gegner (H)'
    assert tn.termin_titel(_termin(typ='spiel')) == 'Spiel'


# -------------------------------------------------------------------------- Diff
def test_diff_termin_meldet_nur_geaenderte_felder():
    alt = _termin(ort='Halle 1')
    neu = _termin(ort='Halle 2', beginn='2026-07-23T19:00')
    zeilen = tn.diff_termin(alt, neu)
    assert zeilen == [
        'Beginn: Mi., 22.07.2026 18:30 → Do., 23.07.2026 19:00',
        'Ort: Halle 1 → Halle 2',
    ]


def test_diff_termin_leer_bei_no_op():
    t = _termin(ort='Halle 1', beschreibung='Bitte pünktlich')
    assert tn.diff_termin(t, _termin(ort='Halle 1', beschreibung='Bitte pünktlich')) == []


def test_diff_termin_none_wird_strich():
    zeilen = tn.diff_termin(_termin(), _termin(treffpunkt='Eingang'))
    assert zeilen == ['Treffpunkt: – → Eingang']


# ----------------------------------------------------------------------- Versand
class _StubDB:
    """Minimaler Datastore-Ausschnitt für notify_termin/notify_serie."""

    def __init__(self, kader_user_ids, users, gast_user_ids=()):
        self._users = users
        self.push = None
        self.termine = SimpleNamespace(
            list_kader_user_ids=lambda mid, tag=None: list(kader_user_ids))
        self.termin_zusagen = SimpleNamespace(
            list_user_ids_mit_zusage=lambda tid: list(gast_user_ids))
        self.users = SimpleNamespace(get_by_id=lambda uid: self._users.get(uid))

    def get_mannschaft(self, mannschaft_id):
        return SimpleNamespace(name='Erste')


@pytest.fixture
def gesendet(monkeypatch):
    from app.services.notification_service import NotificationService
    calls = []
    monkeypatch.setattr(
        NotificationService, 'send_notification_async',
        staticmethod(lambda user, title, message, push_service=None:
                     calls.append((user.id, title, message))))
    return calls


def test_notify_termin_empfaengerkreis(gesendet):
    users = {
        1: SimpleNamespace(id=1, active=True),    # Auslöser → übersprungen
        2: SimpleNamespace(id=2, active=True),
        3: SimpleNamespace(id=3, active=False),   # inaktiv → übersprungen
    }
    db = _StubDB(kader_user_ids=[1, 2, 2, 3, 4], users=users)  # 4 = kein User mehr
    tn.notify_termin(db, _termin(ort='Halle 1'), tn.AKTION_NEU, actor_user_id=1)
    assert [c[0] for c in gesendet] == [2]
    uid, title, message = gesendet[0]
    assert title == 'Neuer Termin – Erste'
    assert 'Training am Mi., 22.07.2026 18:30 (Erste)' in message
    assert 'Ort: Halle 1' in message


def test_notify_termin_erreicht_gaeste(gesendet):
    """Gäste (Zusage ohne Kader) gehören zum Empfängerkreis; Dubletten
    zwischen Kader- und Zusagen-Liste werden nur einmal beliefert."""
    users = {
        2: SimpleNamespace(id=2, active=True),
        5: SimpleNamespace(id=5, active=True),   # Gast
    }
    db = _StubDB(kader_user_ids=[2], users=users, gast_user_ids=[5, 2])
    tn.notify_termin(db, _termin(), tn.AKTION_ABGESAGT, actor_user_id=1)
    assert sorted(c[0] for c in gesendet) == [2, 5]


def test_notify_termin_geaendert_mit_diff(gesendet):
    db = _StubDB(kader_user_ids=[2], users={2: SimpleNamespace(id=2, active=True)})
    tn.notify_termin(db, _termin(), tn.AKTION_GEAENDERT, actor_user_id=1,
                     aenderungen=['Ort: Halle 1 → Halle 2'])
    _, title, message = gesendet[0]
    assert title == 'Termin geändert – Erste'
    assert 'Änderungen:' in message and '- Ort: Halle 1 → Halle 2' in message


def test_notify_termin_abgesagt_und_reaktiviert(gesendet):
    db = _StubDB(kader_user_ids=[2], users={2: SimpleNamespace(id=2, active=True)})
    tn.notify_termin(db, _termin(), tn.AKTION_ABGESAGT, actor_user_id=1)
    tn.notify_termin(db, _termin(), tn.AKTION_REAKTIVIERT, actor_user_id=1)
    assert gesendet[0][1] == 'Termin abgesagt – Erste'
    assert 'Der Termin wurde abgesagt.' in gesendet[0][2]
    assert gesendet[1][1] == 'Termin findet statt – Erste'
    assert 'findet wieder statt' in gesendet[1][2]


def test_notify_serie(gesendet):
    db = _StubDB(kader_user_ids=[2], users={2: SimpleNamespace(id=2, active=True)})
    serie = SimpleNamespace(mannschaft_id=5, typ='training', beginn_zeit='18:30',
                            ort='Halle 1', treffpunkt=None, treffpunkt_zeit=None,
                            beschreibung=None, start_datum='2026-07-21',
                            ende_datum='2026-12-15')
    tn.notify_serie(db, serie, actor_user_id=1)
    _, title, message = gesendet[0]
    assert title == 'Neue Terminserie – Erste'
    assert 'Training wöchentlich dienstags um 18:30 Uhr (Erste)' in message
    assert 'Ab Di., 21.07.2026 bis Di., 15.12.2026' in message
    assert 'Ort: Halle 1' in message


# ------------------------------------------- Offene Fragen aus dem Import (#95)
class _StubAbwDB(_StubDB):
    """Ergänzt den Stub um die Verwalter-Liste und den Termin-Zugriff."""

    def __init__(self, verwalter, users, termine):
        super().__init__(kader_user_ids=[], users=users)
        self._termine = termine
        self.termine = SimpleNamespace(
            list_verwalter_user_ids=lambda mid, tag=None: list(verwalter),
            get=lambda tid: self._termine.get(tid),
        )


def test_notify_abweichungen_geht_nur_an_betreuer_und_ul(gesendet):
    """Der Kader kann die Frage nicht beantworten – er bekommt sie auch nicht.

    Verwechselte man hier die Empfängerliste mit `list_kader_user_ids`, bekäme
    die halbe Mannschaft eine Aufforderung, die sie gar nicht ausführen darf.
    """
    users = {2: SimpleNamespace(id=2, active=True),
             3: SimpleNamespace(id=3, active=True)}
    db = _StubAbwDB(verwalter=[2, 3], users=users,
                    termine={7: _termin(id=7, typ='spiel', gegner='SV Gegner',
                                        heim_auswaerts='heim')})
    tn.notify_abweichungen(db, 5, [(7, 'beginn')], actor_user_id=1)
    assert sorted(c[0] for c in gesendet) == [2, 3]
    _, title, message = gesendet[0]
    assert title == 'Spielplan: Entscheidung nötig – Erste'
    assert 'Eine Ansetzung braucht eine Entscheidung' in message
    assert '- Spiel vs. SV Gegner (H) am Mi., 22.07.2026 18:30: Anstoß' in message


def test_notify_abweichungen_buendelt_mehrere_felder_je_termin(gesendet):
    """Zwei Felder am selben Termin sind eine Zeile, nicht zwei Meldungen."""
    db = _StubAbwDB(verwalter=[2], users={2: SimpleNamespace(id=2, active=True)},
                    termine={7: _termin(id=7), 8: _termin(id=8)})
    tn.notify_abweichungen(db, 5, [(7, 'beginn'), (7, 'ort'), (8, 'entfallen')],
                           actor_user_id=1)
    assert len(gesendet) == 1
    _, _, message = gesendet[0]
    assert '2 Ansetzungen brauchen eine Entscheidung' in message
    assert ': Anstoß, Spielort' in message
    assert ': nicht mehr in diesem Auszug' in message


def test_notify_abweichungen_ohne_verwalter_schweigt(gesendet):
    """Mannschaft ohne Betreuer/ÜL: kein Empfänger, keine Meldung ins Leere."""
    db = _StubAbwDB(verwalter=[], users={}, termine={7: _termin(id=7)})
    tn.notify_abweichungen(db, 5, [(7, 'beginn')], actor_user_id=1)
    assert gesendet == []


def test_notify_abweichungen_ueberspringt_verschwundene_termine(gesendet):
    """Zwischen Import und Versand gelöschter Termin darf nicht alles kippen."""
    db = _StubAbwDB(verwalter=[2], users={2: SimpleNamespace(id=2, active=True)},
                    termine={})
    tn.notify_abweichungen(db, 5, [(7, 'beginn')], actor_user_id=1)
    assert len(gesendet) == 1
    assert 'Bitte im Termin entscheiden' in gesendet[0][2]
