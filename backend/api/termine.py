"""Mannschafts-Termine (#95, Spielbetrieb Etappe 1).

Zugriffsmodell (analog Kassen/Tresor, hier mit dem Kader als ACL): wer am Stichtag
aktiv im Kader einer Mannschaft steht (mitglied_mannschaft, von/bis), liest deren
Termine; die Kader-Rollen trainer/betreuer/uebungsleiter verwalten sie (anlegen,
bearbeiten, absagen, löschen). Nur das übergreifende Verwalten aller Mannschaften
hängt am globalen Recht `termine.verwalten`; Admins dürfen ohnehin alles.

Zeiten sind lokale Wandzeit als TEXT: beginn/ende 'YYYY-MM-DDTHH:MM',
treffpunkt_zeit 'HH:MM'. status wird nicht über PUT geändert, sondern über die
Aktions-Endpunkte /absagen und /reaktivieren (klare Audit-Intention; in Etappe 2
Hook für Benachrichtigungen). serie_id/extern_ref sind noch nicht per API setzbar
(kommen mit Terminserien bzw. DFBnet-Import).
"""
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.db.termin_repository import VALID_TYPEN
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/termine", tags=["termine"])


# --------------------------------------------------------------------------- I/O
class TerminCreate(BaseModel):
    typ: str = 'training'
    beginn: str                              # 'YYYY-MM-DDTHH:MM'
    ende: Optional[str] = None
    ort: Optional[str] = None
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None    # 'HH:MM'
    gegner: Optional[str] = None             # nur typ='spiel'
    heim_auswaerts: Optional[str] = None     # 'heim' | 'auswaerts', nur typ='spiel'
    beschreibung: Optional[str] = None


class TerminUpdate(TerminCreate):
    expected_version: int


class TerminAktion(BaseModel):
    expected_version: int


# ----------------------------------------------------------------- Authorisierung
def _darf_alle_verwalten(user) -> bool:
    return user.role == 'admin' or user.has_permission(Permission.TERMINE_VERWALTEN)


def _zugriff(db: DB, user, mannschaft_id: int) -> Optional[str]:
    """Effektive Stufe auf die Termine einer Mannschaft: 'verwalten' | 'lesen' | None.
    termine.verwalten/Admin => 'verwalten', sonst entscheidet der Kader."""
    if _darf_alle_verwalten(user):
        return 'verwalten'
    return db.termine.get_access_for_user(user.id, mannschaft_id)


def _require_lesen(db: DB, user, mannschaft_id: int) -> str:
    z = _zugriff(db, user, mannschaft_id)
    if z is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Kein Zugriff auf die Termine dieser Mannschaft")
    return z


def _require_verwalten(db: DB, user, mannschaft_id: int) -> None:
    if _zugriff(db, user, mannschaft_id) != 'verwalten':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung, Termine dieser Mannschaft zu verwalten")


# ------------------------------------------------------------------- Validierung
def _parse_wandzeit(wert: str, feld: str) -> datetime:
    try:
        return datetime.fromisoformat(wert)
    except ValueError:
        raise HTTPException(422, f"{feld} muss das Format JJJJ-MM-TTTHH:MM haben")


def _validate_termin(data: TerminCreate) -> None:
    """Prüft Typ/Zeiten/Spielfelder und normalisiert Nicht-Spiel-Termine
    (gegner/heim_auswaerts werden dort serverseitig genullt)."""
    if data.typ not in VALID_TYPEN:
        raise HTTPException(422, f"Ungültiger Typ (erlaubt: {', '.join(VALID_TYPEN)})")
    beginn = _parse_wandzeit(data.beginn, "beginn")
    if data.ende:
        if _parse_wandzeit(data.ende, "ende") < beginn:
            raise HTTPException(422, "Ende darf nicht vor dem Beginn liegen")
    else:
        data.ende = None
    if data.typ == 'spiel':
        if data.heim_auswaerts not in (None, 'heim', 'auswaerts'):
            raise HTTPException(422, "heim_auswaerts muss 'heim' oder 'auswaerts' sein")
    else:
        data.gegner = None
        data.heim_auswaerts = None
    for feld in ('ort', 'treffpunkt', 'gegner', 'beschreibung'):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(data, feld, wert.strip() or None)


# ------------------------------------------------------------------ Mannschaften
@router.get("/mannschaften")
def list_meine_mannschaften(user: CurrentUser, db: DB):
    """Mannschaften, deren Termine der User sehen/verwalten darf – dient dem
    Frontend auch als ACL-Probe (leere Liste => Nav-Punkt ausblenden)."""
    if _darf_alle_verwalten(user):
        return db.termine.list_all_mannschaften()
    return db.termine.list_mannschaften_for_user(user.id)


@router.get("/mannschaften/{mannschaft_id}")
def list_termine(mannschaft_id: int, user: CurrentUser, db: DB,
                 von: Optional[str] = None, bis: Optional[str] = None):
    """Termine einer Mannschaft (von/bis = ISO-Datum, beide inklusiv)."""
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    zugriff = _require_lesen(db, user, mannschaft_id)
    termine = db.termine.list_for_mannschaft(mannschaft_id, von=von, bis=bis)
    return {
        "zugriff": zugriff,
        "darf_verwalten": zugriff == 'verwalten',
        "termine": [asdict(t) for t in termine],
    }


@router.post("/mannschaften/{mannschaft_id}", status_code=status.HTTP_201_CREATED)
def create_termin(mannschaft_id: int, data: TerminCreate, user: CurrentUser, db: DB):
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    _require_verwalten(db, user, mannschaft_id)
    _validate_termin(data)
    t = db.termine.create(
        mannschaft_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username,
    )
    return asdict(t)


# ---------------------------------------------------------------- Meine Termine
@router.get("/meine")
def meine_termine(user: CurrentUser, db: DB,
                  von: Optional[str] = None, bis: Optional[str] = None):
    """Termine aller Mannschaften, in deren Kader der User aktiv steht.
    Ohne von-Filter ab heute (Vergangenes blendet das Frontend explizit ein)."""
    if von is None and bis is None:
        von = date.today().isoformat()
    return db.termine.list_for_user(user.id, von=von, bis=bis)


# --------------------------------------------------------------- Einzel-Termine
@router.put("/{termin_id}")
def update_termin(termin_id: int, data: TerminUpdate, user: CurrentUser, db: DB):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    _validate_termin(data)
    ok = db.termine.update(
        termin_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username, data.expected_version,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.termine.get(termin_id))


def _set_status(termin_id: int, neuer_status: str, data: TerminAktion,
                user, db: DB) -> dict:
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    if t.status == neuer_status:
        raise HTTPException(422, f"Termin ist bereits '{neuer_status}'")
    ok = db.termine.set_status(termin_id, neuer_status, user.username,
                               data.expected_version)
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.termine.get(termin_id))


@router.post("/{termin_id}/absagen")
def absagen(termin_id: int, data: TerminAktion, user: CurrentUser, db: DB):
    return _set_status(termin_id, 'abgesagt', data, user, db)


@router.post("/{termin_id}/reaktivieren")
def reaktivieren(termin_id: int, data: TerminAktion, user: CurrentUser, db: DB):
    return _set_status(termin_id, 'geplant', data, user, db)


@router.delete("/{termin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_termin(termin_id: int, user: CurrentUser, db: DB):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    db.termine.mark_deleted(termin_id, user.username)
