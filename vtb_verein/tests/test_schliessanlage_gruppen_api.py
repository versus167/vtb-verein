"""
Rechtegruppen an Chips (#169, backend/api/schliessanlage.py).

Die Gruppe ist eine Rechte-Abkürzung – deshalb prüft der Router jede betroffene Tür
einzeln gegen den Abteilungs-Scope. Genau das steht hier auf dem Prüfstand: Wer eine
Gruppe pflegen darf, wo abgeriegelt wird und was gar nicht erst in eine Gruppe gehört.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_schliessanlage_chip_inhaber_api).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from app.models.schliessanlage import ChipGruppe  # noqa: E402
from backend.api import schliessanlage as api  # noqa: E402


def _user(*perms, role='mitglied', scoped=None):
    """`scoped` = Abteilungs-IDs, in denen das Verwaltungsrecht gilt (sonst vereinsweit)."""
    keys = set(perms)

    def has_permission_global(p):
        return role == 'admin' or (p in keys and not scoped)

    def has_permission_for_abteilung(p, abteilung_id):
        if role == 'admin' or (p in keys and not scoped):
            return True
        return p in keys and abteilung_id in (scoped or ())

    return SimpleNamespace(
        id=1, username='verwalter', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
        has_permission_global=has_permission_global,
        has_permission_for_abteilung=has_permission_for_abteilung,
        allowed_abteilungen=lambda p: None if has_permission_global(p) else set(scoped or ()),
    )


def _schloss(id, *, abteilung_id=None, extern=False, name=None):
    """`extern` = Fremdanlage ohne Cloud-Anschluss (keine lockId)."""
    return SimpleNamespace(id=id, name=name or f"Tür {id}", abteilung_id=abteilung_id,
                           ttlock_lock_id=None if extern else 3000 + id)


class _GruppeRepo:
    def __init__(self, gruppen=()):
        self.gruppen = {g.id: g for g in gruppen}
        self.geschrieben = []
        self.chips = {}

    def get(self, id):
        return self.gruppen.get(id)

    def list_all(self):
        return list(self.gruppen.values())

    def find_by_name(self, name):
        return next((g for g in self.gruppen.values()
                     if g.name.casefold() == name.casefold()), None)

    def create(self, g, by):
        g.id = 99
        g.schloss_ids = []
        self.gruppen[g.id] = g
        self.geschrieben.append(('create', g.name))
        return g

    def update(self, g, by):
        self.geschrieben.append(('update', g.name))
        return g

    def set_schloesser(self, gruppe_id, schloss_ids, by):
        self.gruppen[gruppe_id].schloss_ids = list(schloss_ids)
        self.geschrieben.append(('schloesser', gruppe_id, list(schloss_ids)))
        return list(schloss_ids)

    def chip_ids(self, gruppe_id):
        return sorted(self.chips.get(gruppe_id, set()))


class _Zutritt:
    """Fängt ab, was der Router an den Service durchreicht."""

    def __init__(self):
        self.aufrufe = []

    def _antwort(self, name, kw):
        self.aufrufe.append((name, kw))
        return {"erteilt": 1, "entzogen": 0, "fehler": []}

    def gruppe_schloesser_setzen(self, **kw):
        return self._antwort('schloesser', kw)

    def gruppe_chip_zuordnen(self, **kw):
        return self._antwort('zuordnen', kw)

    def gruppe_chip_entfernen(self, **kw):
        return self._antwort('entfernen', kw)

    def gruppe_loeschen(self, **kw):
        return self._antwort('loeschen', kw)

    def gruppe_abgleichen(self, **kw):
        return self._antwort('gruppe_abgleich', kw)

    def chip_gruppen_abgleichen(self, **kw):
        return self._antwort('abgleich', kw)


def _db(gruppen=(), schloesser=(), zutritt=None):
    by_id = {s.id: s for s in schloesser}
    return SimpleNamespace(
        chip_gruppen=_GruppeRepo(gruppen),
        tuer_schloesser=SimpleNamespace(get=lambda id: by_id.get(id)),
        zutritt=zutritt or _Zutritt(),
        access_log_repository=SimpleNamespace(log=lambda *a, **k: None),
    )


_REQ = SimpleNamespace(client=None, headers={})


def _gruppe(id=1, name="Übungsleiter", schloss_ids=()):
    g = ChipGruppe(id=id, name=name)
    g.schloss_ids = list(schloss_ids)
    return g


# --------------------------------------------------------------- Rechte

class TestRechte:
    def test_lesen_braucht_nur_das_leserecht(self):
        db = _db(gruppen=[_gruppe()])
        assert api.gruppen_liste(_user(Permission.SCHLIESSANLAGE_READ), db)

    def test_anlegen_ohne_verwaltungsrecht_abgewiesen(self):
        db = _db()
        with pytest.raises(HTTPException) as e:
            api.gruppe_anlegen(api.GruppeIn(name="Übungsleiter"),
                               _user(Permission.SCHLIESSANLAGE_READ), db)
        assert e.value.status_code == 403

    def test_fremde_abteilungstuer_kommt_nicht_in_die_gruppe(self):
        """Sonst wäre die Gruppe der Weg, sich über die eigene Abteilung hinaus
        Rechte zu erteilen."""
        db = _db(gruppen=[_gruppe()], schloesser=[_schloss(1, abteilung_id=7),
                                                  _schloss(2, abteilung_id=9)])
        user = _user(Permission.SCHLIESSANLAGE_VERWALTEN, scoped={7})
        with pytest.raises(HTTPException) as e:
            api.gruppe_schloesser_setzen(1, api.GruppeSchloesserIn(schloss_ids=[1, 2]),
                                         _REQ, user, db)
        assert e.value.status_code == 403 and "Tür 2" in e.value.detail

    def test_eigene_abteilungstuer_ist_erlaubt(self):
        db = _db(gruppen=[_gruppe()], schloesser=[_schloss(1, abteilung_id=7)])
        user = _user(Permission.SCHLIESSANLAGE_VERWALTEN, scoped={7})
        api.gruppe_schloesser_setzen(1, api.GruppeSchloesserIn(schloss_ids=[1]),
                                     _REQ, user, db)
        assert db.zutritt.aufrufe[0][0] == 'schloesser'

    def test_auch_das_wegnehmen_wird_geprueft(self):
        """Eine Tür aus der Gruppe zu werfen entzieht sie allen Chips – derselbe
        Eingriff, also dieselbe Prüfung."""
        db = _db(gruppen=[_gruppe(schloss_ids=[2])],
                 schloesser=[_schloss(1, abteilung_id=7), _schloss(2, abteilung_id=9)])
        user = _user(Permission.SCHLIESSANLAGE_VERWALTEN, scoped={7})
        with pytest.raises(HTTPException) as e:
            api.gruppe_schloesser_setzen(1, api.GruppeSchloesserIn(schloss_ids=[1]),
                                         _REQ, user, db)
        assert e.value.status_code == 403 and "Tür 2" in e.value.detail

    def test_chip_zuordnen_verlangt_alle_tueren_der_gruppe(self):
        db = _db(gruppen=[_gruppe(schloss_ids=[1, 2])],
                 schloesser=[_schloss(1, abteilung_id=7), _schloss(2, abteilung_id=9)])
        user = _user(Permission.SCHLIESSANLAGE_VERWALTEN, scoped={7})
        with pytest.raises(HTTPException) as e:
            api.gruppe_chip_zuordnen(1, api.GruppeChipIn(chip_id=5), _REQ, user, db)
        assert e.value.status_code == 403


# --------------------------------------------------------------- Fachregeln

class TestGruppenpflege:
    def test_fremdanlage_gehoert_nicht_in_eine_gruppe(self):
        """Ein Schloss ohne Cloud-Anschluss lässt sich nicht anlernen – die Gruppe
        verspräche etwas, das nie an der Tür ankommt."""
        db = _db(gruppen=[_gruppe()],
                 schloesser=[_schloss(1, extern=True, name="Tor Einfahrt")])
        with pytest.raises(HTTPException) as e:
            api.gruppe_schloesser_setzen(1, api.GruppeSchloesserIn(schloss_ids=[1]),
                                         _REQ, _user(role='admin'), db)
        assert e.value.status_code == 400 and "Fremdanlage" in e.value.detail

    def test_unbekanntes_schloss_ist_ein_404(self):
        db = _db(gruppen=[_gruppe()], schloesser=[])
        with pytest.raises(HTTPException) as e:
            api.gruppe_schloesser_setzen(1, api.GruppeSchloesserIn(schloss_ids=[42]),
                                         _REQ, _user(role='admin'), db)
        assert e.value.status_code == 404

    def test_name_ist_pflicht(self):
        db = _db()
        with pytest.raises(HTTPException) as e:
            api.gruppe_anlegen(api.GruppeIn(name="   "), _user(role='admin'), db)
        assert e.value.status_code == 400

    def test_doppelter_name_wird_abgewiesen(self):
        """Zwei „Übungsleiter" wären beim Zuordnen nicht zu unterscheiden."""
        db = _db(gruppen=[_gruppe(name="Übungsleiter")])
        with pytest.raises(HTTPException) as e:
            api.gruppe_anlegen(api.GruppeIn(name="übungsleiter"), _user(role='admin'), db)
        assert e.value.status_code == 409

    def test_anlegen_nimmt_die_tueren_gleich_mit(self):
        db = _db(schloesser=[_schloss(1)])
        api.gruppe_anlegen(api.GruppeIn(name="Übungsleiter", schloss_ids=[1]),
                           _user(role='admin'), db)
        assert ('schloesser', 99, [1]) in db.chip_gruppen.geschrieben

    def test_unbekannte_gruppe_ist_ein_404(self):
        db = _db()
        with pytest.raises(HTTPException) as e:
            api.gruppe_detail(7, _user(Permission.SCHLIESSANLAGE_READ), db)
        assert e.value.status_code == 404


# --------------------------------------------------------------- Durchreichen

class TestAbgleichDurchreichen:
    def test_zuordnen_reicht_chip_und_benutzer_durch(self):
        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1)])
        antwort = api.gruppe_chip_zuordnen(1, api.GruppeChipIn(chip_id=5), _REQ,
                                           _user(role='admin'), db)
        name, kw = db.zutritt.aufrufe[0]
        assert name == 'zuordnen'
        assert kw['gruppe_id'] == 1 and kw['chip_id'] == 5
        assert kw['erteilt_von'] == 1 and kw['actor'] == 'verwalter'
        assert antwort['abgleich']['erteilt'] == 1

    def test_entfernen_reicht_durch(self):
        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1)])
        api.gruppe_chip_entfernen(1, 5, _REQ, _user(role='admin'), db)
        name, kw = db.zutritt.aufrufe[0]
        assert name == 'entfernen' and kw['chip_id'] == 5

    def test_nachfassen_ruft_den_abgleich(self):
        db = _db()
        api.chip_gruppen_abgleich(5, _REQ, _user(role='admin'), db)
        name, kw = db.zutritt.aufrufe[0]
        assert name == 'abgleich' and kw['chip_id'] == 5

    def test_gruppen_abgleich_fasst_fuer_alle_traeger_nach(self):
        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1)])
        api.gruppe_abgleich(1, _REQ, _user(role='admin'), db)
        name, kw = db.zutritt.aufrufe[0]
        assert name == 'gruppe_abgleich' and kw['gruppe_id'] == 1

    def test_gruppen_abgleich_prueft_den_scope(self):
        """Nachfassen erteilt Türen – dieselbe Prüfung wie beim Zuordnen."""
        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1, abteilung_id=9)])
        user = _user(Permission.SCHLIESSANLAGE_VERWALTEN, scoped={7})
        with pytest.raises(HTTPException) as e:
            api.gruppe_abgleich(1, _REQ, user, db)
        assert e.value.status_code == 403

    def test_cloud_fehler_wird_zu_502(self):
        from app.services.ttlock_client import TTLockError

        class _Kaputt(_Zutritt):
            def gruppe_chip_zuordnen(self, **kw):
                raise TTLockError("Gateway offline", errcode=-3003)

        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1)],
                 zutritt=_Kaputt())
        with pytest.raises(HTTPException) as e:
            api.gruppe_chip_zuordnen(1, api.GruppeChipIn(chip_id=5), _REQ,
                                     _user(role='admin'), db)
        assert e.value.status_code == 502

    def test_unbekannter_chip_wird_zu_400(self):
        class _Kaputt(_Zutritt):
            def gruppe_chip_zuordnen(self, **kw):
                raise ValueError("Chip nicht gefunden")

        db = _db(gruppen=[_gruppe(schloss_ids=[1])], schloesser=[_schloss(1)],
                 zutritt=_Kaputt())
        with pytest.raises(HTTPException) as e:
            api.gruppe_chip_zuordnen(1, api.GruppeChipIn(chip_id=99), _REQ,
                                     _user(role='admin'), db)
        assert e.value.status_code == 400
