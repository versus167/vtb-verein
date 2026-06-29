"""
API-Endpunkte für die Zutrittskontrolle / Schließanlage (TT-Lock), Phase 1.

Master-Detail:
- Schlösser: Liste mit Status (Akku/Online/letzter Schließvorgang); Detail mit
  Zutrittslogs (hinter `schliessanlage.protokoll`) + zugeteilten Chips.
- Chips: Liste (Inhaber/Standort); Detail mit Berechtigungen + Nutzungs-Log
  (hinter `schliessanlage.protokoll`).
- Sync: Inventar + Logs aus der Cloud ziehen (on-demand-Button), `schliessanlage.verwalten`.

Bewegungsdaten (Logs) sind DSGVO-sensibel → eigenes Recht `schliessanlage.protokoll`.
Chip-/Schloss-Stammdatenpflege ist reine DB-Arbeit (kein Cloud-Write in Phase 1).
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.services.zutritt_service import ZutrittNichtKonfiguriertError
from ..core.deps import CurrentUser, DB
from .auth import _client_ip

router = APIRouter(prefix="/schliessanlage", tags=["schliessanlage"])


def _require(user, perm: str, was: str) -> None:
    if not user.has_permission(perm):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Keine Berechtigung: {was}")


class SchlossUpdateIn(BaseModel):
    name: str
    standort: Optional[str] = None
    abteilung_id: Optional[int] = None
    notiz: Optional[str] = None
    aktiv: bool = True
    version: int


class ChipIn(BaseModel):
    kartennummer: str
    bezeichnung: Optional[str] = None
    mitglied_id: Optional[int] = None
    aufbewahrungsort: Optional[str] = None
    status: str = "aktiv"


class ChipUpdateIn(BaseModel):
    bezeichnung: Optional[str] = None
    mitglied_id: Optional[int] = None
    aufbewahrungsort: Optional[str] = None
    status: str = "aktiv"
    version: int


# --- Status / Sync ----------------------------------------------------------
@router.get("/status")
def status_info(user: CurrentUser, db: DB):
    """Konto-/Sync-Status für die Seite (konfiguriert? letzter Sync?)."""
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    konto = db.ttlock_konto.get()
    return {
        "konfiguriert": db.zutritt.is_configured(),
        "letzter_sync_at": konto.letzter_sync_at if konto else None,
        "darf_verwalten": user.has_permission(Permission.SCHLIESSANLAGE_VERWALTEN),
        "darf_protokoll": user.has_permission(Permission.SCHLIESSANLAGE_PROTOKOLL),
    }


@router.post("/sync")
def sync(request: Request, user: CurrentUser, db: DB,
         backfill_days: int = 30, logs_only: bool = False):
    """On-demand-Sync (Inventar + Logs) – derselbe Pfad wie der Cron-Command."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage synchronisieren")
    try:
        ergebnis = {}
        if not logs_only:
            ergebnis.update(db.zutritt.inventar_sync())
        ergebnis.update(db.zutritt.logs_sync(backfill_days=backfill_days))
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    try:
        db.access_log_repository.log(
            "schliessanlage_sync", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{ergebnis}",
        )
    except Exception:
        pass
    return ergebnis


# --- Schlösser ---------------------------------------------------------------
@router.get("/schloesser")
def schloesser_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    return db.tuer_schloesser.list_all()


@router.get("/schloesser/{schloss_id}")
def schloss_detail(schloss_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    darf_protokoll = user.has_permission(Permission.SCHLIESSANLAGE_PROTOKOLL)
    return {
        "schloss": schloss,
        "berechtigungen": db.tuer_berechtigungen.list_for_schloss(schloss_id),
        "logs": db.tuer_zutritt_logs.list_for_schloss(schloss_id) if darf_protokoll else [],
        "darf_protokoll": darf_protokoll,
    }


@router.put("/schloesser/{schloss_id}")
def schloss_update(schloss_id: int, data: SchlossUpdateIn, user: CurrentUser, db: DB):
    """Stammdaten (Name/Standort/Abteilung/Notiz/aktiv) – reine DB-Pflege."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    schloss.name = data.name
    schloss.standort = data.standort
    schloss.abteilung_id = data.abteilung_id
    schloss.notiz = data.notiz
    schloss.aktiv = data.aktiv
    schloss.version = data.version
    updated = db.tuer_schloesser.update_stammdaten(schloss, user.username)
    if not updated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Konflikt (zwischenzeitlich geändert) – bitte neu laden")
    return updated


# --- Chips -------------------------------------------------------------------
@router.get("/chips")
def chips_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    return db.schluessel_chips.list_all()


@router.get("/chips/{chip_id}")
def chip_detail(chip_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    chip = db.schluessel_chips.get(chip_id)
    if not chip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
    darf_protokoll = user.has_permission(Permission.SCHLIESSANLAGE_PROTOKOLL)
    return {
        "chip": chip,
        "berechtigungen": db.tuer_berechtigungen.list_for_chip(chip_id),
        "logs": db.tuer_zutritt_logs.list_for_chip(chip_id) if darf_protokoll else [],
        "darf_protokoll": darf_protokoll,
    }


@router.post("/chips", status_code=status.HTTP_201_CREATED)
def chip_anlegen(data: ChipIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.models.schliessanlage import SchluesselChip
    chip = SchluesselChip(
        kartennummer=data.kartennummer, bezeichnung=data.bezeichnung,
        mitglied_id=data.mitglied_id, aufbewahrungsort=data.aufbewahrungsort,
        status=data.status,
    )
    return db.schluessel_chips.create(chip, user.username)


@router.put("/chips/{chip_id}")
def chip_update(chip_id: int, data: ChipUpdateIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    chip = db.schluessel_chips.get(chip_id)
    if not chip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
    chip.bezeichnung = data.bezeichnung
    chip.mitglied_id = data.mitglied_id
    chip.aufbewahrungsort = data.aufbewahrungsort
    chip.status = data.status
    chip.version = data.version
    updated = db.schluessel_chips.update(chip, user.username)
    if not updated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Konflikt (zwischenzeitlich geändert) – bitte neu laden")
    return updated


@router.delete("/chips/{chip_id}", status_code=status.HTTP_204_NO_CONTENT)
def chip_loeschen(chip_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    if not db.schluessel_chips.soft_delete(chip_id, user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
