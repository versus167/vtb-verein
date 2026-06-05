from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.db.mannschaft_repository import Mannschaft
from app.db.mitglied_mannschaft_repository import VALID_ROLLEN
from ..core.deps import CurrentUser, DB

router = APIRouter(tags=["mannschaften"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MannschaftCreate(BaseModel):
    abteilung_id: int
    name: str
    saison: Optional[str] = None
    beschreibung: Optional[str] = None


class MannschaftUpdate(MannschaftCreate):
    expected_version: int


class KaderCreate(BaseModel):
    mitglied_id: int
    rolle: str = 'spieler'
    von: Optional[str] = None
    bis: Optional[str] = None


class KaderUpdate(BaseModel):
    rolle: str
    von: Optional[str] = None
    bis: Optional[str] = None
    expected_version: int


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _require_read(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_READ):
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung für Mannschaften")

def _require_write(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_WRITE):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung für Mannschaften")

def _require_delete(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_DELETE):
        raise HTTPException(status_code=403, detail="Keine Löschberechtigung für Mannschaften")

def _validate_rolle(rolle: str):
    if rolle not in VALID_ROLLEN:
        raise HTTPException(status_code=422, detail=f"Ungültige Rolle. Erlaubt: {VALID_ROLLEN}")


# ---------------------------------------------------------------------------
# Mannschaften
# ---------------------------------------------------------------------------

@router.get("/mannschaften")
def list_mannschaften(user: CurrentUser, db: DB, abteilung_id: Optional[int] = None):
    _require_read(user)
    return [asdict(m) for m in db.list_mannschaften(abteilung_id)]


@router.post("/mannschaften", status_code=status.HTTP_201_CREATED)
def create_mannschaft(data: MannschaftCreate, user: CurrentUser, db: DB):
    _require_write(user)
    if not data.name.strip():
        raise HTTPException(status_code=422, detail="Name ist erforderlich")
    m = Mannschaft(abteilung_id=data.abteilung_id, name=data.name.strip(),
                   saison=data.saison, beschreibung=data.beschreibung)
    return asdict(db.create_mannschaft(m, created_by=user.username))


@router.put("/mannschaften/{mannschaft_id}")
def update_mannschaft(mannschaft_id: int, data: MannschaftUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    m = db.get_mannschaft(mannschaft_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    m.abteilung_id = data.abteilung_id
    m.name = data.name.strip()
    m.saison = data.saison
    m.beschreibung = data.beschreibung
    m.version = data.expected_version
    if not db.update_mannschaft(m, updated_by=user.username):
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mannschaft(mannschaft_id))


@router.delete("/mannschaften/{mannschaft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mannschaft(mannschaft_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    if db.mannschaft_has_active_mitglieder(mannschaft_id):
        raise HTTPException(status_code=400, detail="Mannschaft hat noch Kader-Mitglieder – bitte zuerst entfernen")
    db.mark_mannschaft_deleted(mannschaft_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Kader (Mitglied <-> Mannschaft)
# ---------------------------------------------------------------------------

@router.get("/mannschaften/{mannschaft_id}/mitglieder")
def list_kader(mannschaft_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(z) for z in db.list_mannschaft_kader(mannschaft_id)]


@router.post("/mannschaften/{mannschaft_id}/mitglieder", status_code=status.HTTP_201_CREATED)
def add_kader(mannschaft_id: int, data: KaderCreate, user: CurrentUser, db: DB):
    _require_write(user)
    _validate_rolle(data.rolle)
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    try:
        db.get_mitglied(data.mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    z = db.create_mitglied_mannschaft(
        data.mitglied_id, mannschaft_id, data.rolle, data.von, data.bis,
        created_by=user.username,
    )
    return asdict(z)


@router.put("/mannschaften/{mannschaft_id}/mitglieder/{zuordnung_id}")
def update_kader(mannschaft_id: int, zuordnung_id: int, data: KaderUpdate,
                 user: CurrentUser, db: DB):
    _require_write(user)
    _validate_rolle(data.rolle)
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    z = db.get_mitglied_mannschaft(zuordnung_id)
    if z is None or z.mannschaft_id != mannschaft_id:
        raise HTTPException(status_code=404, detail="Kader-Zuordnung nicht gefunden")
    ok = db.update_mitglied_mannschaft(
        zuordnung_id, data.rolle, data.von, data.bis,
        updated_by=user.username, expected_version=data.expected_version,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_mannschaft(zuordnung_id))


@router.delete("/mannschaften/{mannschaft_id}/mitglieder/{zuordnung_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_kader(mannschaft_id: int, zuordnung_id: int, user: CurrentUser, db: DB):
    _require_write(user)
    z = db.get_mitglied_mannschaft(zuordnung_id)
    if z is None or z.mannschaft_id != mannschaft_id:
        raise HTTPException(status_code=404, detail="Kader-Zuordnung nicht gefunden")
    db.mark_mitglied_mannschaft_deleted(zuordnung_id, deleted_by=user.username)


@router.get("/mitglieder/{mitglied_id}/mannschaften")
def list_fuer_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(z) for z in db.list_mitglied_mannschaften(mitglied_id)]
