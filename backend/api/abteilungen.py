from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/abteilungen", tags=["abteilungen"])


class AbteilungWrite(BaseModel):
    name: str
    kuerzel: Optional[str] = None
    beschreibung: Optional[str] = None
    kostenstelle: Optional[int] = None   # Fibu-Kostenstelle (FBASC Feld 07)


class AbteilungUpdate(AbteilungWrite):
    expected_version: int


def _require_read(user):
    if not user.has_permission(Permission.ABTEILUNGEN_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Leseberechtigung")


def _require_write(user):
    if not user.has_permission(Permission.ABTEILUNGEN_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Schreibberechtigung")


def _require_delete(user):
    if not user.has_permission(Permission.ABTEILUNGEN_DELETE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Löschberechtigung")


def _can_delete(db, abteilung_id: int) -> bool:
    return (
        not db.has_active_mitglied_abteilung_references(abteilung_id)
        and not db.has_active_beitragsregel_references(abteilung_id)
    )


@router.get("/")
def list_abteilungen(user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(a) for a in db.list_abteilungen()]


@router.get("/deleted")
def list_deleted(user: CurrentUser, db: DB):
    _require_read(user)
    rows = db.list_deleted_abteilungen()
    return [
        {
            'id':          r['id'],
            'name':        r['name'],
            'kuerzel':     r['kuerzel'],
            'beschreibung': r['beschreibung'],
            'deleted_at':  r['deleted_at'][:19] if r['deleted_at'] else None,
            'deleted_by':  r['deleted_by'],
        }
        for r in rows
    ]


@router.get("/{abteilung_id}")
def get_abteilung(abteilung_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    a = db.get_abteilung(abteilung_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    return asdict(a)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_abteilung(data: AbteilungWrite, user: CurrentUser, db: DB):
    _require_write(user)
    from app.models.abteilung import Abteilung
    abt = Abteilung(name=data.name, kuerzel=data.kuerzel, beschreibung=data.beschreibung,
                    kostenstelle=data.kostenstelle)
    created = db.create_abteilung(abt, created_by=user.username)
    return asdict(created)


@router.put("/{abteilung_id}")
def update_abteilung(abteilung_id: int, data: AbteilungUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    abt = db.get_abteilung(abteilung_id)
    if abt is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    abt.name = data.name
    abt.kuerzel = data.kuerzel
    abt.beschreibung = data.beschreibung
    abt.kostenstelle = data.kostenstelle
    abt.version = data.expected_version
    success = db.update_abteilung(abt, updated_by=user.username)
    if not success:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte neu laden")
    return asdict(db.get_abteilung(abteilung_id))


@router.delete("/{abteilung_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_abteilung(abteilung_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    if db.get_abteilung(abteilung_id) is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    if not _can_delete(db, abteilung_id):
        raise HTTPException(
            status_code=409,
            detail="Abteilung wird noch verwendet und kann nicht gelöscht werden",
        )
    db.mark_abteilung_deleted(abteilung_id, deleted_by=user.username)


@router.post("/{abteilung_id}/restore")
def restore_abteilung(abteilung_id: int, user: CurrentUser, db: DB):
    _require_write(user)
    success = db.restore_abteilung(abteilung_id, restored_by=user.username)
    if not success:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden oder bereits aktiv")
    return asdict(db.get_abteilung(abteilung_id))
