from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from .security import REMEMBER_ME_LIFETIME, create_access_token, decode_token
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
    session = None
    if sid is not None:
        session = db.user_session_repository.get_active_session(sid)
        if session is None:
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
            _verlaengere_bei_nutzung(request, db, payload, session)
    except Exception:
        pass
    # Effektive Permissions (Sockel ∪ Funktionsrechte ∪ Grants − Denies) sind
    # bereits frisch geladen: get_user_by_id → UserRepository._load_permissions.
    # Änderungen an Matrix/Funktionen wirken damit ab dem nächsten Request.
    return user


def _bleibt_angemeldet(payload: dict, session: dict[str, Any]) -> bool:
    """War beim Login „Angemeldet bleiben" gesetzt?

    Neue Token tragen das als `rem`. Token von vor #211 nicht – deren Session
    wurde aber auch nie verlängert, `expires_at − created_at` ist also noch
    genau die Laufzeit vom Login und deutlich länger als die kurze Frist.
    """
    if "rem" in payload:
        return bool(payload["rem"])

    def _zeit(wert) -> datetime:
        z = wert if isinstance(wert, datetime) else datetime.fromisoformat(str(wert))
        return z if z.tzinfo else z.replace(tzinfo=timezone.utc)

    try:
        dauer = _zeit(session["expires_at"]) - _zeit(session["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return dauer > timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES) + timedelta(hours=1)


def _verlaengere_bei_nutzung(request: Request, db: VereinsDB, payload: dict,
                             session: dict[str, Any]) -> None:
    """Login-Verlängerung bei Nutzung (#211), gleitend und ohne Höchstdauer.

    Gilt nur für Sessions mit „Angemeldet bleiben"; ohne Haken bleibt es bei der
    festen kurzen Frist ab Login. Ist mehr als die Hälfte der Laufzeit
    verstrichen, bekommt die Session ein frisches Token mit derselben sid – wer
    die App nutzt, bleibt also angemeldet; nur Leerlauf über die volle Laufzeit
    meldet ab. Die Halbzeit-Schwelle hält das Neuausstellen selten.

    Das Cookie setzt nicht diese Dependency, sondern die Middleware in main.py
    aus `request.state.session_cookie`: Ein hier injiziertes `Response` erreicht
    Endpunkte nicht, die selbst eine Response liefern (Downloads, Streams).
    Gerät abmelden wirkt unverändert – die sid bleibt dieselbe.
    """
    if not _bleibt_angemeldet(payload, session):
        return
    laufzeit = REMEMBER_ME_LIFETIME
    jetzt = datetime.now(timezone.utc)
    restzeit = datetime.fromtimestamp(payload["exp"], timezone.utc) - jetzt
    if restzeit > laufzeit / 2:
        return
    sid = payload["sid"]
    if not db.user_session_repository.extend_session(sid, jetzt + laufzeit):
        return
    token = create_access_token(int(payload["sub"]), expires_delta=laufzeit,
                                session_id=sid, remember=True)
    request.state.session_cookie = (token, int(laufzeit.total_seconds()))


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
