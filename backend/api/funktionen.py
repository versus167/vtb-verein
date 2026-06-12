from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/funktionen", tags=["funktionen"])


class FunktionCreate(BaseModel):
    key: str
    name: str
    beschreibung: Optional[str] = None


class FunktionUpdate(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    expected_version: int


def _require_admin(user):
    if user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur Admins")


@router.get("")
def list_funktionen(db: DB):
    return [asdict(f) for f in db.funktionen.list_all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_funktion(data: FunktionCreate, user: CurrentUser, db: DB):
    _require_admin(user)
    if not data.key.strip() or not data.name.strip():
        raise HTTPException(status_code=422, detail="Key und Name dürfen nicht leer sein")
    key = data.key.strip().lower().replace(' ', '_')
    if db.funktionen.get_by_key(key):
        raise HTTPException(status_code=409, detail=f"Funktion mit Key '{key}' existiert bereits")
    f = db.funktionen.create(key, data.name.strip(), data.beschreibung, created_by=user.username)
    return asdict(f)


@router.put("/{funktion_id}")
def update_funktion(funktion_id: int, data: FunktionUpdate, user: CurrentUser, db: DB):
    _require_admin(user)
    if not data.name.strip():
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    ok = db.funktionen.update(
        funktion_id, data.name.strip(), data.beschreibung,
        updated_by=user.username, expected_version=data.expected_version,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    f = db.funktionen.get(funktion_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Funktion nicht gefunden")
    return asdict(f)


@router.delete("/{funktion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_funktion(funktion_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    ok = db.funktionen.mark_deleted(funktion_id, deleted_by=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Funktion nicht gefunden")


# ---------------------------------------------------------------------------
# Berechtigungen einer Funktion (Berechtigungsmatrix, siehe BERECHTIGUNGEN.md)
# ---------------------------------------------------------------------------

class FunktionPermissionsWrite(BaseModel):
    permissions: list[str]


@router.get("/{funktion_id}/permissions")
def get_funktion_permissions(funktion_id: int, user: CurrentUser, db: DB):
    """Berechtigungen einer Funktion lesen. Sichtbar für, wer Berechtigungen verwalten darf."""
    if user.role != 'admin' and not user.has_permission(Permission.PERSONEN_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung für Berechtigungsverwaltung")
    f = db.funktionen.get(funktion_id)  # liefert nur aktive (deleted_at IS NULL)
    if f is None:
        raise HTTPException(status_code=404, detail="Funktion nicht gefunden")
    return {
        'funktion': asdict(f),
        'permissions': sorted(db.funktion_permissions.get_permissions_for_funktion(funktion_id)),
    }


@router.put("/{funktion_id}/permissions")
def set_funktion_permissions(funktion_id: int, data: FunktionPermissionsWrite,
                             user: CurrentUser, db: DB):
    """Berechtigungen einer Funktion setzen – hart Admin-only.

    Die Funktions-Matrix steuert mittelbar die Rechte aller Träger dieser Funktion;
    ihre Pflege ist daher bewusst auf Admins beschränkt (Selbst-Eskalations-Sperre)."""
    _require_admin(user)
    f = db.funktionen.get(funktion_id)  # liefert nur aktive (deleted_at IS NULL)
    if f is None:
        raise HTTPException(status_code=404, detail="Funktion nicht gefunden")
    valid = set(Permission.all())
    unbekannt = [p for p in data.permissions if p not in valid]
    if unbekannt:
        raise HTTPException(status_code=422, detail=f"Unbekannte Permission(s): {unbekannt}")
    db.funktion_permissions.set_permissions_for_funktion(
        funktion_id, set(data.permissions), actor=user.username,
    )
    return {'permissions': sorted(db.funktion_permissions.get_permissions_for_funktion(funktion_id))}
