from fastapi import APIRouter, HTTPException, status

from app.models.permission import Permission
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/berichte", tags=["berichte"])


def _require_read(user):
    if not user.has_permission(Permission.BERICHTE_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für Berichte",
        )


@router.get("/statistik")
def get_statistik(user: CurrentUser, db: DB):
    """Aggregierte Vereins-Kennzahlen für das Statistik-Dashboard.

    Bewusst ohne Zahlungsstatus (folgt separat).
    """
    _require_read(user)
    return {
        "kpis":                 db.statistik.kpis(),
        "entwicklung": {
            "jahr":  db.statistik.mitglieder_entwicklung("jahr", 12),
            "monat": db.statistik.mitglieder_entwicklung("monat", 12),
        },
        "altersstruktur":       db.statistik.altersstruktur(),
        "geschlechter":         db.statistik.geschlechterverteilung(),
        "abteilungen":          db.statistik.abteilungsuebersicht(),
    }
