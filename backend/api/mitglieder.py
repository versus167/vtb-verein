from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator
from typing import Optional
from app.models.permission import Permission
from ..core.deps import CurrentUser, DB
from ..core.scope import visible_mitglied_ids
from ..core.validation import iban_or_422

router = APIRouter(prefix="/mitglieder", tags=["mitglieder"])


class MitgliedCreate(BaseModel):
    vorname: str
    nachname: str
    mitgliedsnummer: Optional[int] = None
    geburtsdatum: Optional[str] = None
    geschlecht: Optional[str] = None        # 'm' | 'w' | 'd'
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    status: str = "aktiv"
    zahlungsart: str = ""
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None

    @field_validator('geburtsdatum', 'eintrittsdatum', 'austrittsdatum', 'abgerechnet_bis', mode='before')
    @classmethod
    def empty_str_to_none(cls, v): return None if v == '' else v


def _require_read(user):
    if not user.has_permission(Permission.PERSONEN_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Leseberechtigung")


def _require_write(user):
    if not user.has_permission(Permission.PERSONEN_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Schreibberechtigung")


def _require_delete(user):
    if not user.has_permission(Permission.PERSONEN_DELETE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Löschberechtigung")


def _require_eintrittsdatum(value):
    """Ein Vereinsmitglied muss immer ein Eintrittsdatum haben (Ticket #29)."""
    if not (value or '').strip():
        raise HTTPException(status_code=422, detail="Eintrittsdatum ist erforderlich")


@router.get("/")
def list_mitglieder(user: CurrentUser, db: DB):
    _require_read(user)
    mitglieder = db.list_mitglieder()
    visible = visible_mitglied_ids(user, db)  # Abteilungs-Scope (Stufe E)
    if visible is not None:
        mitglieder = [m for m in mitglieder if m.id in visible]
    return [asdict(m) for m in mitglieder]


@router.get("/{mitglied_id}")
def get_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    m = db.get_mitglied(mitglied_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    return asdict(m)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_mitglied(data: MitgliedCreate, user: CurrentUser, db: DB):
    _require_write(user)
    _require_eintrittsdatum(data.eintrittsdatum)
    data.iban = iban_or_422(data.iban)
    from app.models.mitglied import Mitglied
    if data.mitgliedsnummer is None:
        data.mitgliedsnummer = db.get_next_mitgliedsnummer()
    elif not db.is_mitgliedsnummer_available(data.mitgliedsnummer):
        raise HTTPException(status_code=400, detail="Mitgliedsnummer bereits vergeben")
    m = Mitglied(**data.model_dump())
    created = db.create_mitglied(m, created_by=user.username)
    return asdict(created)


@router.put("/{mitglied_id}")
def update_mitglied(mitglied_id: int, data: MitgliedCreate, user: CurrentUser, db: DB):
    _require_write(user)
    _require_eintrittsdatum(data.eintrittsdatum)
    data.iban = iban_or_422(data.iban)
    existing = db.get_mitglied(mitglied_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    for field, value in data.model_dump().items():
        setattr(existing, field, value)
    existing.id = mitglied_id
    success = db.update_mitglied(existing, updated_by=user.username)
    if not success:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte neu laden")
    return asdict(db.get_mitglied(mitglied_id))


@router.delete("/{mitglied_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    existing = db.get_mitglied(mitglied_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    db.mark_mitglied_deleted(mitglied_id, deleted_by=user.username)
