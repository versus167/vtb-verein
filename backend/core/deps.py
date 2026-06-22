from typing import Annotated, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from .security import decode_token
from .config import settings
from .db import get_db
from app.models.user import User
from app.db.datastore import VereinsDB

# auto_error=False: der Bearer-Header ist nur noch optionaler Fallback (Übergang).
# Hauptquelle des Tokens ist das HttpOnly-Cookie (Ticket #48). Fehlt das Token
# überall, werfen unsere Dependencies selbst die 401.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _token_from_request(request: Request, header_token: Optional[str]) -> Optional[str]:
    """Session-Token bevorzugt aus dem HttpOnly-Cookie, sonst aus dem Bearer-Header.

    Der Header-Fallback ist nur für den Übergang (offene Sessions mit altem
    Frontend) – Zielzustand ist Cookie-only.
    """
    return request.cookies.get(settings.COOKIE_NAME) or header_token


def get_current_user(
    request: Request,
    token: Annotated[Optional[str], Depends(oauth2_scheme)],
    db: Annotated[VereinsDB, Depends(get_db)],
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültige Anmeldedaten",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _token_from_request(request, token)
    if token is None:
        raise exc
    payload = decode_token(token)
    if payload is None:
        raise exc
    user_id = payload.get("sub")
    if user_id is None:
        raise exc
    # Serverseitige Session (Ticket #24): Token mit sid muss eine aktive Session
    # haben – wurde das Gerät abgemeldet, ist die Session widerrufen → 401.
    # Bestandstoken ohne sid werden geduldet (kein Datensatz, kein Geräte-Eintrag).
    sid = payload.get("sid")
    if sid is not None:
        if db.user_session_repository.get_active_session(sid) is None:
            raise exc
    user = db.get_user_by_id(int(user_id))
    if user is None or not user.active:
        raise exc
    # "Zuletzt aktiv" tracken: jeder authentifizierte Request markiert Aktivität
    # (im Repository auf 1×/Minute gedrosselt). Best-effort – darf Auth nie brechen.
    try:
        db.update_last_seen(user.id)
        if sid is not None:
            db.user_session_repository.touch_session(sid)
    except Exception:
        pass
    # Effektive Permissions (Sockel ∪ Funktionsrechte ∪ Grants − Denies) sind
    # bereits frisch geladen: get_user_by_id → UserRepository._load_permissions.
    # Änderungen an Matrix/Funktionen wirken damit ab dem nächsten Request.
    return user


def get_current_session_id(
    request: Request,
    token: Annotated[Optional[str], Depends(oauth2_scheme)],
) -> Optional[str]:
    """sid des aktuellen Tokens (oder None bei Legacy-Token ohne Session)."""
    token = _token_from_request(request, token)
    if token is None:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return payload.get("sid")


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSessionId = Annotated[Optional[str], Depends(get_current_session_id)]
DB = Annotated[VereinsDB, Depends(get_db)]
