from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from app.db.mitglied_abteilung_repository import VALID_STATUS
from ..core.deps import CurrentUser, DB
from ..core.validation import zuordnungsbeginn_or_400

router = APIRouter(tags=["mitglied-abteilungen"])


class ZuordnungWrite(BaseModel):
    abteilung_id: int
    status: str = 'aktiv'
    von: Optional[str] = None
    bis: Optional[str] = None


class ZuordnungUpdate(BaseModel):
    status: str
    von: Optional[str] = None
    bis: Optional[str] = None
    expected_version: int


def _require_read(user):
    if not user.has_permission(Permission.PERSONEN_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Leseberechtigung")


def _require_write(user):
    if not user.has_permission(Permission.PERSONEN_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Schreibberechtigung")


def _require_delete(user):
    if not user.has_permission(Permission.PERSONEN_DELETE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Löschberechtigung")


@router.get("/mitglieder/{mitglied_id}/abteilungen")
def list_zuordnungen(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(z) for z in db.list_mitglied_abteilungen(mitglied_id)]


@router.post("/mitglieder/{mitglied_id}/abteilungen", status_code=status.HTTP_201_CREATED)
def create_zuordnung(mitglied_id: int, data: ZuordnungWrite, user: CurrentUser, db: DB):
    _require_write(user)
    if data.status not in VALID_STATUS:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status. Erlaubt: {VALID_STATUS}")
    if db.mitglied_abteilung_exists_active(mitglied_id, data.abteilung_id):
        raise HTTPException(status_code=409, detail="Mitglied ist dieser Abteilung bereits zugeordnet")
    zuordnungsbeginn_or_400(db, mitglied_id, data.von)
    zuordnung = db.create_mitglied_abteilung(
        mitglied_id, data.abteilung_id, data.status, data.von, data.bis,
        created_by=user.username,
    )
    return asdict(zuordnung)


@router.put("/mitglieder/{mitglied_id}/abteilungen/{zuordnung_id}")
def update_zuordnung(mitglied_id: int, zuordnung_id: int, data: ZuordnungUpdate,
                     user: CurrentUser, db: DB):
    _require_write(user)
    if data.status not in VALID_STATUS:
        raise HTTPException(status_code=422, detail=f"Ungültiger Status. Erlaubt: {VALID_STATUS}")
    zuordnung = db.get_mitglied_abteilung(zuordnung_id)
    if zuordnung is None or zuordnung.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Zuordnung nicht gefunden")
    zuordnungsbeginn_or_400(db, mitglied_id, data.von)
    success = db.update_mitglied_abteilung(
        zuordnung_id, data.status, data.von, data.bis,
        updated_by=user.username, expected_version=data.expected_version,
    )
    if not success:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_abteilung(zuordnung_id))


@router.delete("/mitglieder/{mitglied_id}/abteilungen/{zuordnung_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zuordnung(mitglied_id: int, zuordnung_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    zuordnung = db.get_mitglied_abteilung(zuordnung_id)
    if zuordnung is None or zuordnung.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Zuordnung nicht gefunden")
    db.mark_mitglied_abteilung_deleted(zuordnung_id, deleted_by=user.username)
