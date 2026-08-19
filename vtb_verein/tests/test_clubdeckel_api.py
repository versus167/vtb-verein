"""Teamkassen-API (#98, backend/api/clubdeckel.py) — Stub-basiert.

Zugriffsmatrix der teaminternen Stufen (mitglied < wart < verwalten, Admin-Bypass)
und die Validierungen der Buchungs-Endpunkte im korrigierten Modell (konsum/
verkauf/einkauf/zahlung/beitrag, Gruppen mit Verkäufer, Team-Saldo). Die
SQL-Seite (Kader-CTE, Salden, Paar-Buchungen, Beitragslauf) deckt
test_clubdeckel_integration ab.
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.clubdeckel import (  # noqa: E402
    Clubdeckel, ClubdeckelGruppe, ClubdeckelArtikel, ClubdeckelBuchung,
)
from backend.api import clubdeckel as api  # noqa: E402

_USER = SimpleNamespace(id=5, username='spieler', role='mitglied',
                        has_permission=lambda p: False)
_ADMIN = SimpleNamespace(id=1, username='admin', role='admin',
                         has_permission=lambda p: True)

_AUDIT = dict(version=1, created_at='x', created_by='t', updated_at='x', updated_by='t')


def _deckel(**kw):
    base = dict(id=7, mannschaft_id=3, name='Teamkasse Erste', aktiv=1,
                beitrag=None, beitrag_ab=None, zahlungsempfaenger_mitglied_id=None,
                zahlweg_iban=None, zahlweg_wero=None, zahlweg_paypal=None, **_AUDIT)
    base.update(kw)
    return Clubdeckel(**base)


def _gruppe(**kw):
    base = dict(id=31, deckel_id=7, name='Getränke', verkaeufer_mitglied_id=None,
                aktiv=1, sortierung=0, stamm_id=31, gilt_ab_termin_id=None,
                **_AUDIT)
    base.update(kw)
    return ClubdeckelGruppe(**base)


def _artikel(**kw):
    base = dict(id=21, deckel_id=7, gruppe_id=31, name='Bier', preis=Decimal('1.50'),
                aktiv=1, sortierung=0, **_AUDIT)
    base.update(kw)
    return ClubdeckelArtikel(**base)


def _artikel_mv(**kw):
    """Artikel-Dict wie aus get_mit_verkaeufer (inkl. Gruppen-/Verkäufer-Infos)."""
    base = dict(id=21, deckel_id=7, gruppe_id=31, name='Bier', preis=Decimal('1.50'),
                aktiv=1, sortierung=0, gruppe_aktiv=1, verkaeufer_mitglied_id=None,
                **_AUDIT)
    base.update(kw)
    return base


def _buchung(**kw):
    base = dict(id=100, deckel_id=7, mitglied_id=11, artikel_id=21, typ='konsum',
                menge=1, betrag=Decimal('-1.50'), paar_ref=None, beitrag_monat=None,
                notiz=None, artikel_name='Bier', gegen_name='Team', termin_id=None,
                **_AUDIT)
    base.update(kw)
    return ClubdeckelBuchung(**base)


def _termin(**kw):
    """Termin der Mannschaft 3 (#167) – nur die Felder, die die API anfasst."""
    base = dict(id=55, mannschaft_id=3, typ='spiel', beginn='2026-08-16T15:00',
                ende='2026-08-16T17:00', gegner='SV X', status='geplant')
    base.update(kw)
    return SimpleNamespace(**base)


def _db(kader='mitglied', wart=False):
    """Stub-DB: `kader` ist die Kader-Stufe des Users (None|'mitglied'|'verwalten'),
    `wart` die Wart-ACL. Tests überschreiben einzelne Methoden direkt."""
    return SimpleNamespace(
        clubdeckel=SimpleNamespace(
            get=lambda did: _deckel(id=did),
            get_by_mannschaft=lambda mid: None,
            get_access_for_user=lambda uid, mid: kader,
            get_kader_mitglied_id=lambda uid, mid: 11,
            is_mitglied_in_kader=lambda mid, man: True,
            create=lambda man, name, by: _deckel(name=name),
            update=lambda *a, **k: True,
            set_aktiv=lambda *a, **k: True,
            mark_deleted=lambda *a, **k: True,
            loesche_komplett=lambda *a, **k: 'ref-del',
            restore=lambda *a, **k: 'ok',
            list_geloescht=lambda: [],
            list_teams_for_user=lambda uid: [],
            list_all_teams=lambda: [],
        ),
        clubdeckel_berechtigungen=SimpleNamespace(
            ist_wart_user=lambda did, uid: wart,
            list_for_deckel=lambda did: [],
            set_wart=lambda *a: None,
            revoke=lambda *a: True,
        ),
        clubdeckel_gruppen=SimpleNamespace(
            get=lambda gid: _gruppe(id=gid, stamm_id=gid),
            list_for_deckel=lambda did: [_gruppe()],
            # Sortiments-Stand zum Ziel-Termin (#167, v100)
            list_stand=lambda did, termin_id=None, jetzt=None: [_gruppe()],
            neue_generation=lambda gid, tid, name, verk, aktiv, sort, by: (
                99, {21: 21}),
            list_generationen=lambda stamm: [],
            create=lambda *a, **k: _gruppe(),
            update=lambda *a: True,
            has_active_artikel=lambda gid: False,
            mark_deleted=lambda *a: True,
        ),
        clubdeckel_artikel=SimpleNamespace(
            get=lambda aid: _artikel(id=aid),
            get_mit_verkaeufer=lambda aid: _artikel_mv(id=aid),
            list_for_deckel=lambda did, nur_aktive=False: [dict(
                _artikel_mv(), gruppe_name='Getränke', verkaeufer_name=None)],
            # Artikel des gültigen Gruppen-Standes (#167, v100)
            list_fuer_gruppen=lambda gids, nur_aktive=False: [dict(
                _artikel_mv(), gruppe_name='Getränke', verkaeufer_name=None)],
            # Nachschlag für Artikel außer Dienst (#167) – Standard: keine.
            list_fuer_ids=lambda did, ids: [],
            create=lambda *a: _artikel(),
            update=lambda *a: True,
            mark_deleted=lambda *a: True,
        ),
        clubdeckel_befreiungen=SimpleNamespace(
            ist_befreit=lambda did, mid: False,
            list_for_deckel=lambda did: [],
            set_befreiung=lambda *a: None,
            revoke=lambda *a: True,
        ),
        clubdeckel_buchungen=SimpleNamespace(
            get=lambda bid, include_deleted=False: _buchung(id=bid),
            list_for_deckel=lambda did, mitglied_id=None, limit=None,
            mit_storniert=False, suche=None, von=None, bis=None,
            termin_id=None: [_buchung()],
            create_konsum=lambda *a, **k: _buchung(termin_id=k.get('termin_id')),
            create_zahlung=lambda *a, **k: 'ref123',
            create_einkauf=lambda *a: _buchung(typ='einkauf', betrag=Decimal('20')),
            create_an_verkauf=lambda *a, **k: 'refAV',
            buche_faellige_beitraege=lambda *a, **k: 0,
            storno=lambda *a: True,
            restore=lambda *a, **k: True,
            salden=lambda did: [],
            saldo_for_mitglied=lambda did, mid: Decimal('-3.00'),
            konsum_fuer_termin=lambda did, mid, tid: {
                'summe': Decimal('3.00'), 'anzahl': {21: 2}},
            letzte_konsum_id=lambda did, mid, aid, von=None, bis=None,
            termin_id=None: 100,
            matrix=lambda did, von=None, bis=None, termin_id=None: {
                'zellen': {}, 'je_artikel': {}, 'je_mitglied': [],
                'gesamt': Decimal('0')},
            # Umstellen auf einen neuen Sortiments-Stand (#167, v100)
            konsum_je_artikel=lambda did, tid, aids: [],
            zaehle_konsum_fuer_termin=lambda did, tid: {
                'anzahl': 0, 'betrag': Decimal('0')},
        ),
        # Zusagen zum Termin bestimmen die Reihenfolge der Matrix-Zeilen (#167).
        termin_zusagen=SimpleNamespace(
            list_kader_with_zusage=lambda tid: [],
        ),
        # Termin-Zuordnung der Buchungen (#167): Standard-Stub kennt keinen
        # laufenden Termin – Tests, die einen brauchen, setzen ihn selbst.
        termine=SimpleNamespace(
            get=lambda tid: _termin(id=tid),
            get_laufenden=lambda mid, jetzt=None: None,
            get_naechsten=lambda mid, jetzt=None: None,
            list_for_mannschaft=lambda mid, von=None, bis=None: [],
        ),
        get_mannschaft=lambda mid: SimpleNamespace(id=mid, name='Erste'),
        list_mannschaft_kader=lambda mid: [],
    )


# ----------------------------------------------------------------- Zugriffsmatrix
def test_deckel_nicht_gefunden_404():
    db = _db()
    db.clubdeckel.get = lambda did: None
    with pytest.raises(HTTPException) as exc:
        api.get_deckel(7, _USER, db)
    assert exc.value.status_code == 404


def test_nicht_kader_hat_keinen_zugriff_403():
    with pytest.raises(HTTPException) as exc:
        api.get_deckel(7, _USER, _db(kader=None))
    assert exc.value.status_code == 403


def test_spieler_liest_deckel_mit_stufe_mitglied():
    result = api.get_deckel(7, _USER, _db())
    assert result['zugriff'] == 'mitglied'
    assert result['mein_saldo'] == Decimal('-3.00')
    assert result['artikel'][0]['name'] == 'Bier'


def test_get_deckel_liefert_striche_des_termins():
    result = api.get_deckel(7, _USER, _db())
    assert result['mein_termin_summe'] == Decimal('3.00')
    assert result['artikel'][0]['mein_termin_anzahl'] == 2


def test_spieler_darf_keinen_artikel_anlegen_403():
    with pytest.raises(HTTPException) as exc:
        api.create_artikel(7, api.ArtikelWrite(name='Bier', preis=1.5), _USER, _db())
    assert exc.value.status_code == 403


def test_wart_darf_artikel_anlegen():
    result = api.create_artikel(7, api.ArtikelWrite(name='Bier', preis=1.5),
                                _USER, _db(wart=True))
    assert result['name'] == 'Bier'


def test_wart_darf_keine_stammdaten_aendern_403():
    data = api.DeckelUpdate(name='Neu', aktiv=True, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_deckel(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 403


def test_verwalter_aendert_stammdaten():
    result = api.update_deckel(
        7, api.DeckelUpdate(name='Neu', aktiv=False, beitrag=5.0,
                            zahlweg_iban='DE12', expected_version=1),
        _USER, _db(kader='verwalten'))
    assert result['id'] == 7


def test_stammdaten_negativer_beitrag_422():
    data = api.DeckelUpdate(name='Neu', beitrag=-1.0, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_deckel(7, data, _USER, _db(kader='verwalten'))
    assert exc.value.status_code == 422


def test_admin_bypass_ohne_kader():
    db = _db(kader=None)
    result = api.get_deckel(7, _ADMIN, db)
    assert result['zugriff'] == 'verwalten'


def test_spieler_darf_keine_zahlung_buchen_403():
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=12, betrag=2.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_zahlung(7, data, _USER, _db())
    assert exc.value.status_code == 403


def test_buchungen_alle_erfordert_wart_403():
    with pytest.raises(HTTPException) as exc:
        api.list_buchungen(7, _USER, _db(), alle=True)
    assert exc.value.status_code == 403


def test_befreiungen_erfordern_verwalter_403():
    with pytest.raises(HTTPException) as exc:
        api.set_befreiung(7, 12, _USER, _db(wart=True))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------- Einschalten
def test_einschalten_nur_fuer_kader_verwalter_403():
    with pytest.raises(HTTPException) as exc:
        api.deckel_einschalten(3, api.DeckelCreate(), _USER, _db(kader='mitglied'))
    assert exc.value.status_code == 403


def test_einschalten_mannschaft_fehlt_404():
    db = _db(kader='verwalten')
    db.get_mannschaft = lambda mid: None
    with pytest.raises(HTTPException) as exc:
        api.deckel_einschalten(3, api.DeckelCreate(), _USER, db)
    assert exc.value.status_code == 404


def test_einschalten_doppelt_409():
    db = _db(kader='verwalten')
    db.clubdeckel.get_by_mannschaft = lambda mid: _deckel()
    with pytest.raises(HTTPException) as exc:
        api.deckel_einschalten(3, api.DeckelCreate(), _USER, db)
    assert exc.value.status_code == 409


def test_einschalten_default_name_aus_mannschaft():
    db = _db(kader='verwalten')
    seen = []
    db.clubdeckel.create = lambda man, name, by: (seen.append(name), _deckel(name=name))[1]
    api.deckel_einschalten(3, api.DeckelCreate(), _USER, db)
    assert seen == ['Teamkasse Erste']


# --------------------------------------------------------------------- Beitragslauf
def test_get_deckel_stoesst_beitragslauf_an():
    db = _db()
    db.clubdeckel.get = lambda did: _deckel(id=did, beitrag=Decimal('5.00'),
                                            beitrag_ab='2026-07')
    calls = []
    db.clubdeckel_buchungen.buche_faellige_beitraege = \
        lambda did, man, betrag, ab: (calls.append((did, man, betrag, ab)), 0)[1]
    api.get_deckel(7, _USER, db)
    assert calls == [(7, 3, Decimal('5.00'), '2026-07')]


def test_kein_beitragslauf_ohne_beitrag_oder_inaktiv():
    calls = []
    db = _db()
    db.clubdeckel_buchungen.buche_faellige_beitraege = \
        lambda *a: (calls.append(a), 0)[1]
    api.get_deckel(7, _USER, db)  # kein beitrag konfiguriert
    db.clubdeckel.get = lambda did: _deckel(aktiv=0, beitrag=Decimal('5'),
                                            beitrag_ab='2026-07')
    api.get_deckel(7, _USER, db)  # deaktiviert
    assert calls == []


# --------------------------------------------------------------------- Validierung
def test_konsum_menge_null_422():
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21, menge=0), _USER, _db())
    assert exc.value.status_code == 422


def test_konsum_inaktiver_artikel_422():
    db = _db()
    db.clubdeckel_artikel.get_mit_verkaeufer = lambda aid: _artikel_mv(aktiv=0)
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert exc.value.status_code == 422


def test_konsum_inaktive_gruppe_422():
    db = _db()
    db.clubdeckel_artikel.get_mit_verkaeufer = lambda aid: _artikel_mv(gruppe_aktiv=0)
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert exc.value.status_code == 422


def test_konsum_auf_deaktiviertem_deckel_409():
    db = _db()
    db.clubdeckel.get = lambda did: _deckel(aktiv=0)
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert exc.value.status_code == 409


def test_konsum_ohne_kader_mitglied_422():
    db = _db(kader='verwalten')
    db.clubdeckel.get_kader_mitglied_id = lambda uid, mid: None
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _ADMIN, db)
    assert exc.value.status_code == 422


def test_konsum_reicht_verkaeufer_der_gruppe_durch():
    db = _db()
    db.clubdeckel_artikel.get_mit_verkaeufer = \
        lambda aid: _artikel_mv(name='Roster', preis=Decimal('2.50'),
                                verkaeufer_mitglied_id=42)
    calls = []

    def create_konsum(did, mid, aid, aname, menge, preis, verkaeufer, by,
                      termin_id=None):
        calls.append((did, mid, aid, aname, menge, preis, verkaeufer, by))
        return _buchung(menge=menge)

    db.clubdeckel_buchungen.create_konsum = create_konsum
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21, menge=2), _USER, db)
    assert calls == [(7, 11, 21, 'Roster', 2, Decimal('2.50'), 42, 'spieler')]


def test_zahlung_gleiche_mitglieder_422():
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=11, betrag=2.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_zahlung(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 422


def test_zahlung_negativer_betrag_422():
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=12, betrag=-1.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_zahlung(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 422


def test_zahlung_fremdes_mitglied_422():
    db = _db(wart=True)
    db.clubdeckel.is_mitglied_in_kader = lambda mid, man: False
    db.clubdeckel_buchungen.saldo_for_mitglied = lambda did, mid: Decimal('0')
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=12, betrag=2.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_zahlung(7, data, _USER, db)
    assert exc.value.status_code == 422


def test_zahlung_ausgetretener_mit_restschuld_erlaubt():
    db = _db(wart=True)
    db.clubdeckel.is_mitglied_in_kader = lambda mid, man: False
    db.clubdeckel_buchungen.saldo_for_mitglied = lambda did, mid: Decimal('-4.50')
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=12, betrag=2.0)
    assert api.buche_zahlung(7, data, _USER, db) == {"paar_ref": 'ref123'}


def test_an_verkauf_negativer_betrag_422():
    data = api.AnVerkaufCreate(mitglied_id=11, betrag=0)
    with pytest.raises(HTTPException) as exc:
        api.buche_an_verkauf(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 422


def test_an_verkauf_spieler_403():
    data = api.AnVerkaufCreate(mitglied_id=11, betrag=5.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_an_verkauf(7, data, _USER, _db())
    assert exc.value.status_code == 403


def test_an_verkauf_gegen_gleiches_mitglied_422():
    data = api.AnVerkaufCreate(mitglied_id=11, gegen_mitglied_id=11, betrag=5.0)
    with pytest.raises(HTTPException) as exc:
        api.buche_an_verkauf(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 422


def test_an_verkauf_gegen_team_ok():
    db = _db(wart=True)
    seen = []
    db.clubdeckel_buchungen.create_an_verkauf = \
        lambda did, mid, gegen, verkauft, betrag, notiz, by, datum=None: (
            seen.append((mid, gegen, verkauft, betrag, datum)), 'refAV')[1]
    data = api.AnVerkaufCreate(mitglied_id=11, verkauft=True, betrag=5.0)
    assert api.buche_an_verkauf(7, data, _USER, db) == {"status": "gebucht", "ref": 'refAV'}
    assert seen == [(11, None, True, Decimal('5.00'), None)]


def test_an_verkauf_ungueltiges_datum_422():
    data = api.AnVerkaufCreate(mitglied_id=11, betrag=5.0, datum='kein-datum')
    with pytest.raises(HTTPException) as exc:
        api.buche_an_verkauf(7, data, _USER, _db(wart=True))
    assert exc.value.status_code == 422


def test_zahlung_mit_methode_und_datum():
    db = _db(wart=True)
    seen = []
    db.clubdeckel_buchungen.create_zahlung = \
        lambda did, von, an, betrag, notiz, by, datum=None: (
            seen.append((von, an, betrag, notiz, datum)), 'ref123')[1]
    data = api.ZahlungCreate(von_mitglied_id=11, an_mitglied_id=12, betrag=5.0,
                             methode='unbar', datum='2026-07-20T07:34', notiz='Rest')
    api.buche_zahlung(7, data, _USER, db)
    assert seen == [(11, 12, Decimal('5.00'), 'unbar · Rest', '2026-07-20T07:34')]


def test_gruppe_loeschen_mit_artikeln_422():
    db = _db(wart=True)
    db.clubdeckel_gruppen.has_active_artikel = lambda gid: True
    with pytest.raises(HTTPException) as exc:
        api.delete_gruppe(7, 31, _USER, db)
    assert exc.value.status_code == 422


def test_gruppe_verkaeufer_ausserhalb_422():
    db = _db(wart=True)
    db.clubdeckel.is_mitglied_in_kader = lambda mid, man: False
    db.clubdeckel_buchungen.saldo_for_mitglied = lambda did, mid: Decimal('0')
    data = api.GruppeWrite(name='Essen', verkaeufer_mitglied_id=42)
    with pytest.raises(HTTPException) as exc:
        api.create_gruppe(7, data, _USER, db)
    assert exc.value.status_code == 422


def test_artikel_update_versionskonflikt_409():
    db = _db(wart=True)
    db.clubdeckel_artikel.update = lambda *a: False
    data = api.ArtikelUpdate(name='Bier', preis=1.5, expected_version=1)
    with pytest.raises(HTTPException) as exc:
        api.update_artikel(7, 21, data, _USER, db)
    assert exc.value.status_code == 409


def test_artikel_anderes_deckels_404():
    db = _db(wart=True)
    db.clubdeckel_artikel.get = lambda aid: _artikel(deckel_id=99)
    with pytest.raises(HTTPException) as exc:
        api.delete_artikel(7, 21, _USER, db)
    assert exc.value.status_code == 404


# ------------------------------------------------------------------------- Storno
def test_storno_eigener_konsum_erlaubt():
    db = _db()
    assert api.storno_buchung(7, 100, _USER, db) == {"status": "storniert"}


def test_storno_fremder_konsum_403():
    db = _db()
    db.clubdeckel_buchungen.get = lambda bid: _buchung(mitglied_id=99)
    with pytest.raises(HTTPException) as exc:
        api.storno_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 403


def test_storno_eigener_beitrag_fuer_spieler_403():
    db = _db()
    db.clubdeckel_buchungen.get = lambda bid: _buchung(typ='beitrag')
    with pytest.raises(HTTPException) as exc:
        api.storno_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 403


def test_storno_fremde_buchung_als_wart_erlaubt():
    db = _db(wart=True)
    db.clubdeckel_buchungen.get = lambda bid: _buchung(mitglied_id=99, typ='zahlung')
    assert api.storno_buchung(7, 100, _USER, db) == {"status": "storniert"}


def test_storno_buchung_anderes_deckels_404():
    db = _db(wart=True)
    db.clubdeckel_buchungen.get = lambda bid: _buchung(deckel_id=99)
    with pytest.raises(HTTPException) as exc:
        api.storno_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 404


def test_list_buchungen_alle_reicht_filter_durch():
    """#127/#129: mit_storniert, mitglied_id und suche landen im Repository-Aufruf
    (suche getrimmt, leer → None)."""
    db = _db(wart=True)
    seen = {}

    def _list(did, mitglied_id=None, limit=None, mit_storniert=False, suche=None,
              von=None, bis=None, termin_id=None):
        seen.update(did=did, mitglied_id=mitglied_id, limit=limit,
                    mit_storniert=mit_storniert, suche=suche,
                    von=von, bis=bis, termin_id=termin_id)
        return [_buchung()]

    db.clubdeckel_buchungen.list_for_deckel = _list
    api.list_buchungen(7, _USER, db, alle=True, mit_storniert=True, mitglied_id=11,
                       suche='  Bier ')
    assert seen == {"did": 7, "mitglied_id": 11, "limit": 50,
                    "mit_storniert": True, "suche": 'Bier',
                    "von": None, "bis": None, "termin_id": None}

    api.list_buchungen(7, _USER, db, alle=True, suche='   ')
    assert seen["suche"] is None


# ------------------------------------------------------------------------- Restore
def test_restore_buchung_als_wart_ok():
    db = _db(wart=True)
    seen = []
    db.clubdeckel_buchungen.get = lambda bid, include_deleted=False: _buchung(
        deleted_at='2026-07-21', deleted_by='wart')
    db.clubdeckel_buchungen.restore = lambda bid, by: (seen.append((bid, by)), True)[1]
    assert api.restore_buchung(7, 100, _USER, db) == {"status": "wiederhergestellt"}
    assert seen == [(100, 'spieler')]


def test_restore_buchung_nicht_storniert_422():
    db = _db(wart=True)
    db.clubdeckel_buchungen.get = lambda bid, include_deleted=False: _buchung(deleted_at=None)
    with pytest.raises(HTTPException) as exc:
        api.restore_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 422


def test_restore_buchung_anderes_deckels_404():
    db = _db(wart=True)
    db.clubdeckel_buchungen.get = lambda bid, include_deleted=False: _buchung(
        deckel_id=99, deleted_at='2026-07-21')
    with pytest.raises(HTTPException) as exc:
        api.restore_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 404


def test_restore_buchung_als_spieler_403():
    db = _db()  # kein Wart
    with pytest.raises(HTTPException) as exc:
        api.restore_buchung(7, 100, _USER, db)
    assert exc.value.status_code == 403


def test_undo_konsum_storniert_letzten_strich():
    db = _db()
    seen = []
    db.clubdeckel_buchungen.storno = lambda bid, by: (seen.append((bid, by)), True)[1]
    assert api.undo_konsum(7, 21, _USER, db) == {"status": "storniert"}
    assert seen == [(100, 'spieler')]


def test_undo_konsum_ohne_buchung_404():
    db = _db()
    db.clubdeckel_buchungen.letzte_konsum_id = \
        lambda did, mid, aid, von=None, bis=None, termin_id=None: None
    with pytest.raises(HTTPException) as exc:
        api.undo_konsum(7, 21, _USER, db)
    assert exc.value.status_code == 404


def test_undo_konsum_ohne_kader_422():
    db = _db(kader='verwalten')
    db.clubdeckel.get_kader_mitglied_id = lambda uid, mid: None
    with pytest.raises(HTTPException) as exc:
        api.undo_konsum(7, 21, _ADMIN, db)
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------- Salden
def test_salden_mit_team_saldo():
    db = _db()
    db.clubdeckel_buchungen.salden = lambda did: [
        {"mitglied_id": 11, "mitglied_name": "A", "saldo": Decimal('20'), "buchungen": 1},
        {"mitglied_id": 12, "mitglied_name": "B", "saldo": Decimal('-30'), "buchungen": 2},
    ]
    result = api.list_salden(7, _USER, db)
    assert result['team_saldo'] == Decimal('10')
    assert len(result['mitglieder']) == 2


# -------------------------------------------------------------------- Teams-Liste
def test_teams_filtert_deckellose_fuer_nicht_verwalter():
    db = _db()
    db.clubdeckel.list_teams_for_user = lambda uid: [
        {"mannschaft_id": 1, "mannschaft_name": "Erste", "zugriff": "mitglied",
         "deckel": {"id": 7}},
        {"mannschaft_id": 2, "mannschaft_name": "Zweite", "zugriff": "mitglied",
         "deckel": None},
        {"mannschaft_id": 3, "mannschaft_name": "Dritte", "zugriff": "verwalten",
         "deckel": None},
    ]
    result = api.list_meine_teams(_USER, db)
    assert [t["mannschaft_id"] for t in result] == [1, 3]


def test_teams_admin_nutzt_alle_teams():
    db = _db()
    db.clubdeckel.list_all_teams = lambda: [
        {"mannschaft_id": 1, "mannschaft_name": "Erste", "zugriff": "verwalten",
         "deckel": None},
    ]
    result = api.list_meine_teams(_ADMIN, db)
    assert result[0]["zugriff"] == "verwalten"


# --------------------------------------------------------------------------- Warte
def test_wart_ernennen_nur_verwalter_403():
    with pytest.raises(HTTPException) as exc:
        api.set_wart(7, 12, _USER, _db(wart=True))
    assert exc.value.status_code == 403


def test_wart_ernennen_ausserhalb_kader_422():
    db = _db(kader='verwalten')
    db.clubdeckel.is_mitglied_in_kader = lambda mid, man: False
    with pytest.raises(HTTPException) as exc:
        api.set_wart(7, 12, _USER, db)
    assert exc.value.status_code == 422


def test_wart_entfernen_ohne_eintrag_404():
    db = _db(kader='verwalten')
    db.clubdeckel_berechtigungen.revoke = lambda *a: False
    with pytest.raises(HTTPException) as exc:
        api.revoke_wart(7, 12, _USER, db)
    assert exc.value.status_code == 404


# ----------------------------------------------------- Deaktivieren / Löschen (#125)
def test_deaktivieren_durch_verwalter():
    db = _db(kader='verwalten')
    seen = []
    db.clubdeckel.set_aktiv = lambda did, aktiv, by, ev: (seen.append((did, aktiv, ev)), True)[1]
    api.set_deckel_aktiv(7, api.AktivUpdate(aktiv=False, expected_version=1), _USER, db)
    assert seen == [(7, 0, 1)]


def test_deaktivieren_wart_403():
    with pytest.raises(HTTPException) as exc:
        api.set_deckel_aktiv(7, api.AktivUpdate(aktiv=False, expected_version=1),
                             _USER, _db(wart=True))
    assert exc.value.status_code == 403


def test_deaktivieren_versionskonflikt_409():
    db = _db(kader='verwalten')
    db.clubdeckel.set_aktiv = lambda *a, **k: False
    with pytest.raises(HTTPException) as exc:
        api.set_deckel_aktiv(7, api.AktivUpdate(aktiv=True, expected_version=1), _USER, db)
    assert exc.value.status_code == 409


def test_loeschen_nur_admin_403():
    # Auch ein Kader-Verwalter darf nicht mehr löschen — nur der Admin.
    with pytest.raises(HTTPException) as exc:
        api.delete_deckel(7, _USER, _db(kader='verwalten'))
    assert exc.value.status_code == 403


def test_loeschen_durch_admin_kaskadiert():
    db = _db(kader=None)
    seen = []
    db.clubdeckel.loesche_komplett = lambda did, by: (seen.append((did, by)), 'ref-del')[1]
    assert api.delete_deckel(7, _ADMIN, db) == {"status": "geloescht"}
    assert seen == [(7, 'admin')]


def test_loeschen_unbekannt_404():
    db = _db(kader=None)
    db.clubdeckel.loesche_komplett = lambda *a: None
    with pytest.raises(HTTPException) as exc:
        api.delete_deckel(7, _ADMIN, db)
    assert exc.value.status_code == 404


# ------------------------------------------------------------ Papierkorb / Restore (#125)
def test_papierkorb_nur_admin_403():
    with pytest.raises(HTTPException) as exc:
        api.list_papierkorb(_USER, _db(kader='verwalten'))
    assert exc.value.status_code == 403


def test_papierkorb_admin_liste():
    db = _db(kader=None)
    db.clubdeckel.list_geloescht = lambda: [{"id": 7, "mannschaft_name": "Erste"}]
    assert api.list_papierkorb(_ADMIN, db) == [{"id": 7, "mannschaft_name": "Erste"}]


def test_restore_nur_admin_403():
    with pytest.raises(HTTPException) as exc:
        api.restore_deckel(7, _USER, _db(kader='verwalten'))
    assert exc.value.status_code == 403


def test_restore_ok():
    db = _db(kader=None)
    db.clubdeckel.restore = lambda did, by: 'ok'
    assert api.restore_deckel(7, _ADMIN, db) == {"status": "wiederhergestellt"}


def test_restore_konflikt_409():
    db = _db(kader=None)
    db.clubdeckel.restore = lambda did, by: 'conflict'
    with pytest.raises(HTTPException) as exc:
        api.restore_deckel(7, _ADMIN, db)
    assert exc.value.status_code == 409


def test_restore_unbekannt_404():
    db = _db(kader=None)
    db.clubdeckel.restore = lambda did, by: 'not_found'
    with pytest.raises(HTTPException) as exc:
        api.restore_deckel(7, _ADMIN, db)
    assert exc.value.status_code == 404


# ------------------------------- Fremdbuchung & Termin-Zuordnung (#167) -------
def _konsum_spion(db):
    """Fängt den create_konsum-Aufruf ab und liefert die Argumente zurück."""
    calls = []

    def create_konsum(did, mid, aid, aname, menge, preis, verkaeufer, by,
                      termin_id=None):
        calls.append({"mitglied_id": mid, "termin_id": termin_id})
        return _buchung(mitglied_id=mid, termin_id=termin_id)

    db.clubdeckel_buchungen.create_konsum = create_konsum
    return calls


def test_konsum_fuer_anderes_mitglied_als_wart_ok():
    db = _db(wart=True)
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21, mitglied_id=42), _USER, db)
    assert calls[0]["mitglied_id"] == 42


def test_konsum_fuer_anderes_mitglied_als_spieler_403():
    db = _db()
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21, mitglied_id=42), _USER, db)
    assert exc.value.status_code == 403


def test_konsum_mit_eigener_id_braucht_kein_wart():
    """Die Matrix schickt für jede Zeile eine mitglied_id – die eigene darf ein
    einfaches Kader-Mitglied damit weiterhin buchen."""
    db = _db()
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21, mitglied_id=11), _USER, db)
    assert calls[0]["mitglied_id"] == 11


def test_konsum_fuer_fremdes_mitglied_ausserhalb_des_deckels_422():
    db = _db(wart=True)
    db.clubdeckel.is_mitglied_in_kader = lambda mid, man: False
    db.clubdeckel_buchungen.saldo_for_mitglied = lambda did, mid: Decimal('0')
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21, mitglied_id=99), _USER, db)
    assert exc.value.status_code == 422


def test_konsum_stempelt_laufenden_termin():
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert calls[0]["termin_id"] == 55


def test_konsum_ohne_laufenden_termin_bleibt_ohne():
    db = _db()
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert calls[0]["termin_id"] is None


def test_konsum_expliziter_termin_schlaegt_automatik():
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21, termin_id=61), _USER, db)
    assert calls[0]["termin_id"] == 61


def test_konsum_ohne_termin_flag_unterdrueckt_automatik():
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    calls = _konsum_spion(db)
    api.buche_konsum(7, api.KonsumCreate(artikel_id=21, ohne_termin=True), _USER, db)
    assert calls[0]["termin_id"] is None


def test_konsum_termin_fremder_mannschaft_422():
    db = _db()
    db.termine.get = lambda tid: _termin(id=tid, mannschaft_id=99)
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21, termin_id=61), _USER, db)
    assert exc.value.status_code == 422


def test_undo_konsum_fuer_fremdes_mitglied_als_spieler_403():
    with pytest.raises(HTTPException) as exc:
        api.undo_konsum(7, 21, _USER, _db(), mitglied_id=42)
    assert exc.value.status_code == 403


def test_undo_konsum_reicht_ausschnitt_durch():
    """Das „−" der Matrix muss genau den Strich der Zelle treffen (#167)."""
    db = _db(wart=True)
    seen = {}

    def letzte(did, mid, aid, von=None, bis=None, termin_id=None):
        seen.update(mitglied_id=mid, von=von, bis=bis, termin_id=termin_id)
        return 100

    db.clubdeckel_buchungen.letzte_konsum_id = letzte
    api.undo_konsum(7, 21, _USER, db, mitglied_id=42, termin_id=55)
    assert seen == {"mitglied_id": 42, "von": None, "bis": None, "termin_id": 55}


# -------------------------------------------------------------- Matrix (#167)
def test_matrix_nur_ab_wart_403():
    with pytest.raises(HTTPException) as exc:
        api.get_matrix(7, _USER, _db())
    assert exc.value.status_code == 403


def test_matrix_zeigt_kader_auch_ohne_buchungen():
    db = _db(wart=True)
    db.list_mannschaft_kader = lambda mid: [
        SimpleNamespace(mitglied_id=11, mitglied_vorname='Max',
                        mitglied_nachname='Muster', rolle='spieler',
                        von='2020-01-01', bis=None),
    ]
    result = api.get_matrix(7, _USER, db)
    assert [(m['mitglied_id'], m['anzahl'], m['im_kader'])
            for m in result['mitglieder']] == [(11, 0, True)]
    assert result['artikel'][0]['summe_anzahl'] == 0


def test_matrix_ergaenzt_bucher_ausserhalb_des_kaders():
    """Ein Ausgetretener mit Buchungen im Ausschnitt darf nicht aus dem Gitter
    fallen – seine Striche stecken in den Summen."""
    db = _db(wart=True)
    db.clubdeckel_buchungen.matrix = lambda did, von=None, bis=None, termin_id=None: {
        'zellen': {"42:21": {"anzahl": 3, "betrag": Decimal('4.50')}},
        'je_artikel': {21: {"artikel_id": 21, "anzahl": 3, "betrag": Decimal('4.50')}},
        'je_mitglied': [{"mitglied_id": 42, "mitglied_name": 'Alt Spieler',
                         "anzahl": 3, "betrag": Decimal('4.50')}],
        'gesamt': Decimal('4.50'),
    }
    result = api.get_matrix(7, _USER, db)
    assert [(m['mitglied_id'], m['im_kader']) for m in result['mitglieder']] == [(42, False)]
    assert result['zellen'] == {"42:21": {"anzahl": 3, "betrag": Decimal('4.50')}}
    assert result['artikel'][0]['summe_anzahl'] == 3
    assert result['gesamt'] == Decimal('4.50')


def test_matrix_termin_fremder_mannschaft_404():
    db = _db(wart=True)
    db.termine.get = lambda tid: _termin(id=tid, mannschaft_id=99)
    with pytest.raises(HTTPException) as exc:
        api.get_matrix(7, _USER, db, termin_id=61)
    assert exc.value.status_code == 404


def test_termin_liste_fenstert_in_beide_richtungen():
    """Rückwärts fürs Nachbuchen, vorwärts für Preisstände („ab dem nächsten
    Heimspiel") — ein reines Vergangenheitsfenster machte Letzteres unmöglich."""
    db = _db()
    gesehen = {}

    def _list(mid, von=None, bis=None):
        gesehen.update(von=von, bis=bis)
        return []

    db.termine.list_for_mannschaft = _list
    api.list_termine(7, _USER, db, tage_zurueck=30, tage_voraus=60)

    heute = date.today()
    assert gesehen['von'] == (heute - timedelta(days=30)).isoformat()
    assert gesehen['bis'] == (heute + timedelta(days=60)).isoformat()


def test_termin_liste_markiert_laufenden():
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.termine.list_for_mannschaft = lambda mid, von=None, bis=None: [
        _termin(id=54, typ='training', beginn='2026-08-15T19:00', gegner=None),
        _termin(id=55),
    ]
    result = api.list_termine(7, _USER, db)
    assert result['laufend_id'] == 55
    # Neueste zuerst, damit die Auswahl beim Nachbuchen oben anfängt.
    assert [t['id'] for t in result['termine']] == [55, 54]
    assert result['termine'][0]['label'] == 'Spiel 16.08. 15:00 · SV X'
    assert result['termine'][1]['label'] == 'Training 15.08. 19:00'
    assert result['termine'][0]['laufend'] is True


def test_matrix_ergaenzt_spalte_fuer_abgeschalteten_artikel():
    """#167: Artikel mit Umsatz im Ausschnitt, der nicht mehr im aktiven Katalog
    steht, bekommt seine Spalte über list_fuer_ids zurück — als ausser_dienst."""
    db = _db(wart=True)
    db.clubdeckel_buchungen.matrix = lambda did, von=None, bis=None, termin_id=None: {
        'zellen': {"11:99": {"anzahl": 2, "betrag": Decimal('3.00')}},
        'je_artikel': {99: {"artikel_id": 99, "anzahl": 2, "betrag": Decimal('3.00')}},
        'je_mitglied': [{"mitglied_id": 11, "mitglied_name": 'Anna A',
                         "anzahl": 2, "betrag": Decimal('3.00')}],
        'gesamt': Decimal('3.00'),
    }
    db.clubdeckel_artikel.list_fuer_ids = lambda did, ids: (
        [dict(_artikel_mv(id=99, name='Altbier'))] if ids == [99] else [])

    result = api.get_matrix(7, _USER, db)

    spalten = {a['id']: a for a in result['artikel']}
    assert spalten[21]['ausser_dienst'] is False        # aktiver Katalog
    assert spalten[99]['ausser_dienst'] is True         # nur noch alte Buchungen
    assert spalten[99]['summe_anzahl'] == 2
    # Die Aufschlüsselung muss die Gesamtsumme tragen.
    assert sum(a['summe_betrag'] for a in result['artikel']) == result['gesamt']


# ------------------------ Sortiments-Stände je Gruppe (#167, v100) -------------
def test_gruppe_aendern_legt_stand_ab_laufendem_termin_an():
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    rufe = []
    db.clubdeckel_gruppen.neue_generation = (
        lambda gid, tid, name, verk, aktiv, sort, by:
        rufe.append((gid, tid, name, verk)) or (99, {}))

    api.update_gruppe(7, 31, api.GruppeUpdate(name='Getränke',
                                              verkaeufer_mitglied_id=12,
                                              expected_version=1), _USER, db)

    assert rufe == [(31, 55, 'Getränke', 12)]


def test_gruppe_aendern_am_selben_spieltag_bleibt_derselbe_stand():
    """Der Stand gilt schon ab diesem Termin — dann wird er bearbeitet, nicht
    kopiert. Sonst entstünde bei jedem Nachjustieren eine Generation."""
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.clubdeckel_gruppen.get = lambda gid: _gruppe(id=gid, gilt_ab_termin_id=55)
    rufe = []
    db.clubdeckel_gruppen.neue_generation = (
        lambda *a: rufe.append(a) or (99, {}))

    api.update_gruppe(7, 31, api.GruppeUpdate(name='Kaltgetränke',
                                              expected_version=1), _USER, db)

    assert rufe == []          # keine neue Generation


def test_artikel_aendern_erzeugt_generation_und_trifft_die_kopie():
    """Preis/Bezeichnung gehören zum Stand: geändert wird die KOPIE in der neuen
    Generation, nicht das Original des alten Spieltags."""
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.clubdeckel_gruppen.neue_generation = (
        lambda gid, tid, name, verk, aktiv, sort, by: (99, {21: 77}))
    db.clubdeckel_artikel.get = lambda aid: _artikel(id=aid)
    geaendert = []
    db.clubdeckel_artikel.update = (
        lambda aid, gid, name, preis, aktiv, sort, by, version:
        geaendert.append((aid, gid, preis)) or True)

    api.update_artikel(7, 21, api.ArtikelUpdate(name='Bier', preis=2.0,
                                                gruppe_id=31,
                                                expected_version=1), _USER, db)

    assert geaendert == [(77, 99, Decimal('2.00'))]   # Kopie in neuer Gruppe


def test_artikel_aendern_ohne_generationswechsel_trifft_das_original():
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.clubdeckel_gruppen.get = lambda gid: _gruppe(id=gid, gilt_ab_termin_id=55)
    geaendert = []
    db.clubdeckel_artikel.update = (
        lambda aid, gid, name, preis, aktiv, sort, by, version:
        geaendert.append(aid) or True)

    api.update_artikel(7, 21, api.ArtikelUpdate(name='Bier', preis=2.0,
                                                gruppe_id=31,
                                                expected_version=1), _USER, db)

    assert geaendert == [21]


def test_konsum_lehnt_artikel_aus_fremdem_stand_ab():
    """Schutz gegen veraltete Ansichten: Ein Artikel, der im Sortiment des
    Ziel-Termins nicht vorkommt, würde Preis und Verkäufer von heute einfrieren."""
    db = _db(wart=True)
    db.clubdeckel_artikel.list_fuer_gruppen = lambda gids, nur_aktive=False: [
        dict(_artikel_mv(id=999))]
    with pytest.raises(HTTPException) as exc:
        api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)
    assert exc.value.status_code == 409


def test_konsum_nimmt_preis_und_verkaeufer_des_standes():
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.clubdeckel_artikel.get_mit_verkaeufer = lambda aid: _artikel_mv(
        id=aid, preis=Decimal('2.40'), verkaeufer_mitglied_id=42)
    gebucht = []
    db.clubdeckel_buchungen.create_konsum = (
        lambda did, mid, aid, aname, menge, preis, verk, by, termin_id=None:
        gebucht.append((preis, verk, termin_id)) or _buchung())

    api.buche_konsum(7, api.KonsumCreate(artikel_id=21), _USER, db)

    assert gebucht == [(Decimal('2.40'), 42, 55)]


def test_katalog_liefert_das_sortiment_des_termins():
    db = _db(wart=True)
    gesehen = {}
    db.clubdeckel_gruppen.list_stand = (
        lambda did, termin_id=None, jetzt=None:
        gesehen.update(termin_id=termin_id) or [_gruppe()])

    api.list_artikel(7, _USER, db, alle=True, termin_id=61)

    assert gesehen == {"termin_id": 61}


def test_gruppen_staende_beschriften_die_basis():
    db = _db(wart=True)
    db.clubdeckel_gruppen.list_generationen = lambda stamm: [
        {"id": 99, "name": 'Getränke', "gilt_ab_termin_id": 55,
         "termin_typ": 'spiel', "termin_beginn": '2026-08-16T15:00',
         "termin_gegner": 'SV X'},
        {"id": 31, "name": 'Getränke', "gilt_ab_termin_id": None,
         "termin_typ": None, "termin_beginn": None, "termin_gegner": None},
    ]

    staende = api.list_gruppen_staende(7, 31, _USER, db)

    assert [s['gilt_ab_label'] for s in staende] == [
        'Spiel 16.08. 15:00 · SV X', 'von Anfang an']


def test_termin_liste_liefert_naechstes_ereignis_als_vorgabe():
    """Der Katalog nimmt das nächste Ereignis als Vorgabe — nicht den laufenden
    Termin, der nach dem Abpfiff noch für Buchungen zuständig bleibt."""
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=54)
    db.termine.get_naechsten = lambda mid, jetzt=None: _termin(id=55)

    result = api.list_termine(7, _USER, db)

    assert result['laufend_id'] == 54
    assert result['naechster_id'] == 55


def test_termin_liste_ohne_kuenftiges_ereignis():
    db = _db()
    db.termine.get_naechsten = lambda mid, jetzt=None: None

    assert api.list_termine(7, _USER, db)['naechster_id'] is None


# ------------ Bestehende Buchungen auf einen neuen Stand umstellen (#167) -----
def test_sortiment_status_ohne_termin_ist_leer():
    assert api.sortiment_status(7, _USER, _db(wart=True)) == {
        "buchungen": 0, "betrag": Decimal("0.00")}


def test_sortiment_status_reicht_den_termin_durch():
    db = _db(wart=True)
    gesehen = {}
    db.clubdeckel_buchungen.zaehle_konsum_fuer_termin = (
        lambda did, tid: gesehen.update(tid=tid) or {"anzahl": 3, "betrag": Decimal('4.50')})

    assert api.sortiment_status(7, _USER, db, termin_id=55)['anzahl'] == 3
    assert gesehen == {"tid": 55}


def _uebernahme_db():
    """Wart-DB mit einer bestehenden Buchung beim Ziel-Termin."""
    db = _db(wart=True)
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    db.clubdeckel_buchungen.konsum_je_artikel = lambda did, tid, aids: [
        {"id": 100, "mitglied_id": 11, "artikel_id": 21, "menge": 2,
         "created_at": '2026-08-16T15:30'}]
    return db


def test_umstellen_storniert_und_bucht_gegen_den_neuen_stand():
    db = _uebernahme_db()
    db.clubdeckel_gruppen.neue_generation = (
        lambda gid, tid, name, verk, aktiv, sort, by: (99, {21: 77}))
    db.clubdeckel_artikel.get_mit_verkaeufer = lambda aid: _artikel_mv(
        id=aid, name='Bier 0,5', preis=Decimal('2.00'), verkaeufer_mitglied_id=42)
    storniert, gebucht = [], []
    db.clubdeckel_buchungen.storno = lambda bid, by: storniert.append(bid) or True
    db.clubdeckel_buchungen.create_konsum = (
        lambda did, mid, aid, aname, menge, preis, verk, by, termin_id=None,
        wert_datum=None: gebucht.append(
            (mid, aid, aname, menge, preis, verk, termin_id, wert_datum))
        or _buchung())

    ergebnis = api.update_artikel(7, 21, api.ArtikelUpdate(
        name='Bier 0,5', preis=2.0, gruppe_id=31, bestand_uebernehmen=True,
        expected_version=1), _USER, db)

    assert storniert == [100]
    # Preis, Bezeichnung UND Verkäufer stammen aus dem neuen Stand; die Uhrzeit
    # der ursprünglichen Buchung bleibt erhalten.
    assert gebucht == [(11, 77, 'Bier 0,5', 2, Decimal('2.00'), 42, 55,
                        '2026-08-16T15:30')]
    assert ergebnis['umgestellt'] == 1


def test_ohne_flag_bleibt_der_bestand_unberuehrt():
    db = _uebernahme_db()
    db.clubdeckel_gruppen.neue_generation = (
        lambda gid, tid, name, verk, aktiv, sort, by: (99, {21: 77}))
    storniert = []
    db.clubdeckel_buchungen.storno = lambda bid, by: storniert.append(bid) or True

    ergebnis = api.update_artikel(7, 21, api.ArtikelUpdate(
        name='Bier', preis=2.0, gruppe_id=31, expected_version=1), _USER, db)

    assert storniert == []
    assert ergebnis['umgestellt'] == 0


def test_verkaeuferwechsel_am_bestehenden_stand_stellt_um():
    """Der Fall, der ohne eigene Behandlung durchgerutscht wäre: Der Stand gilt
    schon ab diesem Spieltag, es entsteht keine neue Generation — die
    Gegenbuchung des Verkäufers hängt aber an jedem einzelnen Strich."""
    db = _uebernahme_db()
    db.clubdeckel_gruppen.get = lambda gid: _gruppe(id=gid, gilt_ab_termin_id=55)
    db.clubdeckel_artikel.get_mit_verkaeufer = lambda aid: _artikel_mv(
        id=aid, verkaeufer_mitglied_id=42)
    storniert, gebucht = [], []
    db.clubdeckel_buchungen.storno = lambda bid, by: storniert.append(bid) or True
    db.clubdeckel_buchungen.create_konsum = (
        lambda did, mid, aid, aname, menge, preis, verk, by, termin_id=None,
        wert_datum=None: gebucht.append(verk) or _buchung())

    ergebnis = api.update_gruppe(7, 31, api.GruppeUpdate(
        name='Getränke', verkaeufer_mitglied_id=42, bestand_uebernehmen=True,
        expected_version=1), _USER, db)

    assert storniert == [100] and gebucht == [42]
    assert ergebnis['umgestellt'] == 1


def test_umstellen_laesst_geloeschte_artikel_in_ruhe():
    """Ein Artikel, den es im neuen Stand nicht mehr gibt, steht nicht in der
    Abbildung — seine Striche bleiben, wo sie sind. Umbuchen ginge auch nicht."""
    db = _uebernahme_db()
    db.clubdeckel_gruppen.neue_generation = (
        lambda gid, tid, name, verk, aktiv, sort, by: (99, {}))
    storniert = []
    db.clubdeckel_buchungen.storno = lambda bid, by: storniert.append(bid) or True

    ergebnis = api.update_gruppe(7, 31, api.GruppeUpdate(
        name='Getränke', bestand_uebernehmen=True, expected_version=1), _USER, db)

    assert storniert == []
    assert ergebnis['umgestellt'] == 0


def test_get_deckel_ohne_termin_hat_keinen_termin_deckel():
    """Ohne laufenden Termin gibt es keine Strichliste — die Kachel blendet die
    Oberfläche dann aus, der Gesamtsaldo bleibt."""
    db = _db()
    gesehen = {}
    db.clubdeckel_buchungen.konsum_fuer_termin = (
        lambda did, mid, tid: gesehen.update(tid=tid) or
        {'summe': Decimal('0'), 'anzahl': {}})

    result = api.get_deckel(7, _USER, db)

    assert gesehen == {"tid": None}          # kein Termin -> keine Einschränkung nötig
    assert result['laufender_termin'] is None
    assert result['mein_termin_summe'] == Decimal('0')
    assert result['artikel'][0]['mein_termin_anzahl'] == 0


def test_get_deckel_zaehlt_die_striche_des_laufenden_termins():
    db = _db()
    db.termine.get_laufenden = lambda mid, jetzt=None: _termin(id=55)
    gesehen = {}
    db.clubdeckel_buchungen.konsum_fuer_termin = (
        lambda did, mid, tid: gesehen.update(tid=tid) or
        {'summe': Decimal('4.50'), 'anzahl': {21: 3}})

    result = api.get_deckel(7, _USER, db)

    assert gesehen == {"tid": 55}
    assert result['mein_termin_summe'] == Decimal('4.50')
    assert result['artikel'][0]['mein_termin_anzahl'] == 3
    assert result['laufender_termin']['label'] == 'Spiel 16.08. 15:00 · SV X'


# ------------- Reihenfolge der Matrix nach Zusage zum Termin (#167) ----------
def test_matrix_stellt_zusagen_nach_oben():
    """Der Wart sucht am Tresen die Leute, die da sind — zugesagt zuerst,
    abgesagt zuletzt, alphabetisch innerhalb der Gruppen."""
    db = _db(wart=True)
    db.termin_zusagen.list_kader_with_zusage = lambda tid: [
        {"mitglied_id": 1, "name": 'Anna Abgesagt', "antwort": 'ab'},
        {"mitglied_id": 2, "name": 'Bernd Offen', "antwort": None},
        {"mitglied_id": 3, "name": 'Clara Dabei', "antwort": 'zu'},
        {"mitglied_id": 4, "name": 'Dora Dabei', "antwort": 'zu'},
        {"mitglied_id": 5, "name": 'Emil Vielleicht', "antwort": 'vielleicht'},
    ]

    result = api.get_matrix(7, _USER, db, termin_id=55)

    assert [m['name'] for m in result['mitglieder']] == [
        'Clara Dabei', 'Dora Dabei',            # zugesagt
        'Bernd Offen', 'Emil Vielleicht',       # offen/vielleicht
        'Anna Abgesagt',                        # abgesagt
    ]
    assert result['mitglieder'][0]['antwort'] == 'zu'


def test_matrix_nutzt_den_kader_des_termins():
    """Mit Termin zählt der Kader vom Termin-Datum, nicht der von heute — bei
    einem alten Spiel stand eine andere Mannschaft auf dem Platz."""
    db = _db(wart=True)
    gesehen = {}
    db.termin_zusagen.list_kader_with_zusage = (
        lambda tid: gesehen.update(tid=tid) or
        [{"mitglied_id": 11, "name": 'Anna A', "antwort": 'zu'}])
    db.list_mannschaft_kader = lambda mid: (_ for _ in ()).throw(
        AssertionError('heutiger Kader darf hier nicht gefragt werden'))

    result = api.get_matrix(7, _USER, db, termin_id=55)

    assert gesehen == {"tid": 55}
    assert [m['mitglied_id'] for m in result['mitglieder']] == [11]


def test_matrix_ohne_termin_nimmt_den_heutigen_kader():
    """Ohne Termin (reiner Zeitraum über die API) gibt es keine Zusagen."""
    db = _db(wart=True)
    db.list_mannschaft_kader = lambda mid: [
        SimpleNamespace(mitglied_id=11, mitglied_vorname='Anna',
                        mitglied_nachname='A', rolle='spieler',
                        von='2020-01-01', bis=None)]

    result = api.get_matrix(7, _USER, db)

    assert [(m['mitglied_id'], m['antwort']) for m in result['mitglieder']] == [(11, None)]
