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
def get_statistik(user: CurrentUser, db: DB, abteilung_id: int | None = None):
    """Aggregierte Kennzahlen für das Statistik-Dashboard.

    Ohne ``abteilung_id`` vereinsweit; mit gesetzter ``abteilung_id`` auf die aktiven
    Mitglieder dieser Abteilung gefiltert. Die Abteilungsliste fürs Dropdown wird
    immer mitgeliefert (kein Zusatz-Recht nötig). Bewusst ohne Zahlungsstatus.
    """
    _require_read(user)
    return {
        "kpis":                 db.statistik.kpis(abteilung_id),
        "entwicklung": {
            "jahr":  db.statistik.mitglieder_entwicklung("jahr", 12, abteilung_id),
            "monat": db.statistik.mitglieder_entwicklung("monat", 12, abteilung_id),
        },
        "altersstruktur":       db.statistik.altersstruktur(abteilung_id),
        "geschlechter":         db.statistik.geschlechterverteilung(abteilung_id),
        # Abteilungs-Übersicht nur vereinsweit (bei Filter auf eine Abteilung redundant).
        "abteilungen":          db.statistik.abteilungsuebersicht() if abteilung_id is None else [],
        "abteilung_optionen":   [{"id": a.id, "name": a.name} for a in db.list_abteilungen()],
    }
