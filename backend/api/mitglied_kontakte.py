from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.models.permission import Permission
from app.db.mitglied_kontakt_repository import VALID_TYPEN, KontaktPrimaerRegelError
from ..core.deps import CurrentUser, DB

router = APIRouter(tags=["mitglied-kontakte"])


class KontaktWrite(BaseModel):
    typ: str
    wert: str
    label: Optional[str] = None
    ist_primaer: bool = False


class KontaktUpdate(KontaktWrite):
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


def _validate_typ(typ: str):
    if typ not in VALID_TYPEN:
        raise HTTPException(status_code=422, detail=f"Ungültiger Typ. Erlaubt: {VALID_TYPEN}")


@router.get("/mitglieder/{mitglied_id}/kontakte")
def list_kontakte(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(k) for k in db.list_mitglied_kontakte(mitglied_id)]


@router.post("/mitglieder/{mitglied_id}/kontakte", status_code=status.HTTP_201_CREATED)
def create_kontakt(mitglied_id: int, data: KontaktWrite, user: CurrentUser, db: DB):
    _require_write(user)
    _validate_typ(data.typ)
    if not data.wert.strip():
        raise HTTPException(status_code=422, detail="Wert darf nicht leer sein")
    try:
        db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    kontakt = db.create_mitglied_kontakt(
        mitglied_id, data.typ, data.wert.strip(), data.label, data.ist_primaer,
        created_by=user.username,
    )
    return asdict(kontakt)


@router.put("/mitglieder/{mitglied_id}/kontakte/{kontakt_id}")
def update_kontakt(mitglied_id: int, kontakt_id: int, data: KontaktUpdate,
                   user: CurrentUser, db: DB):
    _require_write(user)
    _validate_typ(data.typ)
    if not data.wert.strip():
        raise HTTPException(status_code=422, detail="Wert darf nicht leer sein")
    eintrag = db.get_mitglied_kontakt(kontakt_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    try:
        ok = db.update_mitglied_kontakt(
            kontakt_id, data.typ, data.wert.strip(), data.label, data.ist_primaer,
            updated_by=user.username, expected_version=data.expected_version,
        )
    except KontaktPrimaerRegelError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_kontakt(kontakt_id))


@router.put("/mitglieder/{mitglied_id}/kontakte/{kontakt_id}/primaer")
def set_kontakt_primaer(mitglied_id: int, kontakt_id: int, user: CurrentUser, db: DB):
    _require_write(user)
    eintrag = db.get_mitglied_kontakt(kontakt_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    ok = db.update_mitglied_kontakt(
        kontakt_id, eintrag.typ, eintrag.wert, eintrag.label, True,
        updated_by=user.username, expected_version=eintrag.version,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_kontakt(kontakt_id))


@router.delete("/mitglieder/{mitglied_id}/kontakte/{kontakt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kontakt(mitglied_id: int, kontakt_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    eintrag = db.get_mitglied_kontakt(kontakt_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    try:
        db.mark_mitglied_kontakt_deleted(kontakt_id, deleted_by=user.username)
    except KontaktPrimaerRegelError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Self-Service: eigene Kontakte im Profil (kein PERSONEN_*-Recht nötig).
# Autorisierung über Eigentümerschaft: der Kontakt muss zum Mitglied-Datensatz
# des angemeldeten Users gehören. Die Login-E-Mail (users.email) bleibt davon
# unberührt und ist weiterhin nur durch Admins änderbar.
# ---------------------------------------------------------------------------

def _mein_mitglied_or_404(user, db):
    m = db.get_mitglied_by_user_id(user.id)
    if m is None:
        raise HTTPException(status_code=404,
                            detail="Kein Mitglied-Datensatz für diesen Account")
    return m


def _eigener_kontakt_or_404(kontakt_id: int, mitglied_id: int, db):
    eintrag = db.get_mitglied_kontakt(kontakt_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
    return eintrag


@router.get("/personen/mein-mitglied/kontakte")
def list_meine_kontakte(user: CurrentUser, db: DB):
    m = _mein_mitglied_or_404(user, db)
    return [asdict(k) for k in db.list_mitglied_kontakte(m.id)]


@router.post("/personen/mein-mitglied/kontakte", status_code=status.HTTP_201_CREATED)
def create_mein_kontakt(data: KontaktWrite, user: CurrentUser, db: DB):
    m = _mein_mitglied_or_404(user, db)
    _validate_typ(data.typ)
    if not data.wert.strip():
        raise HTTPException(status_code=422, detail="Wert darf nicht leer sein")
    kontakt = db.create_mitglied_kontakt(
        m.id, data.typ, data.wert.strip(), data.label, data.ist_primaer,
        created_by=user.username,
    )
    return asdict(kontakt)


@router.put("/personen/mein-mitglied/kontakte/{kontakt_id}")
def update_mein_kontakt(kontakt_id: int, data: KontaktUpdate, user: CurrentUser, db: DB):
    m = _mein_mitglied_or_404(user, db)
    _validate_typ(data.typ)
    if not data.wert.strip():
        raise HTTPException(status_code=422, detail="Wert darf nicht leer sein")
    _eigener_kontakt_or_404(kontakt_id, m.id, db)
    try:
        ok = db.update_mitglied_kontakt(
            kontakt_id, data.typ, data.wert.strip(), data.label, data.ist_primaer,
            updated_by=user.username, expected_version=data.expected_version,
        )
    except KontaktPrimaerRegelError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_kontakt(kontakt_id))


@router.delete("/personen/mein-mitglied/kontakte/{kontakt_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_mein_kontakt(kontakt_id: int, user: CurrentUser, db: DB):
    m = _mein_mitglied_or_404(user, db)
    _eigener_kontakt_or_404(kontakt_id, m.id, db)
    try:
        db.mark_mitglied_kontakt_deleted(kontakt_id, deleted_by=user.username)
    except KontaktPrimaerRegelError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
