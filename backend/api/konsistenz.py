"""
Admin-Endpunkt für die Konsistenzprüfung der Daten-Beziehungen.

Read-only: findet aktive Datensätze, die auf einen soft-gelöschten Parent zeigen –
Beziehungen, die die FK-Constraints (ohne Papierkorb-Kenntnis) nicht abdecken. Es wird
ausschließlich gelesen, nie geschrieben.

Nur für Admins startbar (``role == 'admin'``), nicht über eine einzelne Permission.
"""
from fastapi import APIRouter, HTTPException, status

from app.services.konsistenz_service import KonsistenzService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/konsistenz", tags=["konsistenz"])


def _require_admin(user) -> None:
    if user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Die Konsistenzprüfung ist nur für Administratoren verfügbar",
        )


@router.get("/pruefung")
def konsistenz_pruefung(user: CurrentUser, db: DB):
    """Read-only-Scan: aktive Kinder, die auf soft-gelöschte Parents zeigen. Ändert NICHTS."""
    _require_admin(user)
    return KonsistenzService(db).pruefung()
