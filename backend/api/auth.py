import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from app.services.user_service import UserService
from ..core.db import get_db, get_db as _get_db
from ..core.security import create_access_token
from ..core.deps import CurrentUser, CurrentSessionId, DB
from ..core.config import settings


def _client_ip(request: Request) -> str | None:
    """Client-IP – berücksichtigt X-Forwarded-For hinter dem Reverse-Proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _log_access(db, request: Request, event_type: str, **kwargs) -> None:
    """Schreibt einen Auth-Eintrag ins Zugriffsprotokoll – best-effort.

    Darf den Auth-Pfad niemals brechen (vgl. last_seen-Tracking in deps.py), daher
    vollständig in try/except gekapselt. IP/User-Agent werden aus dem Request abgeleitet.
    """
    try:
        db.access_log_repository.log(
            event_type,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            **kwargs,
        )
    except Exception:
        pass


def _classify_login_failure(db, username: str) -> str:
    """Klassifiziert einen fehlgeschlagenen Login für das Protokoll (nicht für den Client).

    'unknown_user' | 'inactive' | 'bad_password' – best-effort, fällt auf 'bad_password'
    zurück. Die 401-Meldung an den Client bleibt davon unberührt generisch.
    """
    try:
        user = db.users.get_by_username(username.lower().strip())
        if user is None:
            return "unknown_user"
        if not user.active:
            return "inactive"
    except Exception:
        pass
    return "bad_password"

router = APIRouter(prefix="/auth", tags=["auth"])


class SessionUser(BaseModel):
    """Login-Antwort (Ticket #48): das JWT geht ins HttpOnly-Cookie, NICHT mehr in
    den Body. Hier stehen nur noch die unkritischen User-Infos fürs UI-Gating –
    durchgesetzt wird die Berechtigung ohnehin serverseitig je Request."""
    id: int
    username: str
    role: str
    permissions: list[str]


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    """Setzt das Session-JWT als HttpOnly-Cookie (für JS unlesbar)."""
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    """Löscht das Session-Cookie (Logout) – Attribute müssen zum Setzen passen."""
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


class UserInfo(BaseModel):
    id: int
    username: str
    email: str
    role: str
    permissions: list[str]
    last_login: str | None = None
    last_seen: str | None = None
    version: int = 1
    matrix_id: str | None = None
    preferred_contact: str = 'email'


@router.post("/login", response_model=SessionUser)
def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    remember_me: bool = False,
    db=Depends(get_db),
):
    service = UserService(db)
    user = service.authenticate(form_data.username, form_data.password)
    if user is None:
        _log_access(
            db, request, "login_failed",
            username=form_data.username,
            detail=_classify_login_failure(db, form_data.username),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falscher Benutzername oder Passwort",
        )
    _log_access(db, request, "login_success", user_id=user.id, username=user.username)
    expire = timedelta(days=30) if remember_me else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    sid = db.user_session_repository.create_session(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + expire,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    token = create_access_token(user.id, expires_delta=expire, session_id=sid)
    db.update_last_login(user.id)
    _set_session_cookie(response, token, max_age=int(expire.total_seconds()))
    return SessionUser(
        id=user.id,
        username=user.username,
        role=user.role,
        permissions=list(user.permissions),
    )


class OwnPasswordChange(BaseModel):
    new_password: str


@router.get("/me", response_model=UserInfo)
def get_me(user: CurrentUser, db: DB):
    # Hinweis: kein last_login-Bump hier – das ist ein echter Login (Passwort/Magic-Link).
    # Die Aktivität ("zuletzt aktiv") wird über last_seen im Auth-Dependency getrackt.
    fresh = db.get_user_by_id(user.id)
    return UserInfo(
        id=fresh.id,
        username=fresh.username,
        email=fresh.email,
        role=fresh.role,
        permissions=list(fresh.permissions),
        last_login=fresh.last_login,
        last_seen=fresh.last_seen,
        version=fresh.version,
        matrix_id=fresh.matrix_id,
        preferred_contact=fresh.preferred_contact,
    )


@router.get("/me/permissions")
def get_my_permissions(user: CurrentUser, db: DB):
    """Eigene effektive Rechte inkl. Herkunft – read-only, ohne personen.read.

    Jeder eingeloggte User darf seine eigenen Berechtigungen einsehen.
    Liefert dieselbe Struktur wie /users/{id}/permissions plus die statischen
    Berechtigungsgruppen, damit das Profil sie ohne Zusatz-Endpoint rendern kann.
    """
    from .users import _permissions_payload, permission_groups_payload
    fresh = db.get_user_by_id(user.id)
    return {
        **_permissions_payload(fresh, db),
        'groups': permission_groups_payload(),
    }


class ContactPreferencesUpdate(BaseModel):
    matrix_id: str | None = None
    preferred_contact: str
    expected_version: int


@router.patch("/me/contact")
def update_contact_preferences(data: ContactPreferencesUpdate, user: CurrentUser, db: DB):
    service = UserService(db)
    try:
        service.update_contact_preferences(
            user_id=user.id,
            matrix_id=data.matrix_id or None,
            preferred_contact=data.preferred_contact,
            updated_by=user.username,
            expected_version=data.expected_version,
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/me/contact/test")
def send_test_notification(user: CurrentUser, db: DB):
    from app.services.notification_service import NotificationService
    fresh = db.get_user_by_id(user.id)
    result = NotificationService.send_notification(
        fresh,
        title="Test-Nachricht",
        message="Dies ist eine Test-Benachrichtigung von der VTB-Vereinsverwaltung.",
    )
    if not result:
        raise HTTPException(status_code=500, detail="Nachricht konnte nicht versendet werden")
    return {"ok": True}


@router.post("/me/password")
def change_own_password(data: OwnPasswordChange, user: CurrentUser, db: DB):
    service = UserService(db)
    try:
        service.change_password(user.id, data.new_password, updated_by=user.username)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Angemeldete Geräte / Sessions (Ticket #24)
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    id: int
    device_label: str | None = None
    user_agent: str | None = None
    ip: str | None = None
    created_at: str | None = None
    last_seen_at: str | None = None
    expires_at: str | None = None
    current: bool = False


@router.get("/me/sessions", response_model=list[SessionInfo])
def list_my_sessions(user: CurrentUser, sid: CurrentSessionId, db: DB):
    """Eigene aktive Sessions/Geräte – das aktuelle Gerät ist markiert."""
    return [
        SessionInfo(
            id=row["id"],
            device_label=row["device_label"],
            user_agent=row["user_agent"],
            ip=row["ip"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            expires_at=row["expires_at"],
            current=(sid is not None and row["sid"] == sid),
        )
        for row in db.user_session_repository.list_active_for_user(user.id)
    ]


@router.post("/logout")
def logout_current(request: Request, response: Response, user: CurrentUser, sid: CurrentSessionId, db: DB):
    """Normaler Logout: widerruft die aktuelle Server-Session (best effort),
    damit sie nicht als „Geist-Gerät" in der Liste verbleibt, und löscht das
    Session-Cookie im Browser."""
    if sid is not None:
        db.user_session_repository.revoke_by_sid(sid, revoked_by=user.username)
    _clear_session_cookie(response)
    _log_access(db, request, "logout", user_id=user.id, username=user.username)
    return {"ok": True}


@router.post("/me/sessions/revoke-others")
def revoke_other_sessions(user: CurrentUser, sid: CurrentSessionId, db: DB):
    """Alle anderen Geräte abmelden ("en bloc") – das aktuelle bleibt angemeldet."""
    revoked = db.user_session_repository.revoke_others(
        user.id, keep_sid=sid, revoked_by=user.username
    )
    return {"ok": True, "revoked": revoked}


@router.delete("/me/sessions/{session_id}")
def revoke_my_session(session_id: int, user: CurrentUser, db: DB):
    """Ein einzelnes Gerät abmelden. Nur eigene Sessions sind widerrufbar."""
    if not db.user_session_repository.revoke_session(
        session_id, user.id, revoked_by=user.username
    ):
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Magic-Link
# ---------------------------------------------------------------------------

class MagicLinkRequest(BaseModel):
    email: str


class MagicLinkValidate(BaseModel):
    token: str
    remember: bool = False


# Rate-Limiting für Magic-Link-Anforderungen (Ticket #48) – gegen Mail-Bombing
# und Brute-Force/Enumeration. Gezählt wird über das Zugriffsprotokoll (access_log),
# das ohnehin jeden 'magic_link_request' festhält – kein Extra-State, übersteht Neustarts.
MAGIC_LINK_IP_WINDOW_MIN = 15      # Zeitfenster für das Pro-IP-Limit
MAGIC_LINK_MAX_PER_IP = 5          # max. Anfragen je IP im Fenster → danach 429
MAGIC_LINK_USER_WINDOW_MIN = 60    # Zeitfenster für das Pro-Empfänger-Limit
MAGIC_LINK_MAX_PER_USER = 3        # max. Mails an dieselbe Adresse im Fenster


def _smtp_configured() -> bool:
    return bool(settings.SMTP_USERNAME and settings.SMTP_PASSWORD)


def _send_magic_link_email(recipient: str, username: str, token: str) -> None:
    magic_url = f"{settings.BASE_URL}/auth/magic-link?token={token}"
    subject = "Login-Link für VTB Vereinsverwaltung"

    text = (
        f"Hallo {username},\n\n"
        f"hier ist dein Login-Link:\n\n{magic_url}\n\n"
        "Der Link ist 7 Tage gültig und kann nur einmal verwendet werden.\n\n"
        "Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.\n\n"
        "Viele Grüße,\nVTB Vereinsverwaltung"
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;line-height:1.6;color:#333">
<div style="max-width:600px;margin:0 auto;padding:20px">
<h2 style="color:#2c3e50">Login-Link für VTB Vereinsverwaltung</h2>
<p>Hallo <strong>{username}</strong>,</p>
<p>hier ist dein Login-Link für die Vereinsverwaltung:</p>
<div style="margin:30px 0">
<a href="{magic_url}"
   style="display:inline-block;padding:12px 24px;background-color:#3498db;
          color:white;text-decoration:none;border-radius:4px;font-weight:bold">
Jetzt einloggen
</a>
</div>
<p style="color:#7f8c8d;font-size:14px">
Der Link ist <strong>7 Tage gültig</strong> und kann nur einmal verwendet werden.
</p>
<p style="color:#7f8c8d;font-size:14px">
Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.
</p>
<hr style="border:none;border-top:1px solid #ecf0f1;margin:30px 0">
<p style="color:#95a5a6;font-size:12px">Viele Grüße,<br>VTB Vereinsverwaltung</p>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.MAIL_FROM
    msg["To"] = recipient
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as srv:
        if settings.SMTP_USE_TLS:
            srv.starttls()
        srv.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        srv.sendmail(settings.MAIL_FROM, recipient, msg.as_string())


@router.post("/magic-link/request")
def request_magic_link(data: MagicLinkRequest, request: Request, db=Depends(get_db)):
    """Sendet einen Magic-Link an die angegebene E-Mail-Adresse.

    Gibt immer 200 zurück, um keine Informationen über vorhandene Adressen preiszugeben.
    """
    if not _smtp_configured():
        raise HTTPException(status_code=503, detail="E-Mail-Versand nicht konfiguriert")

    ip = _client_ip(request)
    now = datetime.now(timezone.utc)

    # Pro-IP-Gate zuerst: rein volumenbasiert und ohne User-Bezug, daher verrät die
    # 429-Antwort nichts über vorhandene Adressen. Bremst Mail-Bombing/Enumeration
    # von einer Quelle aus.
    if ip and db.access_log_repository.count(
        event_type="magic_link_request",
        ip=ip,
        since=(now - timedelta(minutes=MAGIC_LINK_IP_WINDOW_MIN)).isoformat(),
    ) >= MAGIC_LINK_MAX_PER_IP:
        _log_access(db, request, "magic_link_rate_limited", detail="ip")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Anfragen. Bitte versuche es später erneut.",
        )

    user = db.get_user_by_email(data.email)
    # Protokoll: ob eine passende (aktive) Adresse existierte, nur im detail-Feld –
    # nach außen bleibt die Antwort einheitlich 200 (kein User-Enumeration-Leak).
    _log_access(
        db, request, "magic_link_request",
        user_id=user.id if user else None,
        username=user.username if user else None,
        detail="match" if (user and user.active) else "no_match",
    )
    should_send = bool(user and user.active)

    # Pro-Empfänger-Limit: schützt das Postfach eines echten Nutzers auch dann,
    # wenn der Angreifer die IP wechselt. Bei Überschreitung wird *still* nicht
    # versendet (Antwort bleibt 200) – kein Enumeration-Oracle. Der gerade
    # protokollierte Request ist mitgezählt, daher '>' statt '>='.
    if should_send and db.access_log_repository.count(
        event_type="magic_link_request",
        user_id=user.id,
        since=(now - timedelta(minutes=MAGIC_LINK_USER_WINDOW_MIN)).isoformat(),
    ) > MAGIC_LINK_MAX_PER_USER:
        _log_access(
            db, request, "magic_link_rate_limited",
            user_id=user.id, username=user.username, detail="user",
        )
        should_send = False

    if should_send:
        token = db.auth_token_repository.create_token(
            user_id=user.id,
            token_type="magic_link",
            expires_days=7,
        )
        try:
            _send_magic_link_email(data.email, user.username, token)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"E-Mail-Versand fehlgeschlagen: {exc}")

    return {"ok": True}


@router.post("/magic-link/validate", response_model=SessionUser)
def validate_magic_link(data: MagicLinkValidate, request: Request, response: Response, db=Depends(get_db)):
    result = db.auth_token_repository.validate_and_use_token(data.token)
    if not result or result.get("token_type") != "magic_link":
        _log_access(db, request, "magic_link_failed", detail="invalid_or_used")
        raise HTTPException(status_code=401, detail="Link ungültig oder bereits verwendet")

    user = db.get_user_by_id(result["user_id"])
    if not user or not user.active:
        _log_access(
            db, request, "magic_link_failed",
            user_id=result.get("user_id"),
            detail="user_inactive_or_missing",
        )
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden oder inaktiv")

    _log_access(db, request, "magic_link_login", user_id=user.id, username=user.username)
    db.update_last_login(user.id)
    expire = timedelta(days=30) if data.remember else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    sid = db.user_session_repository.create_session(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + expire,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    token = create_access_token(user.id, expires_delta=expire, session_id=sid)
    _set_session_cookie(response, token, max_age=int(expire.total_seconds()))
    return SessionUser(
        id=user.id,
        username=user.username,
        role=user.role,
        permissions=list(user.permissions),
    )
