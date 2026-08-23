"""
API-Ebene des Fremd-Log-Imports (backend/api/schliessanlage.py).

Geprüft wird, was der Service selbst nicht entscheidet: die Rechte (vereinsweites
Verwalten UND Protokoll – der Bericht ist selbst eine Nutzungsauswertung), die
Vorschau als schreibfreier Pfad, das Nachziehen der Zuordnung beim Pflegen eines
Chips und die Sperre gegen Fernsteuern eines externen Schlosses.

Direkte Endpunkt-Aufrufe mit Stubs (Muster wie test_zugang_freischalten_api).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from app.models.schliessanlage import (  # noqa: E402
    SchliessanlageEinstellungen, SchluesselChip, TuerSchloss, QUELLE_EXTERN,
)
from backend.api import schliessanlage as api  # noqa: E402

CSV = (
    b"Unlock Account,Unlock Type, Lock Name,Unlock Time\n"
    b"Chip8,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05\n"
)


# --------------------------------------------------------------------- Stubs
def _user(*perms, role='mitglied', global_perms=None):
    keys, glob = set(perms), set(global_perms if global_perms is not None else perms)
    return SimpleNamespace(
        id=1, username='verwalter', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
        has_permission_global=lambda p: role == 'admin' or p in glob,
        allowed_abteilungen=lambda p: None,
    )


class _ChipRepo:
    def __init__(self, chips=()):
        self.chips = list(chips)

    def find_active_by_externes_konto(self, konto):
        norm = (konto or '').strip().lower()
        if not norm:
            return None
        for feld in ('externe_kennung', 'bezeichnung', 'kartennummer'):
            for c in self.chips:
                if (getattr(c, feld) or '').strip().lower() == norm:
                    return c
        return None


class _SchlossRepo:
    def __init__(self, schloesser=()):
        self.schloesser = list(schloesser)
        self.angelegt = []

    def get(self, id):
        return next((s for s in self.schloesser if s.id == id), None)

    def find_extern_by_name(self, name):
        return next((s for s in self.schloesser if s.quelle == QUELLE_EXTERN
                     and s.name.lower() == name.lower()), None)

    def create_extern(self, *, name, standort=None, notiz=None, by='SYSTEM'):
        s = TuerSchloss(id=99, name=name, quelle=QUELLE_EXTERN)
        self.angelegt.append(s); self.schloesser.append(s)
        return s

    def update_letztes_event(self, *a, **kw):
        pass


class _LogRepo:
    def __init__(self):
        self.rows = []
        self.aufrufe = []

    def extern_keys_for_schloss(self, schloss_id):
        return set()

    def insert_extern_if_new(self, log):
        self.rows.append(log); return True

    def resolve_extern_konto(self, konto, *, chip_id, mitglied_id, user_id=None):
        self.aufrufe.append((konto, chip_id))
        return 1


class _DB:
    def __init__(self, chips=(), schloesser=()):
        self.schluessel_chips = _ChipRepo(chips)
        self.tuer_schloesser = _SchlossRepo(schloesser)
        self.tuer_zutritt_logs = _LogRepo()
        self.access_log_repository = SimpleNamespace(log=lambda *a, **kw: None)


class _Upload:
    filename = 'Tor.csv'

    def __init__(self, daten=CSV):
        self._daten = daten
        self._pos = 0

    async def read(self, size: int = -1):
        """Wie ``UploadFile.read``: liefert häppchenweise, wenn eine Größe kommt.

        Der Import liest gestückelt ein (s. ``lese_upload``), damit ein riesiger
        Upload nicht erst vollständig im Speicher landet – die Attrappe muss das
        mitmachen, sonst prüft der Test eine Schnittstelle, die es nicht gibt.
        """
        rest = self._daten[self._pos:]
        happen = rest if size < 0 else rest[:size]
        self._pos += len(happen)
        return happen


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'), headers={})


def _import(user, db, *, commit=False, datei=None):
    return asyncio.run(api.log_import(_request(), user, db,
                                      file=datei or _Upload(), commit=commit))


# Wer den Import ausführen darf: beide Rechte, beide vereinsweit.
_BERECHTIGT = (Permission.SCHLIESSANLAGE_VERWALTEN, Permission.SCHLIESSANLAGE_PROTOKOLL)


# ------------------------------------------------------------------- Rechte
def test_import_braucht_vereinsweites_verwalten_recht():
    # Abteilungsgebundenes Verwalten reicht nicht: der Import kann ein Schloss anlegen.
    user = _user(*_BERECHTIGT, global_perms={Permission.SCHLIESSANLAGE_PROTOKOLL})
    with pytest.raises(HTTPException) as e:
        _import(user, _DB())
    assert e.value.status_code == 403 and 'vereinsweit' in e.value.detail


def test_import_braucht_das_protokollrecht():
    """Der Bericht nennt Person, Anzahl und Zeitraum – das ist genau die Auswertung,
    die `schliessanlage.protokoll` schützt. Verwalten allein darf daran nicht vorbei."""
    user = _user(Permission.SCHLIESSANLAGE_VERWALTEN)
    with pytest.raises(HTTPException) as e:
        _import(user, _DB())
    assert e.value.status_code == 403 and 'Zutrittsprotokoll' in e.value.detail


def test_abteilungsgebundenes_protokollrecht_reicht_nicht():
    """Der Bericht geht über alle Schlösser der Datei, nicht nur über eine Abteilung."""
    user = _user(*_BERECHTIGT, global_perms={Permission.SCHLIESSANLAGE_VERWALTEN})
    with pytest.raises(HTTPException) as e:
        _import(user, _DB())
    assert e.value.status_code == 403 and 'Zutrittsprotokoll' in e.value.detail


def test_import_ohne_jedes_recht_ist_verboten():
    with pytest.raises(HTTPException) as e:
        _import(_user(), _DB())
    assert e.value.status_code == 403


def test_leere_datei_wird_abgewiesen():
    with pytest.raises(HTTPException) as e:
        _import(_user(*_BERECHTIGT), _DB(), datei=_Upload(b''))
    assert e.value.status_code == 422


def test_fremdes_dateiformat_meldet_422_statt_500():
    with pytest.raises(HTTPException) as e:
        _import(_user(*_BERECHTIGT), _DB(), datei=_Upload(b"Vorname,Nachname\nMax,Muster\n"))
    assert e.value.status_code == 422 and 'Kopfzeile' in e.value.detail


def test_status_meldet_import_erst_bei_beiden_rechten():
    """Der Button hängt an einem eigenen Flag – sonst müsste das Frontend die Regel
    des Endpoints nachbauen und könnte auseinanderlaufen."""
    db = _DB()
    db.ttlock_konto = SimpleNamespace(get=lambda: None)
    db.zutritt = SimpleNamespace(is_configured=lambda: False)
    db.schliessanlage_einstellungen = SimpleNamespace(
        get=lambda: SchliessanlageEinstellungen())

    nur_verwalten = api.status_info(_user(Permission.SCHLIESSANLAGE_VERWALTEN,
                                          Permission.SCHLIESSANLAGE_READ), db)
    assert nur_verwalten['darf_sync'] is True and nur_verwalten['darf_import'] is False

    beides = api.status_info(_user(*_BERECHTIGT, Permission.SCHLIESSANLAGE_READ), db)
    assert beides['darf_import'] is True


# ------------------------------------------------------------------ Vorschau
def test_vorschau_schreibt_nichts_und_liefert_zusammenfassung():
    db = _DB()
    antwort = _import(_user(*_BERECHTIGT), db, commit=False)
    assert antwort['commit'] is False and antwort['neu'] == 1
    assert 'zusammenfassung' in antwort
    assert db.tuer_zutritt_logs.rows == [] and db.tuer_schloesser.angelegt == []


def test_lauf_legt_schloss_an_und_importiert():
    db = _DB()
    antwort = _import(_user(*_BERECHTIGT), db, commit=True)
    assert antwort['neu'] == 1
    assert [s.name for s in db.tuer_schloesser.angelegt] == ['Tor Einfahrt']
    assert len(db.tuer_zutritt_logs.rows) == 1


# ----------------------------------------------- Zuordnung beim Chip pflegen
def test_konto_nachziehen_nur_fuer_den_passenden_chip():
    """Eine gleichlautende Bezeichnung darf keine Zeilen wegschnappen, die per
    gepflegter Kennung einem anderen Chip gehören."""
    gepflegt = SchluesselChip(id=2, kartennummer='222', externe_kennung='Volker1')
    namensgleich = SchluesselChip(id=1, kartennummer='111', bezeichnung='Volker1')
    db = _DB(chips=[namensgleich, gepflegt])

    api._konto_nachziehen(db, gepflegt)
    assert db.tuer_zutritt_logs.aufrufe == [('Volker1', 2), ('222', 2)]

    db.tuer_zutritt_logs.aufrufe.clear()
    api._konto_nachziehen(db, namensgleich)
    # Nur die eigene Kartennummer – 'Volker1' gehört dem Chip mit gepflegter Kennung
    assert db.tuer_zutritt_logs.aufrufe == [('111', 1)]


def test_konto_nachziehen_faellt_auf_bezeichnung_zurueck():
    chip = SchluesselChip(id=3, kartennummer='333', bezeichnung='Chip8')
    db = _DB(chips=[chip])
    assert api._konto_nachziehen(db, chip) == 2             # Bezeichnung + Kartennummer
    assert [k for k, _ in db.tuer_zutritt_logs.aufrufe] == ['Chip8', '333']


# --------------------------------------------------- Externes Schloss sperren
def test_externes_schloss_kann_niemand_oeffnen():
    extern = TuerSchloss(id=5, name='Tor Einfahrt', quelle=QUELLE_EXTERN)
    db = _DB(schloesser=[extern])
    # Selbst ein Admin (hat implizit jedes Recht) bekommt hier False – es gibt dort
    # schlicht keine Fernöffnung, und ein Button, der immer scheitert, wäre eine Lüge.
    assert api._darf_oeffnen(_user(role='admin'), db, extern) is False
