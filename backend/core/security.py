from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from .config import settings


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
