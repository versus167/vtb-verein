import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from .config import settings

logger = logging.getLogger("app")

_FEHLT = (
    "VTB_SECRET_KEY ist nicht gesetzt oder steht noch auf dem Platzhalter "
    "'{platzhalter}'. Dieser Wert steht im öffentlichen Quellcode: Wer ihn kennt, "
    "stellt sich selbst ein gültiges Session-Token für jedes Konto aus — auch für "
    "Administratoren. Der Widerruf angemeldeter Geräte greift dagegen nicht, weil "
    "Token ohne Session-ID bewusst geduldet werden (Altbestand, s. core/deps.py).\n"
    "Die App startet deshalb nicht. Eigenen Schlüssel erzeugen mit:\n"
    '    python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
    "und als VTB_SECRET_KEY in die .env eintragen. Hinweis: Ein neuer Schlüssel "
    "meldet alle angemeldeten Nutzer einmalig ab."
)

_SCHWACH = (
    "VTB_SECRET_KEY ist mit %d Zeichen kürzer als die empfohlenen %d. Der Start "
    "läuft weiter, ein längerer Schlüssel wäre aber besser: "
    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
)


def pruefe_signaturschluessel() -> None:
    """Bricht den Start ab, wenn die Session-Tokens fälschbar wären.

    Läuft bewusst im Startup (s. main.py) und nicht beim Import von ``config``:
    Tests und Werkzeuge importieren ``settings``, ohne die App zu starten — die
    sollen davon unberührt bleiben. Wer die App wirklich startet, kommt hier
    vorbei, und zwar vor dem ersten Datenbankzugriff.
    """
    if settings.secret_key_fehlt:
        raise RuntimeError(_FEHLT.format(platzhalter=settings.SECRET_KEY_PLATZHALTER))
    if settings.secret_key_schwach:
        logger.warning(_SCHWACH, len(settings.SECRET_KEY.strip()),
                       settings.SECRET_KEY_MIN_LAENGE)


def create_access_token(
    user_id: int,
    expires_delta: Optional[timedelta] = None,
    session_id: Optional[str] = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(user_id), "exp": expire}
    if session_id is not None:
        # Serverseitige Session-ID – ermöglicht Geräteliste + Abmelden (Ticket #24).
        payload["sid"] = session_id
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None
