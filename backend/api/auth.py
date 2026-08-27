import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import AliasChoices, BaseModel, Field
from app.services.user_service import UserService
from app.services.email_service import EmailService
from ..core.db import get_db, get_db as _get_db
from ..core.security import create_access_token
from ..core.deps import CurrentUser, CurrentSessionId, DB
from ..core.config import settings
from ..core.validation import mailadresse_or_422


def _client_ip(request: Request) -> str | None:
    """Client-IP – berücksichtigt X-Forwarded-For hinter dem Reverse-Proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _ts_iso(v):
    """Zeitstempel robust als ISO-String fürs JSON.

    Seit der TIMESTAMPTZ-Umstellung (Schema v51) liefern die migrierten Audit-Spalten
    (z.B. users.last_login/last_seen, user_sessions.created_at) datetime-Objekte,
    verbliebene TEXT-Spalten weiterhin Strings. Die str-typisierten Response-Modelle
    (UserInfo/SessionInfo) würden an einem datetime scheitern – hier vereinheitlicht.
    Das Frontend (formatDateTime) versteht beide ISO-Varianten."""
    return v.isoformat() if isinstance(v, datetime) else v


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


def _classify_login_failure(db, kennung: str) -> str:
    """Klassifiziert einen fehlgeschlagenen Login für das Protokoll (nicht für den Client).

    'unknown_user' | 'inactive' | 'bad_password' – best-effort, fällt auf 'bad_password'
    zurück. Die 401-Meldung an den Client bleibt davon unberührt generisch.

    Gesucht wird über die Kennung (Benutzername oder E-Mail), sonst stünde bei
    jeder Anmeldung per Adresse ein irreführendes 'unknown_user' im Protokoll.
    """
    try:
        user = db.users.get_by_kennung(kennung)
        if user is None:
            return "unknown_user"
        if not user.active:
            return "inactive"
    except Exception:
        pass
    return "bad_password"


def _zaehlschluessel(db, kennung: str) -> str:
    """Führt Benutzername und E-Mail auf *einen* Schlüssel für die Anmelde-Bremse
    zurück: den Benutzernamen des getroffenen Kontos.

    Seit man sich mit beidem anmelden darf, hätte ein Konto sonst zwei getrennte
    Zähler – ein Angreifer bekäme allein durch den Wechsel der Form die doppelte
    Zahl an Versuchen, und ein erfolgreicher Login (protokolliert wird immer der
    Benutzername) setzte die Zählung der anderen Form nicht zurück.

    Bewusst der schlanke Lookup ohne Permission-Fanout: Das läuft *vor* der Bremse,
    ein abgewiesener Versuch soll so wenig wie möglich kosten. Unbekannte Eingaben
    bleiben, wie sie sind – für erfundene Konten verhält sich die Bremse damit
    weiterhin genauso wie für vorhandene.
    """
    try:
        treffer = db.get_username_by_kennung(kennung)
    except Exception:
        treffer = None
    return treffer or kennung.strip()

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Anmelde-Bremse (Brute-Force-Schutz)
# ---------------------------------------------------------------------------
# Gezählt wird wie beim Magic-Link über das Zugriffsprotokoll, das jeden
# 'login_failed' ohnehin festhält – kein Extra-State, übersteht Neustarts.
#
# Zwei Dimensionen mit sehr unterschiedlichem Zuschnitt:
#
# * Pro Konto eng. Das ist der eigentliche Schutz – ein Angreifer, der EIN
#   Passwort raten will. bcrypt bremst zwar, aber gegen ein schwaches Passwort
#   reichen ein paar tausend Versuche, und die hat man in Stunden.
# * Pro IP weit. Ein Verein sitzt zu großen Teilen hinter derselben Adresse
#   (Vereinsheim-WLAN, Mobilfunk-NAT). Ein enges IP-Limit würde beim ersten
#   Trainingsabend die halbe Mannschaft aussperren. Die Grenze zielt deshalb
#   nur auf das maschinelle Durchprobieren vieler Konten von einer Quelle –
#   was Menschen dort erzeugen, liegt weit darunter.
#
# Wer ausgesperrt ist, kommt weiterhin über den Login-Link herein (eigenes,
# empfängerbezogenes Limit). Das nimmt der Sperre die Schärfe: Sie kann nicht
# dazu benutzt werden, jemanden dauerhaft auszuschließen.
LOGIN_FENSTER_MIN = 15        # Beobachtungsfenster für beide Grenzen
LOGIN_MAX_PRO_KONTO = 10      # Fehlversuche je Benutzername im Fenster
LOGIN_MAX_PRO_IP = 30         # Fehlversuche je Quell-IP im Fenster


def _pruefe_login_bremse(db, request: Request, username: str, ip: str | None) -> None:
    """429, wenn zu viele Fehlversuche im Fenster liegen – vor der Passwortprüfung.

    Die Reihenfolge ist Absicht: Erst gar keine bcrypt-Runde ausführen, sonst
    kostet jeder abgewiesene Versuch weiterhin Rechenzeit.

    `username` ist der Zählschlüssel aus `_zaehlschluessel`: der Benutzername des
    getroffenen Kontos, sonst die Eingabe unverändert. Auch nicht existierende
    Konten werden also gezählt – damit antwortet die Bremse für existierende und
    erfundene Konten gleich und verrät nicht, welche existieren.
    """
    jetzt = datetime.now(timezone.utc)
    fenster_start = (jetzt - timedelta(minutes=LOGIN_FENSTER_MIN)).isoformat()

    # Ein erfolgreicher Login setzt die Zählung zurück – sonst summieren sich
    # Vertipper über den Tag hinweg zu einer Sperre, obwohl zwischendurch alles
    # in Ordnung war.
    letzter_erfolg = db.access_log_repository.last_login_success_at(username)
    seit_konto = max(fenster_start, letzter_erfolg) if letzter_erfolg else fenster_start

    if db.access_log_repository.count_login_failures(
        since=seit_konto, username=username
    ) >= LOGIN_MAX_PRO_KONTO:
        _log_access(db, request, "login_rate_limited", username=username, detail="konto")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Fehlversuche. Bitte in einigen Minuten erneut versuchen "
                   "– oder melde dich mit einem Login-Link an.",
        )

    if ip and db.access_log_repository.count_login_failures(
        since=fenster_start, ip=ip
    ) >= LOGIN_MAX_PRO_IP:
        _log_access(db, request, "login_rate_limited", username=username, detail="ip")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Fehlversuche von dieser Verbindung. Bitte in einigen "
                   "Minuten erneut versuchen – oder melde dich mit einem Login-Link an.",
        )


class SessionUser(BaseModel):
    """Login-Antwort (Ticket #48): das JWT geht ins HttpOnly-Cookie, NICHT mehr in
    den Body. Hier stehen nur noch die unkritischen User-Infos fürs UI-Gating –
    durchgesetzt wird die Berechtigung ohnehin serverseitig je Request."""
    id: int
    username: str
    display_name: str
    role: str
    permissions: list[str]


def _klarname(db, user) -> str:
    """Anzeigename fürs UI (#105): „Vorname Nachname" des verknüpften Mitglieds,
    ohne Verknüpfung (oder ohne Namen) der Username."""
    m = db.get_mitglied_by_user_id(user.id)
    if m is not None and (m.vorname or m.nachname):
        return f"{m.vorname or ''} {m.nachname or ''}".strip()
    return user.username


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
    display_name: str
    # Kein Pflichtfeld mehr: Wer sich per Passwort anmeldet, muss keine Adresse haben
    # (und Konten ohne Zugang haben grundsätzlich keine).
    email: str | None = None
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
    # `form_data.username` ist die Kennung: Benutzername *oder* E-Mail-Adresse.
    # Beide sind eindeutig, also nimmt der Login beides an (das Feld heißt nur so,
    # weil OAuth2PasswordRequestForm es vorgibt).
    kennung = _zaehlschluessel(db, form_data.username)
    _pruefe_login_bremse(db, request, kennung, _client_ip(request))
    service = UserService(db)
    user = service.authenticate(form_data.username, form_data.password)
    if user is None:
        _log_access(
            db, request, "login_failed",
            username=kennung,
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
        display_name=_klarname(db, user),
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
        display_name=_klarname(db, fresh),
        email=fresh.email,
        role=fresh.role,
        permissions=list(fresh.permissions),
        last_login=_ts_iso(fresh.last_login),
        last_seen=_ts_iso(fresh.last_seen),
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
        push_service=db.push,
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
            created_at=_ts_iso(row["created_at"]),
            last_seen_at=_ts_iso(row["last_seen_at"]),
            expires_at=_ts_iso(row["expires_at"]),
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
    # Kennung = E-Mail-Adresse **oder** Benutzername: Beides ist eindeutig, also
    # nimmt auch der Login-Link beides an. Der alte Feldname `email` bleibt als
    # Alias gültig — eine noch nicht neu geladene App im Browser soll sich weiter
    # anmelden können.
    #
    # Obergrenze nach RFC 5321. Nicht der Form wegen — die Eingabe landet im
    # Zugriffsprotokoll, und das wird für Auth-Ereignisse dauerhaft aufbewahrt.
    # Ohne Grenze könnte man es mit beliebig langen Zeichenketten vollschreiben.
    kennung: str = Field(..., max_length=254,
                         validation_alias=AliasChoices('kennung', 'email'))


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
    base_url = settings.BASE_URL.rstrip("/")
    magic_url = f"{base_url}/auth/magic-link?token={token}"
    kurz = settings.VEREIN_KURZ
    subject = f"Login-Link für {kurz} Vereinsverwaltung"

    text = (
        f"Hallo {username},\n\n"
        f"hier ist dein Login-Link:\n\n{magic_url}\n\n"
        "Wichtig: Der Link ist 7 Tage gültig und funktioniert nur ein einziges Mal.\n"
        "Danach forderst du dir in der App einfach einen neuen Login-Link an.\n\n"
        f"Die App erreichst du jederzeit unter:\n{base_url}\n\n"
        "Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.\n\n"
        f"Viele Grüße,\n{kurz} Vereinsverwaltung"
    )
    # HTML in der gemeinsamen Vorlage — dieselbe wie die Willkommens-Mail, damit
    # alle System-Mails einheitlich aussehen (Logo auf der Akzentfarbe, Karte in
    # der Flächenfarbe). Die Fußzeile der Vorlage trägt den App-Link (#140).
    html = EmailService.render_vtb_email(
        headline="Dein Login-Link",
        username=username,
        intro_html="hier ist dein Login-Link für die Vereinsverwaltung:",
        button_label="Jetzt einloggen",
        button_url=magic_url,
        hints=EmailService._MAGIC_LINK_HINTS,
        preheader=f"Dein Login-Link für die {kurz} Vereinsverwaltung – 7 Tage gültig, einmal nutzbar.",
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.MAIL_FROM
    msg["To"] = recipient
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    if settings.SMTP_PORT == 465:
        srv = smtplib.SMTP_SSL(settings.SMTP_SERVER, settings.SMTP_PORT)
    else:
        srv = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT)
        if settings.SMTP_USE_TLS:
            srv.starttls()
    try:
        srv.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        srv.sendmail(settings.MAIL_FROM, recipient, msg.as_string())
    finally:
        srv.quit()


@router.post("/magic-link/request")
def request_magic_link(data: MagicLinkRequest, request: Request, db=Depends(get_db)):
    """Sendet einen Login-Link an das Konto zur angegebenen Kennung.

    Kennung ist die E-Mail-Adresse **oder** der Benutzername – beides ist eindeutig.
    Der Link geht in jedem Fall an die am Konto hinterlegte Adresse, nie an eine
    eingetippte: Sonst wäre der Benutzername eines anderen genug, um sich dessen
    Link schicken zu lassen.

    Gibt immer 200 zurück, um keine Informationen über vorhandene Konten preiszugeben.
    """
    if not _smtp_configured():
        raise HTTPException(status_code=503, detail="E-Mail-Versand nicht konfiguriert")

    kennung = data.kennung.strip()
    if not kennung:
        raise HTTPException(status_code=422, detail="Bitte E-Mail-Adresse oder Benutzername eingeben.")
    # Sieht die Eingabe nach einer Adresse aus, wird der Aufbau geprüft, bevor
    # irgendetwas passiert: Ein Vertipper bekommt so sofort einen Hinweis statt der
    # beruhigenden 200, und offensichtlicher Unsinn landet nicht im Protokoll. Ohne @
    # ist ein Benutzername gemeint – für den gibt es keine Formregel außer der Länge.
    # Über vorhandene Konten verrät die Antwort in keinem Fall etwas: Geprüft wird
    # nur die Form der Eingabe, nicht der Bestand.
    if '@' in kennung:
        mailadresse_or_422(kennung, pflicht=True)

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
        _log_access(db, request, "magic_link_rate_limited",
                    detail=f"ip · {data.kennung}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Zu viele Anfragen. Bitte versuche es später erneut.",
        )

    user = db.get_user_by_kennung(kennung)
    # Zustellbar heißt: Konto gefunden, aktiv und mit hinterlegter Adresse. Der
    # letzte Punkt ist neu wichtig – ein Namensträger ohne App-Zugang (email IS NULL)
    # ist über den Benutzernamen jetzt auffindbar, bekommt aber weiterhin keinen Link.
    zustellbar = bool(user and user.active and (user.email or '').strip())

    # Protokoll: ob ein zustellbares Konto existierte, nur im detail-Feld – nach außen
    # bleibt die Antwort einheitlich 200 (kein User-Enumeration-Leak). Getroffene Konten
    # stehen mit id/Benutzername dabei, auch wenn nichts rausging: Sonst ließe sich
    # später nicht erklären, warum jemand keinen Link bekommen hat.
    #
    # Die angefragte Kennung steht ebenfalls dabei, und zwar **wie eingetippt**: Bei
    # no_match ist sie die einzige Spur — ohne sie sieht man, dass jemand Kennungen
    # durchprobiert, aber nicht welche. Groß-/Kleinschreibung spielt für den Abgleich
    # zwar keine Rolle mehr, ein überzähliges Zeichen oder Leerzeichen im Wort aber
    # sehr wohl — und das erkennt man nur am Original, nicht an einer normalisierten
    # Fassung.
    _log_access(
        db, request, "magic_link_request",
        user_id=user.id if user else None,
        username=user.username if user else None,
        detail=f"{'match' if zustellbar else 'no_match'} · {data.kennung}",
    )
    should_send = zustellbar

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
            user_id=user.id, username=user.username,
            detail=f"user · {data.kennung}",
        )
        should_send = False

    if should_send:
        token = db.auth_token_repository.create_token(
            user_id=user.id,
            token_type="magic_link",
            expires_days=7,
        )
        try:
            # Empfänger ist immer die am Konto hinterlegte Adresse, nicht die
            # eingetippte Kennung – die kann ein Benutzername sein.
            _send_magic_link_email(user.email, user.username, token)
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
        display_name=_klarname(db, user),
        role=user.role,
        permissions=list(user.permissions),
    )
