"""
Admin-Endpunkte für die Konsistenzprüfung der Daten-Beziehungen.

Die Prüfung (``GET /pruefung``) ist read-only: sie findet aktive Datensätze, die auf einen
soft-gelöschten Parent zeigen – Beziehungen, die die FK-Constraints (ohne Papierkorb-
Kenntnis) nicht abdecken. Daneben gibt es gezielte, einmalige Altlast-Reparaturen
(``POST /reparatur/...``), die genau EINEN klar umrissenen Alt-Zustand bereinigen.

Nur für Admins startbar (``role == 'admin'``), nicht über eine einzelne Permission.
"""
from fastapi import APIRouter, HTTPException, Request, status

from app.services.konsistenz_service import KonsistenzService
from ..core.deps import CurrentUser, DB
from .auth import _client_ip

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


@router.post("/reparatur/verwaiste-rechte")
def konsistenz_reparatur_verwaiste_rechte(request: Request, user: CurrentUser, db: DB):
    """Einmalige Altlast-Bereinigung: entzieht (soft) die Rechte bereits gelöschter Benutzer.

    Deckt genau den Befund ``user_permissions -> users`` ab und entspricht dem heutigen
    Verhalten beim Benutzer-Löschen. Idempotent – ein zweiter Aufruf bereinigt 0 Zeilen.
    """
    _require_admin(user)
    ergebnis = KonsistenzService(db).repariere_verwaiste_rechte(actor=user.username)
    try:
        db.access_log_repository.log(
            "konsistenz_reparatur_verwaiste_rechte", category="konsistenz",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{ergebnis['bereinigt']} verwaiste Rechte-Einträge bereinigt",
        )
    except Exception:
        pass
    return ergebnis
