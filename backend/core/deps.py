from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from .security import decode_token
from .db import get_db
from app.models.user import User
from app.db.datastore import VereinsDB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[VereinsDB, Depends(get_db)],
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültige Anmeldedaten",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None:
        raise exc
    user_id = payload.get("sub")
    if user_id is None:
        raise exc
    user = db.get_user_by_id(int(user_id))
    if user is None or not user.active:
        raise exc
    # "Zuletzt aktiv" tracken: jeder authentifizierte Request markiert Aktivität
    # (im Repository auf 1×/Minute gedrosselt). Best-effort – darf Auth nie brechen.
    try:
        db.update_last_seen(user.id)
    except Exception:
        pass
    # Permissions frisch aus der DB laden (damit Admin-Änderungen sofort wirken)
    user.permissions = db.permissions.get_permissions_for_user(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[VereinsDB, Depends(get_db)]
