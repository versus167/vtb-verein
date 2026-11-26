"""Anmeldung per Passkey (Fingerabdruck/Face ID über WebAuthn).

Ein vierter Login-Weg neben Passwort, Login-Link und Login-Code. Er endet in
derselben Session-Anlage (`auth._login_session`), Geräteliste, „Angemeldet bleiben"
und Abmelden funktionieren also unverändert.

Biometrie verlässt das Handy nie: Das Gerät prüft Finger/Gesicht (oder die
Geräte-PIN – unterscheiden lässt sich das nicht) und signiert damit eine Challenge
des Servers. Hier liegt nur der öffentliche Schlüssel.

Challenges: signiert (HMAC über SECRET_KEY) und mit Ablaufzeit, ausgegeben OHNE
DB-Schreibzugriff – der Login-Aufruf ist anonym und soll niemandem erlauben, die
Datenbank zu füllen. Beim Einlösen wird der Hash in `webauthn_challenge` vermerkt;
der Unique-Index macht jede Challenge genau einmal brauchbar.

Registrieren geht nur kurz nach einer echten Anmeldung (REGISTRIERUNG_FENSTER_MIN):
Wer bloß eine fremde, offene Sitzung erwischt, soll sich darüber keinen eigenen
Dauerzugang einrichten können. Zusätzlich bekommt das Mitglied eine Mail.
"""
import hashlib
import hmac
import html
import json
import logging
import secrets
import struct
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialHint,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.services.email_service import EmailService, verbindung_oeffnen
from ..core.client_ip import client_ip as _client_ip
from ..core.config import settings
from ..core.db import get_db
from ..core.deps import DB, CurrentSessionId, CurrentUser
from .auth import SessionUser, _klarname, _log_access, _login_session, _smtp_configured, _ts_iso

logger = logging.getLogger("app.passkeys")

router = APIRouter(prefix="/auth/passkey", tags=["auth"])

CHALLENGE_MINUTEN = 5          # Gültigkeit einer Challenge (Browser-Timeout ist 60 s)
REGISTRIERUNG_FENSTER_MIN = 10  # Einrichten nur so lange nach der Anmeldung
FEHLER_IP_WINDOW_MIN = 15       # Zeitfenster für das Pro-IP-Limit beim Login
FEHLER_MAX_PER_IP = 10          # max. Fehlversuche je IP im Fenster → danach 429


# ---------------------------------------------------------------------------
# Signierte Challenges
# ---------------------------------------------------------------------------
# Aufbau: 16 Byte Zufall | 8 Byte Ablauf (Unix-Sekunden) | 32 Byte HMAC-SHA256.
# Der HMAC deckt Zweck und Konto mit ab: Eine Login-Challenge taugt nicht zum
# Registrieren, und eine Registrier-Challenge nur für das Konto, das sie bekam.

def _challenge_schluessel() -> bytes:
    # Eigener Schlüssel abgeleitet aus SECRET_KEY, damit eine Challenge nie als
    # irgendeine andere Signatur der App durchgeht.
    return hmac.new(settings.SECRET_KEY.encode(), b"vtb-webauthn-challenge", hashlib.sha256).digest()


def _challenge_mac(zweck: str, user_id: int | None, kern: bytes) -> bytes:
    nachricht = f"{zweck}|{user_id or ''}|".encode() + kern
    return hmac.new(_challenge_schluessel(), nachricht, hashlib.sha256).digest()


def neue_challenge(zweck: str, user_id: int | None = None) -> bytes:
    ablauf = int((datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_MINUTEN)).timestamp())
    kern = secrets.token_bytes(16) + struct.pack(">Q", ablauf)
    return kern + _challenge_mac(zweck, user_id, kern)


def challenge_einloesen(db, challenge: bytes, zweck: str, user_id: int | None = None) -> bool:
    """Echt, unabgelaufen, für diesen Zweck/dieses Konto – und noch nie eingelöst."""
    if len(challenge) != 56:
        return False
    kern, mac = challenge[:24], challenge[24:]
    if not hmac.compare_digest(mac, _challenge_mac(zweck, user_id, kern)):
        return False
    ablauf = datetime.fromtimestamp(struct.unpack(">Q", kern[16:])[0], timezone.utc)
    if ablauf <= datetime.now(timezone.utc):
        return False
    return db.webauthn.challenge_verbrauchen(challenge, zweck, user_id, ablauf)


def _challenge_aus_antwort(credential: dict) -> bytes:
    """Die Challenge steht im vom Gerät signierten clientDataJSON – ein Cookie oder
    sonstiger Sitzungszustand ist zum Zuordnen deshalb nicht nötig."""
    try:
        client_data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        return base64url_to_bytes(client_data["challenge"])
    except Exception:
        return b""


def _options_json(options) -> dict:
    return json.loads(options_to_json(options))


# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------

class PasskeyInfo(BaseModel):
    id: int
    name: str
    created_at: str | None = None
    last_used_at: str | None = None
    # Im Schlüsselbund synchronisiert (iCloud/Google) – dann auch auf den anderen
    # Geräten desselben Kontos nutzbar.
    synchronisiert: bool = False


class RegistrierenAntwort(BaseModel):
    credential: dict
    name: str | None = Field(default=None, max_length=60)


class AnmeldenAntwort(BaseModel):
    credential: dict
    remember: bool = True


class Umbenennen(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


def _info(row) -> PasskeyInfo:
    return PasskeyInfo(
        id=row["id"],
        name=row["geraet_label"] or "Passkey",
        created_at=_ts_iso(row["created_at"]),
        last_used_at=_ts_iso(row["last_used_at"]),
        synchronisiert=bool(row["backed_up"]),
    )


# ---------------------------------------------------------------------------
# Verwalten (angemeldet)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PasskeyInfo])
def meine_passkeys(user: CurrentUser, db: DB):
    return [_info(r) for r in db.webauthn.list_active_for_user(user.id)]


def _als_datetime(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _pruefe_frische_anmeldung(db, sid: str | None) -> None:
    sitzung = db.user_session_repository.get_active_session(sid) if sid else None
    beginn = _als_datetime(sitzung["created_at"]) if sitzung else None
    if beginn is None or beginn < datetime.now(timezone.utc) - timedelta(minutes=REGISTRIERUNG_FENSTER_MIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "neu_anmelden",
                "message": "Zum Einrichten bitte einmal ab- und neu anmelden "
                           f"(höchstens {REGISTRIERUNG_FENSTER_MIN} Minuten her).",
            },
        )


@router.post("/register/options")
def registrieren_optionen(user: CurrentUser, sid: CurrentSessionId, db: DB):
    _pruefe_frische_anmeldung(db, sid)
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        # Opaker Konto-Bezug im Passkey; landet beim Login als userHandle zurück.
        user_id=str(user.id).encode(),
        user_name=user.username,
        user_display_name=_klarname(db, user),
        challenge=neue_challenge("register", user.id),
        timeout=60000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Der eingebaute Sensor des Geräts – kein externer Sicherheitsschlüssel.
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
            for cid in db.webauthn.credential_ids_for_user(user.id)
        ],
        hints=[PublicKeyCredentialHint.CLIENT_DEVICE],
    )
    return _options_json(options)


def _einrichten_fehlgeschlagen(db, request: Request, user, grund: str) -> None:
    """Fehlschläge beim Einrichten ins Zugriffsprotokoll – sonst sähe sie nur das
    Server-Log, und das Mitglied bliebe mit „hat nicht geklappt" allein."""
    _log_access(db, request, "passkey_register_failed", user_id=user.id,
                username=user.username, detail=grund[:300])


@router.post("/register/verify", response_model=PasskeyInfo)
def registrieren(data: RegistrierenAntwort, request: Request, background: BackgroundTasks,
                 user: CurrentUser, db: DB):
    challenge = _challenge_aus_antwort(data.credential)
    if not challenge_einloesen(db, challenge, "register", user.id):
        _einrichten_fehlgeschlagen(db, request, user, "server: challenge")
        raise HTTPException(status_code=400, detail="Die Einrichtung ist abgelaufen – bitte noch einmal.")
    try:
        ergebnis = verify_registration_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGINS,
            require_user_verification=True,
        )
    except Exception as exc:  # WebAuthnException, aber auch Parse-Fehler aus Fremdformaten
        logger.info("Passkey-Registrierung abgelehnt (user %s): %r", user.id, exc)
        _einrichten_fehlgeschlagen(db, request, user, f"server: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=400, detail="Passkey konnte nicht geprüft werden.")

    transports = data.credential.get("response", {}).get("transports") or []
    row = db.webauthn.anlegen(
        user_id=user.id,
        credential_id=bytes_to_base64url(ergebnis.credential_id),
        public_key=ergebnis.credential_public_key,
        sign_count=ergebnis.sign_count,
        transports=[str(t) for t in transports if isinstance(t, str)],
        aaguid=ergebnis.aaguid,
        backed_up=ergebnis.credential_backed_up,
        user_agent=request.headers.get("user-agent"),
    )
    name = (data.name or "").strip()
    if name and db.webauthn.umbenennen(row["id"], user.id, name):
        row["geraet_label"] = name
    _log_access(db, request, "passkey_registered", user_id=user.id, username=user.username,
                detail=row["geraet_label"])
    fresh = db.get_user_by_id(user.id)
    if fresh and (fresh.email or "").strip() and _smtp_configured():
        background.add_task(_hinweis_mail, fresh.email, fresh.username, row["geraet_label"])
    return _info(row)


class ClientFehler(BaseModel):
    """Was der Browser beim Einrichten gemeldet hat. Diese Fehler entstehen im Handy
    und erreichen den Server sonst nie."""
    name: str | None = Field(default=None, max_length=80)
    code: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)


@router.post("/register/fehler")
def einrichten_fehler_melden(data: ClientFehler, request: Request, user: CurrentUser, db: DB):
    teile = [t for t in (data.name, data.code) if t]
    grund = f"geraet: {' / '.join(teile) or 'unbekannt'}"
    if data.message:
        grund += f": {data.message}"
    _einrichten_fehlgeschlagen(db, request, user, grund)
    return {"ok": True}


@router.patch("/{passkey_id}", response_model=PasskeyInfo)
def umbenennen(passkey_id: int, data: Umbenennen, user: CurrentUser, db: DB):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen angeben.")
    if not db.webauthn.umbenennen(passkey_id, user.id, name):
        raise HTTPException(status_code=404, detail="Passkey nicht gefunden")
    row = next(r for r in db.webauthn.list_active_for_user(user.id) if r["id"] == passkey_id)
    return _info(row)


@router.delete("/{passkey_id}")
def entfernen(passkey_id: int, request: Request, user: CurrentUser, db: DB):
    if not db.webauthn.widerrufen(passkey_id, user.id, revoked_by=user.username):
        raise HTTPException(status_code=404, detail="Passkey nicht gefunden")
    _log_access(db, request, "passkey_revoked", user_id=user.id, username=user.username,
                detail=str(passkey_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Anmelden (anonym)
# ---------------------------------------------------------------------------

@router.post("/login/options")
def anmelden_optionen():
    """Ohne Kennung: Das Handy zeigt selbst an, welche Passkeys es für die Domain
    hat. Schreibt nichts in die DB (s. Moduldoku)."""
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        challenge=neue_challenge("login"),
        timeout=60000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return _options_json(options)


@router.post("/login/verify", response_model=SessionUser)
def anmelden(data: AnmeldenAntwort, request: Request, response: Response, db=Depends(get_db)):
    ip = _client_ip(request)
    if ip and db.access_log_repository.count(
        event_type="passkey_failed",
        ip=ip,
        since=(datetime.now(timezone.utc) - timedelta(minutes=FEHLER_IP_WINDOW_MIN)).isoformat(),
    ) >= FEHLER_MAX_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Versuche. Bitte versuche es später erneut – oder melde dich "
                   "mit einem Login-Link an.",
        )

    def fehler(grund: str, cred=None, user=None, meldung="Anmeldung mit Passkey fehlgeschlagen."):
        _log_access(db, request, "passkey_failed",
                    user_id=(user.id if user else cred["user_id"] if cred else None),
                    username=user.username if user else None, detail=grund)
        return HTTPException(status_code=401, detail=meldung)

    credential_id = data.credential.get("id") if isinstance(data.credential.get("id"), str) else None
    cred = db.webauthn.aktiv_nach_credential_id(credential_id) if credential_id else None
    if cred is None:
        # Typisch: Passkey im Profil entfernt, im Handy aber noch gespeichert.
        raise fehler("unbekannt", meldung="Dieser Passkey ist hier nicht (mehr) eingerichtet. "
                                          "Bitte mit Login-Link anmelden und das Handy neu einrichten.")

    challenge = _challenge_aus_antwort(data.credential)
    if not challenge_einloesen(db, challenge, "login"):
        raise fehler("challenge", cred)

    user_handle = data.credential.get("response", {}).get("userHandle")
    if user_handle:
        try:
            passt = base64url_to_bytes(user_handle) == str(cred["user_id"]).encode()
        except Exception:
            passt = False
        if not passt:
            raise fehler("user_handle", cred)

    try:
        ergebnis = verify_authentication_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGINS,
            credential_public_key=bytes(cred["public_key"]),
            credential_current_sign_count=cred["sign_count"],
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        logger.info("Passkey-Login abgelehnt (credential %s): %s", cred["id"], exc)
        raise fehler(f"pruefung: {exc}"[:200], cred)

    user = db.get_user_by_id(cred["user_id"])
    if not user or not user.active:
        raise fehler("user_inactive_or_missing", cred)

    db.webauthn.nach_login(cred["id"], ergebnis.new_sign_count, ergebnis.credential_backed_up)
    _log_access(db, request, "passkey_login", user_id=user.id, username=user.username,
                detail=cred["geraet_label"])
    return _login_session(db, request, response, user, data.remember)


# ---------------------------------------------------------------------------
# Hinweis-Mail
# ---------------------------------------------------------------------------

def _hinweis_mail(recipient: str, username: str, geraet: str | None) -> None:
    """Best effort im Hintergrund – ein Mailfehler darf die Einrichtung nicht kippen."""
    try:
        base_url = settings.BASE_URL.rstrip("/")
        profil_url = f"{base_url}/profile"
        kurz = settings.VEREIN_KURZ
        geraet = geraet or "ein Gerät"
        text = (
            f"Hallo {username},\n\n"
            f"für dein Konto wurde gerade ein Passkey eingerichtet ({geraet}). Damit kannst "
            "du dich auf diesem Gerät per Fingerabdruck oder Gesichtserkennung anmelden.\n\n"
            "Warst du das nicht? Dann entferne den Passkey sofort in deinem Profil unter "
            "„Anmeldung per Fingerabdruck“, melde dort alle anderen Geräte ab und sag dem "
            f"Vorstand Bescheid:\n{profil_url}\n\n"
            f"Viele Grüße,\n{kurz} Vereinsverwaltung"
        )
        html_body = EmailService.render_vtb_email(
            headline="Neuer Passkey eingerichtet",
            username=username,
            intro_html=(
                f"für dein Konto wurde gerade ein Passkey eingerichtet (<strong>{html.escape(geraet)}</strong>). "
                "Damit kannst du dich auf diesem Gerät per Fingerabdruck oder "
                "Gesichtserkennung anmelden."
            ),
            button_label="Mein Profil öffnen",
            button_url=profil_url,
            hints=[
                "Warst du das nicht? Dann entferne den Passkey sofort in deinem Profil unter "
                "<strong>„Anmeldung per Fingerabdruck“</strong>, melde dort alle anderen "
                "Geräte ab und sag dem Vorstand Bescheid.",
                "Warst du es selbst, musst du nichts weiter tun.",
            ],
            preheader=f"Für dein Konto bei der {kurz} Vereinsverwaltung wurde ein Passkey eingerichtet.",
        )
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Neuer Passkey für {kurz} Vereinsverwaltung"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = recipient
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        srv = verbindung_oeffnen()
        try:
            srv.sendmail(settings.MAIL_FROM, recipient, msg.as_string())
        finally:
            srv.quit()
    except Exception:
        logger.exception("Hinweis-Mail zum neuen Passkey konnte nicht versendet werden")

