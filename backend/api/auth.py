from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from app.services.user_service import UserService
from ..core.db import get_db
from ..core.security import create_access_token
from ..core.deps import CurrentUser
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


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db=Depends(get_db),
):
    service = UserService(db)
    user = service.authenticate(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falscher Benutzername oder Passwort",
        )
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


@router.get("/me", response_model=UserInfo)
def get_me(user: CurrentUser):
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        permissions=list(user.permissions),
    )
