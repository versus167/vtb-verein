"""
Inhaber eines Chips: Mitglied ODER Benutzerkonto (backend/api/schliessanlage.py).

Nicht jeder, der einen Chip bekommt, ist Mitglied — Platzwart, Hausmeister, Betreuer
eines Gastvereins haben ein App-Konto, aber keinen Mitgliedsdatensatz. Geprüft wird
hier die Regel, die der Endpunkt durchsetzt: höchstens ein Inhaber, unbekannte
Benutzer werden abgewiesen, und ein Benutzer MIT Mitgliedsdatensatz landet am
Mitglied (dort hängen Log-Auflösung und Mitglieder-Ansicht).
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
from app.models.schliessanlage import SchluesselChip  # noqa: E402
from backend.api import schliessanlage as api  # noqa: E402


def _user(*perms, role='mitglied'):
    keys = set(perms)
    return SimpleNamespace(
        id=1, username='verwalter', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
        has_permission_global=lambda p: role == 'admin' or p in keys,
        allowed_abteilungen=lambda p: None,
    )


class _ChipRepo:
    """Merkt sich, was tatsächlich geschrieben wurde."""

    def __init__(self, bestand=None):
        self.bestand = bestand or {}
        self.geschrieben = []

    def get(self, chip_id):
        return self.bestand.get(chip_id)

    def create(self, chip, actor):
        self.geschrieben.append(chip)
        chip.id = 42
        return chip

    def update(self, chip, actor):
        self.geschrieben.append(chip)
        return chip

    def find_active_by_externes_konto(self, konto):
        return None            # kein Nachziehen alter Import-Zeilen im Test


def _db(chip_repo, *, users=(), mitglied_je_user=None, mitglieder=()):
    bekannt = {u['id']: u for u in users}
    zuordnung = mitglied_je_user or {}
    return SimpleNamespace(
        schluessel_chips=chip_repo,
        tuer_zutritt_logs=SimpleNamespace(resolve_extern_konto=lambda *a, **k: 0),
        get_user_by_id=lambda uid: bekannt.get(uid),
        get_mitglied_by_user_id=lambda uid: zuordnung.get(uid),
        list_mitglieder=lambda: list(mitglieder),
    )


def _chip_in(**kw):
    daten = {"kartennummer": "4711", "bezeichnung": "Chip blau", "externe_kennung": None,
             "mitglied_id": None, "user_id": None, "aufbewahrungsort": None,
             "status": "aktiv"}
    daten.update(kw)
    return api.ChipIn(**daten)


def _chip_update(**kw):
    daten = {"bezeichnung": "Chip blau", "externe_kennung": None, "mitglied_id": None,
             "user_id": None, "aufbewahrungsort": None, "status": "aktiv", "version": 1}
    daten.update(kw)
    return api.ChipUpdateIn(**daten)


VERWALTER = Permission.SCHLIESSANLAGE_VERWALTEN


# ------------------------------------------------------------------- Anlegen
def test_chip_an_mitglied_bleibt_am_mitglied():
    repo = _ChipRepo()
    api.chip_anlegen(_chip_in(mitglied_id=7), _user(VERWALTER), _db(repo))
    assert (repo.geschrieben[0].mitglied_id, repo.geschrieben[0].user_id) == (7, None)


def test_chip_an_benutzer_ohne_mitgliedsdatensatz():
    """Der eigentliche Fall: Platzwart mit App-Konto, aber ohne Mitgliedschaft."""
    repo = _ChipRepo()
    db = _db(repo, users=[{"id": 9, "username": "platzwart"}])
    api.chip_anlegen(_chip_in(user_id=9), _user(VERWALTER), db)
    assert (repo.geschrieben[0].mitglied_id, repo.geschrieben[0].user_id) == (None, 9)


def test_benutzer_mit_mitgliedsdatensatz_wird_aufs_mitglied_umgeschrieben():
    """Sonst hinge derselbe Mensch je nach Auswahl mal am Konto, mal am Mitglied –
    und die Log-Auflösung (tuer_zutritt_log.mitglied_id) liefe ins Leere."""
    repo = _ChipRepo()
    db = _db(repo, users=[{"id": 9, "username": "marko"}],
             mitglied_je_user={9: SimpleNamespace(id=3)})
    api.chip_anlegen(_chip_in(user_id=9), _user(VERWALTER), db)
    assert (repo.geschrieben[0].mitglied_id, repo.geschrieben[0].user_id) == (3, None)


def test_zwei_inhaber_gleichzeitig_sind_ein_fehler():
    db = _db(_ChipRepo(), users=[{"id": 9, "username": "platzwart"}])
    with pytest.raises(HTTPException) as e:
        api.chip_anlegen(_chip_in(mitglied_id=7, user_id=9), _user(VERWALTER), db)
    assert e.value.status_code == 400 and 'entweder' in e.value.detail


def test_unbekannter_benutzer_wird_abgewiesen():
    """Sonst schlüge erst der Fremdschlüssel zu – mit einem 500 statt einer Ansage."""
    with pytest.raises(HTTPException) as e:
        api.chip_anlegen(_chip_in(user_id=999), _user(VERWALTER), _db(_ChipRepo()))
    assert e.value.status_code == 400 and 'Benutzer' in e.value.detail


def test_chip_anlegen_braucht_das_verwalten_recht():
    with pytest.raises(HTTPException) as e:
        api.chip_anlegen(_chip_in(), _user(Permission.SCHLIESSANLAGE_READ), _db(_ChipRepo()))
    assert e.value.status_code == 403


# ----------------------------------------------------------------- Bearbeiten
def _bestand(**kw):
    daten = {"id": 5, "kartennummer": "4711", "bezeichnung": "Chip blau",
             "status": "aktiv", "version": 1}
    daten.update(kw)
    return {5: SchluesselChip(**daten)}


def test_wechsel_von_mitglied_auf_benutzer_raeumt_die_andere_seite_ab():
    repo = _ChipRepo(_bestand(mitglied_id=7))
    db = _db(repo, users=[{"id": 9, "username": "platzwart"}])
    api.chip_update(5, _chip_update(user_id=9), _user(VERWALTER), db)
    assert (repo.geschrieben[0].mitglied_id, repo.geschrieben[0].user_id) == (None, 9)


def test_inhaber_entfernen_macht_wieder_einen_pool_chip():
    repo = _ChipRepo(_bestand(user_id=9))
    api.chip_update(5, _chip_update(aufbewahrungsort='Geschäftsstelle'),
                    _user(VERWALTER), _db(repo))
    geschrieben = repo.geschrieben[0]
    assert (geschrieben.mitglied_id, geschrieben.user_id) == (None, None)
    assert geschrieben.aufbewahrungsort == 'Geschäftsstelle'


def test_update_prueft_den_inhaber_bevor_es_schreibt():
    repo = _ChipRepo(_bestand(mitglied_id=7))
    with pytest.raises(HTTPException) as e:
        api.chip_update(5, _chip_update(mitglied_id=7, user_id=9), _user(VERWALTER),
                        _db(repo, users=[{"id": 9, "username": "platzwart"}]))
    assert e.value.status_code == 400
    assert repo.geschrieben == []


# --------------------------------------------------------------- User-Picker
def test_user_lookup_meldet_wer_schon_mitglied_ist(monkeypatch):
    """Der Picker soll dieselbe Person nicht zweimal anbieten."""
    class _UserService:
        def __init__(self, db):
            pass

        def list_all(self):
            return [SimpleNamespace(id=9, username='platzwart', active=True),
                    SimpleNamespace(id=10, username='marko', active=True),
                    SimpleNamespace(id=11, username='alt', active=False)]

    monkeypatch.setattr('app.services.user_service.UserService', _UserService)
    db = _db(_ChipRepo(), mitglieder=[SimpleNamespace(id=3, user_id=10),
                                      SimpleNamespace(id=4, user_id=None)])
    liste = api.user_lookup(_user(VERWALTER), db)
    assert liste == [{"id": 9, "username": "platzwart", "active": True, "mitglied_id": None},
                     {"id": 10, "username": "marko", "active": True, "mitglied_id": 3}]
