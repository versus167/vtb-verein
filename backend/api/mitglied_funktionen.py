from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from ..core.authz import authorize_permission_delegation
from ..core.deps import CurrentUser, DB
from ..core.scope import require_abteilung, require_mitglied
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


def _pruefe_delegation(db, user, funktion_key: str, abteilung_id) -> None:
    """Delegationsregel für die Zuordnung: Eine Funktion gibt ihre Rechte an den
    Träger weiter — vergeben darf sie deshalb nur, wer diese Rechte selbst hat.

    Funktionen ohne hinterlegte Rechte (rein beschreibende wie „Vorstand" oder
    „Kampfrichter") bleiben davon unberührt: leere Menge, nichts zu prüfen.
    """
    funktion = db.funktionen.get_by_key(funktion_key)
    if funktion is None:
        return  # unbekannter Key – der Endpunkt weist ihn ohnehin mit 422 ab
    rechte = db.funktion_permissions.get_permissions_for_funktion(funktion.id)
    authorize_permission_delegation(user, rechte, abteilung_id=abteilung_id,
                                    anlass="über eine Funktion vergeben")


@router.get("/mitglieder/{mitglied_id}/funktionen")
def list_funktionen(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    require_mitglied(user, db, mitglied_id)
    return [asdict(f) for f in db.list_mitglied_funktionen(mitglied_id)]


@router.post("/mitglieder/{mitglied_id}/funktionen", status_code=status.HTTP_201_CREATED)
def create_funktion(mitglied_id: int, data: FunktionWrite, user: CurrentUser, db: DB):
    _require_write(user)
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_WRITE)
    # Auch die Ziel-Abteilung der Zuordnung, nicht nur das Mitglied: Funktionsrechte
    # tragen den Abteilungs-Scope: Wer sich selbst eine Funktion für eine fremde
    # Abteilung eintragen könnte, hätte sie beim nächsten Request im Scope.
    require_abteilung(user, data.abteilung_id, Permission.PERSONEN_WRITE)
    _pruefe_delegation(db, user, data.funktion, data.abteilung_id)
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
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_WRITE)
    require_abteilung(user, data.abteilung_id, Permission.PERSONEN_WRITE)
    _pruefe_delegation(db, user, data.funktion, data.abteilung_id)
    valid_keys = db.funktionen.list_keys()
    if data.funktion not in valid_keys:
        raise HTTPException(status_code=422, detail=f"Ungültige Funktion. Erlaubt: {valid_keys}")
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    eintrag = db.get_mitglied_funktion(funktion_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Funktionszuordnung nicht gefunden")
    # Auch die bisherige Abteilung: Sonst ließe sich eine fremde Zuordnung
    # in den eigenen Bereich umschreiben.
    require_abteilung(user, eintrag.abteilung_id, Permission.PERSONEN_WRITE)
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
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_DELETE)
    eintrag = db.get_mitglied_funktion(funktion_id)
    if eintrag is None or eintrag.mitglied_id != mitglied_id:
        raise HTTPException(status_code=404, detail="Funktionszuordnung nicht gefunden")
    require_abteilung(user, eintrag.abteilung_id, Permission.PERSONEN_DELETE)
    db.mark_mitglied_funktion_deleted(funktion_id, deleted_by=user.username)
