"""Teamtresor-API (#98, backend/api/clubdeckel.py) — Stub-basiert.

Zugriffsmatrix der teaminternen Stufen (mitglied < wart < verwalten, Admin-Bypass)
und die Validierungen der Buchungs-Endpunkte im korrigierten Modell (konsum/
verkauf/einkauf/zahlung/beitrag, Gruppen mit Verkäufer, Team-Saldo). Die
SQL-Seite (Kader-CTE, Salden, Paar-Buchungen, Beitragslauf) deckt
test_clubdeckel_integration ab.
"""
import sys
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
    base = dict(id=7, mannschaft_id=3, name='Teamtresor Erste', aktiv=1,
                beitrag=None, beitrag_ab=None, zahlungsempfaenger_mitglied_id=None,
                zahlweg_iban=None, zahlweg_wero=None, zahlweg_paypal=None, **_AUDIT)
    base.update(kw)
    return Clubdeckel(**base)


def _gruppe(**kw):
    base = dict(id=31, deckel_id=7, name='Getränke', verkaeufer_mitglied_id=None,
                aktiv=1, sortierung=0, **_AUDIT)
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
                notiz=None, artikel_name='Bier', gegen_name='Team', **_AUDIT)
    base.update(kw)
    return ClubdeckelBuchung(**base)


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
            get=lambda gid: _gruppe(id=gid),
            list_for_deckel=lambda did: [_gruppe()],
            create=lambda *a: _gruppe(),
            update=lambda *a: True,
            has_active_artikel=lambda gid: False,
            mark_deleted=lambda *a: True,
        ),
        clubdeckel_artikel=SimpleNamespace(
            get=lambda aid: _artikel(id=aid),
            get_mit_verkaeufer=lambda aid: _artikel_mv(id=aid),
            list_for_deckel=lambda did, nur_aktive=False: [dict(
                _artikel_mv(), gruppe_name='Getränke', verkaeufer_name=None)],
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
            mit_storniert=False: [_buchung()],
            create_konsum=lambda *a: _buchung(),
            create_zahlung=lambda *a, **k: 'ref123',
            create_einkauf=lambda *a: _buchung(typ='einkauf', betrag=Decimal('20')),
            create_an_verkauf=lambda *a, **k: 'refAV',
            buche_faellige_beitraege=lambda *a, **k: 0,
            storno=lambda *a: True,
            restore=lambda *a, **k: True,
            salden=lambda did: [],
            saldo_for_mitglied=lambda did, mid: Decimal('-3.00'),
            konsum_24h=lambda did, mid: {'summe': Decimal('3.00'), 'anzahl': {21: 2}},
            letzte_konsum_id=lambda did, mid, aid: 100,
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


def test_get_deckel_liefert_24h_striche():
    result = api.get_deckel(7, _USER, _db())
    assert result['mein_24h_summe'] == Decimal('3.00')
    assert result['artikel'][0]['mein_24h_anzahl'] == 2


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
    assert seen == ['Teamtresor Erste']


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

    def create_konsum(did, mid, aid, aname, menge, preis, verkaeufer, by):
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
    db.clubdeckel_buchungen.letzte_konsum_id = lambda did, mid, aid: None
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
