"""
Admin-Endpunkte für das Prune (endgültiges Aufräumen alter Soft-Deletes).

- Vorschau (Dry-Run): zeigt, was ein vollständiger Lauf entfernen *würde* – löscht nichts.
- Einstellungen: pro Entität einstellbare Tunables (Tage, Mindestanzahl, History-Tage).
  Gespeichert werden nur Abweichungen vom Code-Default (Override-Modell).

Phase 0: noch kein echtes Löschen. Alles geschützt über ``system.config`` (Admin umgeht).
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models.permission import Permission
from app.services.prune_service import ACCESS_LOG_PAGE, PRUNE_REGISTRY, PruneService
from ..core.deps import CurrentUser, DB
from .auth import _client_ip

router = APIRouter(prefix="/prune", tags=["prune"])

# Konfigurierbar sind die Soft-Delete-Bereiche plus der Sonder-Bereich Protokoll-Seitenaufrufe.
_ENTITY_NAMES = {e.name for e in PRUNE_REGISTRY} | {ACCESS_LOG_PAGE}


def _require_admin(user) -> None:
    if not user.has_permission(Permission.SYSTEM_CONFIG):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für die Datenbereinigung (Prune)",
        )


def _require_known_entity(entity: str) -> None:
    if entity not in _ENTITY_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unbekannte Prune-Entität: {entity}",
        )


class EinstellungIn(BaseModel):
    retention_days: int = Field(ge=1, description="Mindest-Verweildauer im Papierkorb (Tage)")
    keep_min: int = Field(ge=0, description="So viele zuletzt Gelöschte bleiben immer erhalten")
    history_retention_days: int = Field(ge=1, description="Aufbewahrung der History (Tage)")


@router.get("/vorschau")
def prune_vorschau(user: CurrentUser, db: DB):
    """Dry-Run: was *würde* ein Prune-Lauf je Entität entfernen? Löscht NICHTS."""
    _require_admin(user)
    return PruneService(db).report()


@router.post("/ausfuehren")
def prune_ausfuehren(request: Request, user: CurrentUser, db: DB, dry_run: bool = True):
    """Führt die Bereinigung aus. Sicherheits-Default ``dry_run=True``.

    Erst mit ``?dry_run=false`` wird tatsächlich (atomar) gelöscht – dann wird der Lauf
    mit Summen ins access_log (category 'prune') protokolliert.
    """
    _require_admin(user)
    ergebnis = PruneService(db).prune(dry_run=dry_run)
    if not dry_run:
        try:
            db.access_log_repository.log(
                "prune_executed", category="prune",
                user_id=user.id, username=user.username, ip=_client_ip(request),
                detail=f"{ergebnis['summe_geloescht']} Datensätze, "
                       f"{ergebnis['summe_history_geloescht']} History-Zeilen gelöscht",
            )
        except Exception:
            pass
    return ergebnis


@router.get("/einstellungen")
def prune_einstellungen(user: CurrentUser, db: DB):
    """Wirksame Tunables je Entität (Override oder Code-Default)."""
    _require_admin(user)
    return PruneService(db).einstellungen()


@router.put("/einstellungen/{entity}")
def prune_einstellungen_setzen(
    entity: str, data: EinstellungIn, request: Request, user: CurrentUser, db: DB
):
    """Setzt einen Override für eine Entität (Tage / Mindestanzahl / History-Tage)."""
    _require_admin(user)
    _require_known_entity(entity)
    gesetzt = db.prune_einstellungen.upsert(
        entity, data.retention_days, data.keep_min, data.history_retention_days,
        updated_by=user.username,
    )
    try:
        db.access_log_repository.log(
            "prune_config_changed", category="prune",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{entity}: retention={data.retention_days}d, keep_min={data.keep_min}, "
                   f"history={data.history_retention_days}d",
        )
    except Exception:
        pass
    return gesetzt


@router.delete("/einstellungen/{entity}", status_code=status.HTTP_204_NO_CONTENT)
def prune_einstellungen_zuruecksetzen(
    entity: str, request: Request, user: CurrentUser, db: DB
):
    """Entfernt den Override → Entität fällt auf den Code-Default zurück."""
    _require_admin(user)
    _require_known_entity(entity)
    db.prune_einstellungen.delete(entity, deleted_by=user.username)
    try:
        db.access_log_repository.log(
            "prune_config_reset", category="prune",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{entity}: auf Default zurückgesetzt",
        )
    except Exception:
        pass
