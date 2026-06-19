from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from ..core.deps import CurrentUser, DB
from ..core.validation import zuordnungsbeginn_or_400

router = APIRouter(tags=["mitglied-funktionen"])


class FunktionWrite(BaseModel):
    abteilung_id: Optional[int] = None
    funktion: str
    von: Optional[str] = None
    bis: Optional[str] = None


class FunktionUpdate(FunktionWrite):
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


@router.get("/mitglieder/{mitglied_id}/funktionen")
def list_funktionen(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(f) for f in db.list_mitglied_funktionen(mitglied_id)]


@router.post("/mitglieder/{mitglied_id}/funktionen", status_code=status.HTTP_201_CREATED)
def create_funktion(mitglied_id: int, data: FunktionWrite, user: CurrentUser, db: DB):
    _require_write(user)
    valid_keys = db.funktionen.list_keys()
    if data.funktion not in valid_keys:
        raise HTTPException(status_code=422, detail=f"Ungültige Funktion. Erlaubt: {valid_keys}")
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    zuordnungsbeginn_or_400(db, mitglied_id, data.von)
    funktion = db.create_mitglied_funktion(
        mitglied_id, data.abteilung_id, data.funktion, data.von, data.bis,
        created_by=user.username,
    )
    return asdict(funktion)


@router.put("/mitglieder/{mitglied_id}/funktionen/{funktion_id}")
def update_funktion(mitglied_id: int, funktion_id: int, data: FunktionUpdate,
                    user: CurrentUser, db: DB):
    _require_write(user)
    valid_keys = db.funktionen.list_keys()
    if data.funktion not in valid_keys:
        raise HTTPException(status_code=422, detail=f"Ungültige Funktion. Erlaubt: {valid_keys}")
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    eintrag = db.get_mitglied_funktion(funktion_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Funktionszuordnung nicht gefunden")
    zuordnungsbeginn_or_400(db, mitglied_id, data.von)
    success = db.update_mitglied_funktion(
        funktion_id, data.abteilung_id, data.funktion, data.von, data.bis,
        updated_by=user.username, expected_version=data.expected_version,
    )
    if not success:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_funktion(funktion_id))


@router.delete("/mitglieder/{mitglied_id}/funktionen/{funktion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_funktion(mitglied_id: int, funktion_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    eintrag = db.get_mitglied_funktion(funktion_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Funktionszuordnung nicht gefunden")
    db.mark_mitglied_funktion_deleted(funktion_id, deleted_by=user.username)
