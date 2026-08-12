"""Anhang-Downloads hängen an der Berechtigung ihres Elternobjekts.

Vorher lief jeder Download über `/api/uploads/{stored_name}` und prüfte nur, *dass*
jemand angemeldet ist. Die Dateinamen sind fortlaufend (`att_000123.jpg`,
`rech_000042.jpg`, `kabu_000007.jpg`) – ein beliebiges Mitgliedskonto konnte damit
durch Hochzählen sämtliche Belege und Ticket-Anhänge des Vereins abziehen.

Geprüft wird deshalb dreierlei:
  * Der Sammel-Endpunkt existiert nicht mehr (sonst bliebe die Abkürzung offen).
  * Jeder Fach-Endpunkt setzt dieselbe Leseprüfung durch wie seine Anhang-Liste.
  * Eine Anhang-ID aus einem fremden Ticket/Beleg zieht nicht – sonst wäre die
    Lücke nur eine Ebene nach oben gewandert.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_tresor_api).
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

from app.models.kasse import KassenbuchungAnhang  # noqa: E402
from app.models.rechnung import RechnungAnhang  # noqa: E402
from app.models.ticket import TicketAnhang  # noqa: E402
from app.services.anhang_service import AnhangService  # noqa: E402
from app.services.kassenbuch_service import KeinLesezugriffError  # noqa: E402
from app.services.rechnung_service import KeinZugriffError, RechnungService  # noqa: E402
from backend.api import kassenbuch as kassen_api  # noqa: E402
from backend.api import rechnungen as rechnungen_api  # noqa: E402
from backend.api import tickets as tickets_api  # noqa: E402
from backend.api.uploads import anhang_antwort  # noqa: E402


# --------------------------------------------------------------------- Stubs
def _user(uid=1, role='mitglied', rechte=()):
    return SimpleNamespace(
        id=uid, username='mitglied', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in rechte,
        has_permission_global=lambda p: role == 'admin' or p in rechte,
        has_permission_for_abteilung=lambda p, a: role == 'admin' or p in rechte,
        allowed_abteilungen=lambda p: None,
    )


def _datei(tmp_path, name, inhalt=b'BILDDATEN'):
    """Legt eine Anhang-Datei im Upload-Ordner an und liefert den AnhangService."""
    (tmp_path / name).write_bytes(inhalt)
    return AnhangService(str(tmp_path))


def _db(anhang_service, **kw):
    return SimpleNamespace(anhang_service=anhang_service, **kw)


# ------------------------------------------------- Gemeinsame Datei-Antwort
def test_bild_geht_inline_mit_seinem_mime_typ_raus(tmp_path):
    dienst = _datei(tmp_path, 'att_000001.jpg')
    anhang = TicketAnhang(id=1, ticket_id=7, original_name='Foto.jpg',
                          stored_name='att_000001.jpg', mime_type='image/jpeg')
    antwort = anhang_antwort(_db(dienst), anhang)
    assert antwort.media_type == 'image/jpeg'
    assert antwort.headers['content-disposition'].startswith('inline')


def test_pdf_geht_als_download_raus(tmp_path):
    dienst = _datei(tmp_path, 'rech_000002.pdf')
    anhang = RechnungAnhang(id=2, rechnung_id=3, original_name='Quittung.pdf',
                            stored_name='rech_000002.pdf', mime_type='application/pdf')
    antwort = anhang_antwort(_db(dienst), anhang)
    assert antwort.media_type == 'application/pdf'
    assert antwort.headers['content-disposition'].startswith('attachment')


def test_nicht_erlaubter_mime_typ_wird_nicht_im_browser_gerendert(tmp_path):
    """Der MIME-Typ stammt vom Hochladenden. Was der Upload nicht durchgelassen
    hätte, geht als undeutbarer Download raus statt als etwas Ausführbares."""
    dienst = _datei(tmp_path, 'att_000003.html', b'<script>alert(1)</script>')
    anhang = TicketAnhang(id=3, ticket_id=7, original_name='boese.html',
                          stored_name='att_000003.html', mime_type='text/html')
    antwort = anhang_antwort(_db(dienst), anhang)
    assert antwort.media_type == 'application/octet-stream'
    assert antwort.headers['content-disposition'].startswith('attachment')


def test_fehlende_datei_meldet_404(tmp_path):
    dienst = AnhangService(str(tmp_path))
    anhang = TicketAnhang(id=4, ticket_id=7, original_name='weg.jpg',
                          stored_name='att_000004.jpg', mime_type='image/jpeg')
    with pytest.raises(HTTPException) as e:
        anhang_antwort(_db(dienst), anhang)
    assert e.value.status_code == 404


def test_stored_name_kann_nicht_aus_dem_upload_ordner_zeigen(tmp_path):
    """Die Endung des stored_name stammt aus dem hochgeladenen Dateinamen – die
    Zusicherung „bleibt im Upload-Ordner" muss deshalb geprüft werden, nicht bloß
    angenommen."""
    (tmp_path.parent / 'geheim.txt').write_bytes(b'nicht fuer dich')
    dienst = AnhangService(str(tmp_path))
    anhang = TicketAnhang(id=5, ticket_id=7, original_name='x',
                          stored_name='../geheim.txt', mime_type='image/jpeg')
    with pytest.raises(HTTPException) as e:
        anhang_antwort(_db(dienst), anhang)
    assert e.value.status_code == 404


# ------------------------------------------------------------------ Tickets
def _ticket_db(tmp_path, anhang, ticket_id=7):
    dienst = _datei(tmp_path, anhang.stored_name)
    return _db(
        dienst,
        tickets=SimpleNamespace(
            get_ticket=lambda tid: SimpleNamespace(
                id=tid, bereich_id=1, gemeldet_von=1, zugewiesen_an=None),
            get_anhang=lambda aid: anhang if anhang.id == aid else None,
        ),
    )


def test_ticket_anhang_wird_ausgeliefert(tmp_path):
    anhang = TicketAnhang(id=10, ticket_id=7, original_name='Screenshot.png',
                          stored_name='att_000010.png', mime_type='image/png')
    antwort = tickets_api.download_anhang(7, 10, _user(), _ticket_db(tmp_path, anhang))
    assert antwort.media_type == 'image/png'


def test_ticket_anhang_eines_anderen_tickets_ist_nicht_erreichbar(tmp_path):
    """Der Kern: Die Anhang-ID allein darf nicht reichen – sie muss zum Ticket
    im Pfad gehören, sonst ist die Lücke nur eine Ebene weitergewandert."""
    anhang = TicketAnhang(id=10, ticket_id=99, original_name='fremd.png',
                          stored_name='att_000010.png', mime_type='image/png')
    with pytest.raises(HTTPException) as e:
        tickets_api.download_anhang(7, 10, _user(), _ticket_db(tmp_path, anhang))
    assert e.value.status_code == 404


def test_geloeschter_ticket_anhang_ist_nicht_mehr_abrufbar(tmp_path):
    anhang = TicketAnhang(id=10, ticket_id=7, original_name='weg.png',
                          stored_name='att_000010.png', mime_type='image/png',
                          deleted_at='2026-01-01T00:00:00Z', deleted_by='wer')
    with pytest.raises(HTTPException) as e:
        tickets_api.download_anhang(7, 10, _user(), _ticket_db(tmp_path, anhang))
    assert e.value.status_code == 404


# --------------------------------------------------------------- Rechnungen
def _rechnung_service(anhang, *, ersteller_id=1, status='eingereicht'):
    rechnung = SimpleNamespace(id=3, ersteller_user_id=ersteller_id,
                               status=status, abteilung_id=None)
    return RechnungService(
        rechnung_repo=SimpleNamespace(get=lambda rid: rechnung if rid == 3 else None),
        kategorie_repo=None,
        anhang_repo=SimpleNamespace(get=lambda aid: anhang if anhang.id == aid else None),
        user_repo=None,
        mitglied_repo=None,
        permission_repo=None,
        abteilung_repo=None,
    )


def _beleg(**kw):
    daten = dict(id=20, rechnung_id=3, original_name='Kassenbon.jpg',
                 stored_name='rech_000020.jpg', mime_type='image/jpeg')
    daten.update(kw)
    return RechnungAnhang(**daten)


def test_beleg_ist_sichtbar_fuer_den_ersteller():
    anhang = _beleg()
    dienst = _rechnung_service(anhang, ersteller_id=1)
    assert dienst.hole_anhang(3, 20, _user(uid=1)) is anhang


def test_fremder_beleg_ist_gesperrt():
    """Ein fremder Entwurf bleibt verborgen – die Datei darf das nicht unterlaufen."""
    dienst = _rechnung_service(_beleg(), ersteller_id=99, status='entwurf')
    with pytest.raises(KeinZugriffError):
        dienst.hole_anhang(3, 20, _user(uid=1))


def test_beleg_einer_anderen_rechnung_ist_nicht_erreichbar():
    dienst = _rechnung_service(_beleg(rechnung_id=77))
    with pytest.raises(KeyError):
        dienst.hole_anhang(3, 20, _user(uid=1))


def test_geloeschter_beleg_ist_nicht_mehr_abrufbar():
    dienst = _rechnung_service(_beleg(deleted_at='2026-01-01T00:00:00Z'))
    with pytest.raises(KeyError):
        dienst.hole_anhang(3, 20, _user(uid=1))


def test_rechnungs_endpunkt_uebersetzt_fehlenden_zugriff_in_403(tmp_path):
    dienst = _rechnung_service(_beleg(), ersteller_id=99, status='entwurf')
    db = _db(AnhangService(str(tmp_path)), rechnungen=dienst)
    with pytest.raises(HTTPException) as e:
        rechnungen_api.download_anhang(3, 20, _user(uid=1), db)
    assert e.value.status_code == 403


# --------------------------------------------------------------- Kassenbuch
def _kassen_db(tmp_path, anhang, *, lesezugriff=True, kasse_der_buchung=2):
    dienst = _datei(tmp_path, anhang.stored_name)

    def pruefe_lesezugriff(kasse_id, user_id, is_admin=False):
        if not lesezugriff:
            raise KeinLesezugriffError('Kein Lesezugriff auf diese Kasse.')

    return _db(
        dienst,
        kassenbuch=SimpleNamespace(
            _pruefe_lesezugriff=pruefe_lesezugriff,
            _buchung=SimpleNamespace(
                get_kassenbuchung=lambda bid: SimpleNamespace(
                    id=bid, kasse_id=kasse_der_buchung)),
            get_anhang=lambda aid: anhang if anhang.id == aid else None,
        ),
    )


def _kabu(**kw):
    daten = dict(id=30, buchung_id=5, original_name='Beleg.jpg',
                 stored_name='kabu_000030.jpg', mime_type='image/jpeg')
    daten.update(kw)
    return KassenbuchungAnhang(**daten)


def test_kassenbeleg_wird_bei_lesezugriff_ausgeliefert(tmp_path):
    antwort = kassen_api.download_anhang(2, 5, 30, _user(), _kassen_db(tmp_path, _kabu()))
    assert antwort.media_type == 'image/jpeg'


def test_kassenbeleg_ohne_lesezugriff_ist_gesperrt(tmp_path):
    """Die Kassen-ACL entscheidet über den Beleg genauso wie über die Buchung."""
    db = _kassen_db(tmp_path, _kabu(), lesezugriff=False)
    with pytest.raises(HTTPException) as e:
        kassen_api.download_anhang(2, 5, 30, _user(), db)
    assert e.value.status_code == 403


def test_kassenbeleg_einer_fremden_buchung_ist_nicht_erreichbar(tmp_path):
    db = _kassen_db(tmp_path, _kabu(buchung_id=88))
    with pytest.raises(HTTPException) as e:
        kassen_api.download_anhang(2, 5, 30, _user(), db)
    assert e.value.status_code == 404


def test_buchung_einer_fremden_kasse_ist_nicht_erreichbar(tmp_path):
    """Sonst liehe man sich den Lesezugriff auf Kasse A, um Belege aus B zu holen."""
    db = _kassen_db(tmp_path, _kabu(), kasse_der_buchung=999)
    with pytest.raises(HTTPException) as e:
        kassen_api.download_anhang(2, 5, 30, _user(), db)
    assert e.value.status_code == 404


# ------------------------------------------------------------- Regressionen
def test_sammel_endpunkt_fuer_uploads_existiert_nicht_mehr():
    """Solange `/api/uploads/{stored_name}` erreichbar ist, sind alle Prüfungen
    darüber wirkungslos – der Weg daran vorbei muss zu bleiben."""
    from backend.main import app
    pfade = [getattr(r, 'path', '') for r in app.routes]
    assert not [p for p in pfade if p.startswith('/api/uploads')]


def test_jeder_anhang_download_haengt_unter_seinem_elternobjekt():
    from backend.main import app
    downloads = sorted(p for p in (getattr(r, 'path', '') for r in app.routes)
                       if p.endswith('/anhaenge/{anhang_id}/datei'))
    assert downloads == [
        '/api/kassen/{kasse_id}/buchungen/{buchung_id}/anhaenge/{anhang_id}/datei',
        '/api/rechnungen/{rechnung_id}/anhaenge/{anhang_id}/datei',
        '/api/tickets/{ticket_id}/anhaenge/{anhang_id}/datei',
    ]
