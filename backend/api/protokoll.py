from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.models.permission import Permission
from ..core.deps import CurrentUser, DB
from .auth import _client_ip, _log_access

router = APIRouter(prefix="/protokoll", tags=["protokoll"])


def _require_read(user):
    if not user.has_permission(Permission.SYSTEM_PROTOKOLL):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für das Zugriffsprotokoll",
        )


class SeitenaufrufIn(BaseModel):
    route_name: str | None = None
    path: str | None = None
    title: str | None = None


@router.post("/seitenaufruf")
def log_seitenaufruf(data: SeitenaufrufIn, request: Request, user: CurrentUser, db: DB):
    """Protokolliert einen Seitenaufruf des eingeloggten Users (category 'page').

    Kein Sonderrecht nötig – jeder eingeloggte User erzeugt Seitenaufrufe. Best-effort:
    ein fehlgeschlagenes Logging darf die Navigation nie stören, daher immer {ok: True}.
    Als detail wird ein lesbarer Seitenbezeichner gespeichert (Titel/Route/Pfad).
    """
    detail = data.title or data.route_name or data.path
    try:
        db.access_log_repository.log(
            "page_view",
            category="page",
            user_id=user.id,
            username=user.username,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            detail=detail,
        )
    except Exception:
        pass
    return {"ok": True}


@router.get("")
def list_protokoll(
    user: CurrentUser,
    db: DB,
    event_type: str | None = None,
    category: str | None = None,
    username: str | None = None,
    user_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Paginierte, gefilterte Sicht auf das Zugriffsprotokoll (neueste zuerst).

    Geschützt über `system.protokoll` (Admin umgeht). Filter sind optional und
    kombinierbar; `since`/`until` sind ISO-Zeitstempel/Datumsangaben.
    """
    _require_read(user)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    repo = db.access_log_repository
    filters = dict(
        event_type=event_type, category=category, username=username,
        user_id=user_id, since=since, until=until,
    )
    return {
        "items": repo.list(limit=limit, offset=offset, **filters),
        "total": repo.count(**filters),
        "limit": limit,
        "offset": offset,
    }


@router.get("/benutzer")
def list_protokoll_benutzer(user: CurrentUser, db: DB) -> list[str]:
    """Distinct-Liste der im Protokoll vorkommenden Benutzer (für den Filter)."""
    _require_read(user)
    return db.access_log_repository.distinct_usernames()
