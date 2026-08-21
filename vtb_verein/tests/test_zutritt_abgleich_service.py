"""Soll-Ist-Abgleich der IC-Karten (app/services/zutritt_abgleich_service.py).

Der Sync spiegelt das Ist, aber verglichen hat es bisher niemand. Geprüft wird hier
die Vergleichslogik selbst – reine Funktion über zwei Listen, ohne DB und ohne Cloud –
plus die Wiederholungssperre der Meldung: Ein Befund, der eine Woche offen steht, darf
den Admins nicht 28 Nachrichten schicken.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import zutritt_abgleich_service as abg  # noqa: E402

_JETZT = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
_JETZT_MS = int(_JETZT.timestamp() * 1000)


def _iso(**delta) -> str:
    return (_JETZT + timedelta(**delta)).isoformat()


def _ber(**kw):
    """Eine Berechtigungszeile, wie sie das Repository liefert (inkl. Anzeige-JOINs)."""
    daten = dict(id=1, chip_id=7, schloss_id=1, ttlock_card_id=9001,
                 gueltig_von=None, gueltig_bis=None, sync_status='aktiv',
                 schloss_name='Halle', chip_bezeichnung='Chip blau',
                 kartennummer='818229331', chip_status='aktiv',
                 mitglied_vorname=None, mitglied_nachname=None)
    daten.update(kw)
    return SimpleNamespace(**daten)


def _karte(**kw):
    """Eine gespiegelte IC-Karte (tuer_credential, typ='ic')."""
    daten = dict(schloss_id=1, ttlock_credential_id=9001, name='Chip blau',
                 detail='818229331', gueltig_von=None, gueltig_bis=None,
                 schloss_name='Halle', gesehen_am=_iso())
    daten.update(kw)
    return SimpleNamespace(**daten)


def _gesperrte_karte(**kw):
    """Karte mit dem Fenster, das `sperr_fenster` erzeugt: komplett in der Vergangenheit."""
    return _karte(gueltig_von=_iso(minutes=-2), gueltig_bis=_iso(minutes=-1), **kw)


def _arten(befunde):
    return [b['art'] for b in befunde]


class TestAllesInOrdnung:
    def test_unbefristete_karte_am_schloss_ist_kein_befund(self):
        assert abg.befunde([_ber()], [_karte()], jetzt_ms=_JETZT_MS) == []

    def test_gesperrter_chip_mit_abgelaufener_karte_ist_kein_befund(self):
        """Genau das ist das Ziel des Sperrens – kein Grund, jemanden zu behelligen."""
        befunde = abg.befunde([_ber(chip_status='verloren')], [_gesperrte_karte()],
                              jetzt_ms=_JETZT_MS)
        assert befunde == []

    def test_gleiches_fenster_auf_die_sekunde_genau_passt(self):
        """ISO → ms → ISO lässt Sekunden wandern; das ist keine Abweichung."""
        befunde = abg.befunde(
            [_ber(gueltig_bis='2026-12-31T23:00:00+00:00')],
            [_karte(gueltig_bis='2026-12-31T23:00:30+00:00')], jetzt_ms=_JETZT_MS)
        assert befunde == []


class TestSperrluecke:
    def test_gesperrter_chip_mit_gueltiger_karte_ist_kritisch(self):
        """Der Fall, auf den es ankommt: Er steht als verloren in der Liste und öffnet."""
        befunde = abg.befunde([_ber(chip_status='verloren')], [_karte()], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_SPERRE_OFFEN]
        assert befunde[0]['kritisch'] is True
        assert 'verloren' in befunde[0]['text'] and 'Halle' in befunde[0]['text']

    def test_aktiver_chip_mit_abgelaufener_karte_bleibt_stumm(self):
        befunde = abg.befunde([_ber()], [_gesperrte_karte()], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_SPERRE_HAENGT]
        assert befunde[0]['kritisch'] is False

    def test_inhaber_steht_im_text(self, ):
        befunde = abg.befunde(
            [_ber(chip_status='gesperrt', mitglied_vorname='Max', mitglied_nachname='M.')],
            [_karte()], jetzt_ms=_JETZT_MS)
        assert 'Max M.' in befunde[0]['text']


class TestKarteFehltOderIstFremd:
    def test_zugeteilt_aber_nicht_am_schloss(self):
        befunde = abg.befunde([_ber()], [], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_KARTE_FEHLT]

    def test_nie_angelernte_zeile_ist_kein_befund(self):
        """Das steht schon als „nicht am Schloss" an der Zeile – kein zweiter Kanal."""
        assert abg.befunde([_ber(ttlock_card_id=None)], [], jetzt_ms=_JETZT_MS) == []

    def test_nie_angelernt_aber_karte_liegt_dort_wird_ueber_die_nummer_gefunden(self):
        """Per BLE an unserer App vorbei angelernt: Die Zeile ist im Rückstand, aber
        die Karte ist unsere – sie darf nicht als fremd gemeldet werden."""
        befunde = abg.befunde([_ber(ttlock_card_id=None)], [_karte()], jetzt_ms=_JETZT_MS)
        assert befunde == []

    def test_karte_ohne_berechtigung_ist_fremd(self):
        befunde = abg.befunde([], [_karte(name='Unbekannt', detail='999')],
                              jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_KARTE_FREMD]
        assert befunde[0]['chip_id'] is None      # zu der Karte gibt es keinen Chip von uns

    def test_zwei_schloesser_werden_nicht_verwechselt(self):
        """Dieselbe cardId kann an zwei Schlössern vorkommen – Schlüssel ist das Paar."""
        befunde = abg.befunde(
            [_ber(schloss_id=1), _ber(id=2, schloss_id=2, schloss_name='Küche')],
            [_karte(schloss_id=1)], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_KARTE_FEHLT]
        assert befunde[0]['schloss'] == 'Küche'


class TestFenster:
    def test_abweichendes_ende_wird_gemeldet(self):
        befunde = abg.befunde(
            [_ber(gueltig_bis='2026-12-31T23:00:00+00:00')],
            [_karte(gueltig_bis='2027-12-31T23:00:00+00:00')], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_FENSTER]
        assert '2026-12-31' in befunde[0]['text'] and '2027-12-31' in befunde[0]['text']

    def test_unbefristet_am_schloss_statt_befristet_bei_uns(self):
        """endDate=0 heißt bei TTLock unbefristet – die Karte gilt länger als gedacht."""
        befunde = abg.befunde(
            [_ber(gueltig_bis='2026-12-31T23:00:00+00:00')], [_karte()], jetzt_ms=_JETZT_MS)
        assert _arten(befunde) == [abg.BEFUND_FENSTER]


class TestMeldung:
    def test_digest_nennt_jeden_befund(self):
        kritische = [b for b in abg.befunde([_ber(chip_status='verloren')], [_karte()],
                                            jetzt_ms=_JETZT_MS) if b['kritisch']]
        titel, text = abg.build_sperr_digest(kritische)
        assert '1' in titel and 'Halle' in text and 'Gateway' in text

    def test_ohne_befund_kein_digest(self):
        assert abg.build_sperr_digest([]) is None

    def test_signatur_ist_reihenfolgeunabhaengig(self):
        a = {'schloss_id': 1, 'kartennummer': '111', 'chip_id': 7}
        b = {'schloss_id': 2, 'kartennummer': '222', 'chip_id': 8}
        assert abg.signatur([a, b]) == abg.signatur([b, a])

    def test_andere_luecke_ergibt_andere_signatur(self):
        a = {'schloss_id': 1, 'kartennummer': '111', 'chip_id': 7}
        b = {'schloss_id': 2, 'kartennummer': '111', 'chip_id': 7}
        assert abg.signatur([a]) != abg.signatur([b])


class FakeLog:
    """Zugriffsprotokoll als Gedächtnis der letzten Meldung."""
    def __init__(self):
        self.zeilen = []

    def log(self, event_type, *, category=None, detail=None, **kw):
        self.zeilen.insert(0, {'event_type': event_type, 'detail': detail})

    def list(self, *, event_type=None, limit=100, **kw):
        return [z for z in self.zeilen if z['event_type'] == event_type][:limit]


class FakeDB:
    def __init__(self, berechtigungen, karten, empfaenger=()):
        self.access_log_repository = FakeLog()
        self.push = None
        self.tuer_berechtigungen = SimpleNamespace(list_fuer_abgleich=lambda: berechtigungen)
        self.tuer_credentials = SimpleNamespace(list_fuer_abgleich=lambda typ: karten)
        self.user_repository = SimpleNamespace(list_all=lambda: list(empfaenger))
        self.auth_token_repository = None


def _admin(name='chef'):
    return SimpleNamespace(id=1, username=name, role='admin', active=True)


class TestWiederholungssperre:
    def _melden(self, db, monkeypatch, gesendet):
        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, 'send_notification',
                            staticmethod(lambda *a, **k: gesendet.append(a) or True))
        return abg.melde_sperrluecken(db)

    def test_neue_luecke_wird_gemeldet(self, monkeypatch):
        db = FakeDB([_ber(chip_status='verloren')], [_karte()], empfaenger=[_admin()])
        gesendet = []
        assert self._melden(db, monkeypatch, gesendet) == 1
        assert len(gesendet) == 1

    def test_dieselbe_luecke_meldet_nicht_erneut(self, monkeypatch):
        """Der Sync läuft alle sechs Stunden – sonst kämen 4 Nachrichten am Tag."""
        db = FakeDB([_ber(chip_status='verloren')], [_karte()], empfaenger=[_admin()])
        gesendet = []
        self._melden(db, monkeypatch, gesendet)
        assert self._melden(db, monkeypatch, gesendet) == 0
        assert len(gesendet) == 1

    def test_entwarnung_wird_protokolliert(self, monkeypatch):
        """Ohne diese Zeile bliebe dieselbe Lücke beim zweiten Auftreten stumm."""
        db = FakeDB([], [], empfaenger=[_admin()])
        gesendet = []
        assert self._melden(db, monkeypatch, gesendet) == 0
        assert db.access_log_repository.zeilen[0]['detail'] == ''
        assert gesendet == []

    def test_nach_entwarnung_meldet_dieselbe_luecke_wieder(self, monkeypatch):
        db = FakeDB([_ber(chip_status='verloren')], [_karte()], empfaenger=[_admin()])
        gesendet = []
        self._melden(db, monkeypatch, gesendet)
        db.tuer_berechtigungen.list_fuer_abgleich = lambda: [_ber()]      # Chip wieder aktiv
        self._melden(db, monkeypatch, gesendet)
        db.tuer_berechtigungen.list_fuer_abgleich = lambda: [_ber(chip_status='verloren')]
        assert self._melden(db, monkeypatch, gesendet) == 1
        assert len(gesendet) == 2

    def test_ohne_erreichbare_admins_bleibt_die_signatur_gemerkt(self, monkeypatch):
        db = FakeDB([_ber(chip_status='verloren')], [_karte()], empfaenger=[])
        assert self._melden(db, monkeypatch, []) == 0
        assert db.access_log_repository.zeilen[0]['detail'] != ''


class TestEndpunkt:
    """Der Endpunkt selbst: Recht prüfen, Scope durchreichen – mehr tut er nicht."""

    def _api(self):
        _ROOT = Path(__file__).resolve().parents[2]
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        from backend.api import schliessanlage as api
        return api

    def _user(self, *perms):
        return SimpleNamespace(
            id=1, username='verwalter', role='mitglied', active=True,
            has_permission=lambda p: p in set(perms),
            has_permission_global=lambda p: p in set(perms),
            allowed_abteilungen=lambda p: None)

    def test_ohne_verwalten_recht_403(self):
        import pytest
        from fastapi import HTTPException
        api = self._api()
        with pytest.raises(HTTPException) as e:
            api.abgleich(self._user(), FakeDB([], []))
        assert e.value.status_code == 403

    def test_mit_recht_kommen_die_befunde(self):
        from app.models.permission import Permission
        api = self._api()
        db = FakeDB([_ber(chip_status='verloren')], [_karte()])
        ergebnis = api.abgleich(self._user(Permission.SCHLIESSANLAGE_VERWALTEN), db)
        assert ergebnis['kritisch'] == 1


class TestScope:
    def test_fremde_schloesser_fallen_raus(self):
        """Ein abteilungsgebundener Verwalter sieht keine Befunde fremder Türen."""
        db = FakeDB([_ber(schloss_id=1), _ber(id=2, schloss_id=2, chip_status='verloren')],
                    [_karte(schloss_id=1), _karte(schloss_id=2)])
        assert abg.abgleich(db, schloss_ids={2})['kritisch'] == 1
        assert abg.abgleich(db, schloss_ids={1})['befunde'] == []

    def test_stand_ist_der_juengste_spiegel(self):
        db = FakeDB([], [_karte(gesehen_am='2026-08-20T06:00:00+00:00'),
                         _karte(gesehen_am='2026-08-21T06:00:00+00:00')])
        assert abg.abgleich(db)['stand'] == '2026-08-21T06:00:00+00:00'
