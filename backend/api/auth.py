import smtplib
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from app.services.user_service import UserService
from ..core.db import get_db, get_db as _get_db
from ..core.security import create_access_token
from ..core.deps import CurrentUser, DB
from ..core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    permissions: list[str]


class UserInfo(BaseModel):
    id: int
    username: str
    email: str
    role: str
    permissions: list[str]
    last_login: str | None = None


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    remember_me: bool = False,
    db=Depends(get_db),
):
    service = UserService(db)
    user = service.authenticate(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falscher Benutzername oder Passwort",
        )
    expire = timedelta(days=30) if remember_me else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(user.id, expires_delta=expire)
    return Token(
        access_token=token,
        username=user.username,
        role=user.role,
        permissions=list(user.permissions),
    )


class OwnPasswordChange(BaseModel):
    new_password: str


@router.get("/me", response_model=UserInfo)
def get_me(user: CurrentUser, db: DB):
    # Frisch laden damit last_login etc. aktuell ist
    fresh = db.get_user_by_id(user.id)
    return UserInfo(
        id=fresh.id,
        username=fresh.username,
        email=fresh.email,
        role=fresh.role,
        permissions=list(fresh.permissions),
        last_login=fresh.last_login,
    )


@router.post("/me/password")
def change_own_password(data: OwnPasswordChange, user: CurrentUser, db: DB):
    service = UserService(db)
    try:
        service.change_password(user.id, data.new_password, updated_by=user.username)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Magic-Link
# ---------------------------------------------------------------------------

class MagicLinkRequest(BaseModel):
    email: str


class MagicLinkValidate(BaseModel):
    token: str


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
def request_magic_link(data: MagicLinkRequest, db=Depends(get_db)):
    """Sendet einen Magic-Link an die angegebene E-Mail-Adresse.

    Gibt immer 200 zurück, um keine Informationen über vorhandene Adressen preiszugeben.
    """
    if not _smtp_configured():
        raise HTTPException(status_code=503, detail="E-Mail-Versand nicht konfiguriert")

    user = db.get_user_by_email(data.email)
    if user and user.active:
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


@router.post("/magic-link/validate", response_model=Token)
def validate_magic_link(data: MagicLinkValidate, db=Depends(get_db)):
    result = db.auth_token_repository.validate_and_use_token(data.token)
    if not result or result.get("token_type") != "magic_link":
        raise HTTPException(status_code=401, detail="Link ungültig oder bereits verwendet")

    user = db.get_user_by_id(result["user_id"])
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden oder inaktiv")

    db.update_last_login(user.id)
    token = create_access_token(
        user.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(
        access_token=token,
        username=user.username,
        role=user.role,
        permissions=list(user.permissions),
    )
