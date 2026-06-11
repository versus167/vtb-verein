from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from app.services.user_service import UserService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/users", tags=["users"])

PERMISSION_GROUPS = [
    {
        'label': 'Personen', 'icon': 'people',
        'permissions': [
            (Permission.PERSONEN_READ,        'Ansehen'),
            (Permission.PERSONEN_WRITE,       'Bearbeiten'),
            (Permission.PERSONEN_DELETE,      'Löschen'),
            (Permission.PERSONEN_PERMISSIONS, 'Berechtigungen verwalten'),
        ],
    },
    {
        'label': 'Abteilungen', 'icon': 'account_tree',
        'permissions': [
            (Permission.ABTEILUNGEN_READ,   'Ansehen'),
            (Permission.ABTEILUNGEN_WRITE,  'Bearbeiten'),
            (Permission.ABTEILUNGEN_DELETE, 'Löschen'),
        ],
    },
    {
        'label': 'Beiträge', 'icon': 'euro',
        'permissions': [
            (Permission.BEITRAEGE_READ,      'Ansehen'),
            (Permission.BEITRAEGE_WRITE,     'Bearbeiten'),
            (Permission.BEITRAEGE_ABRECHNEN, 'Abrechnen'),
        ],
    },
    {
        'label': 'Berichte', 'icon': 'bar_chart',
        'permissions': [
            (Permission.BERICHTE_READ,   'Ansehen'),
            (Permission.BERICHTE_EXPORT, 'Exportieren'),
        ],
    },
    {
        'label': 'System', 'icon': 'settings',
        'permissions': [
            (Permission.SYSTEM_CONFIG, 'Konfiguration'),
        ],
    },
    {
        'label': 'Tickets', 'icon': 'confirmation_number',
        'permissions': [
            (Permission.TICKETS_ACCESS,             'Zugang'),
            (Permission.TICKETS_BEREICHE_VERWALTEN, 'Bereiche verwalten'),
        ],
    },
]


def _require_read(user):
    if not user.has_permission(Permission.PERSONEN_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Leseberechtigung")

def _require_write(user):
    if not user.has_permission(Permission.PERSONEN_WRITE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Schreibberechtigung")

def _require_delete(user):
    if not user.has_permission(Permission.PERSONEN_DELETE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Löschberechtigung")

def _require_permissions(user):
    if not user.has_permission(Permission.PERSONEN_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Berechtigung für Berechtigungsverwaltung")


def _user_to_dict(u):
    return {
        'id':         u.id,
        'username':   u.username,
        'email':      u.email,
        'role':       u.role,
        'active':     u.active,
        'last_login': u.last_login,
        'last_seen':  u.last_seen,
        'version':    u.version,
    }


# --- Schemas ---

class UserCreate(BaseModel):
    username: str
    email: str
    role: str
    active: bool = True
    password: Optional[str] = None


class UserUpdate(BaseModel):
    username: str
    email: str
    role: str
    active: bool
    expected_version: int


class PasswordChange(BaseModel):
    new_password: str


class PermissionsUpdate(BaseModel):
    permissions: list[str]


# --- Endpoints ---

@router.get("/")
def list_users(user: CurrentUser, db: DB):
    _require_read(user)
    service = UserService(db)
    return [_user_to_dict(u) for u in service.list_all()]


@router.get("/permission-groups")
def get_permission_groups(user: CurrentUser):
    _require_read(user)
    return [
        {
            'label': g['label'],
            'icon':  g['icon'],
            'permissions': [
                {'key': key, 'label': label}
                for key, label in g['permissions']
            ],
        }
        for g in PERMISSION_GROUPS
    ]


@router.get("/{user_id}")
def get_user(user_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    return _user_to_dict(target)


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, user: CurrentUser, db: DB):
    _require_write(user)
    service = UserService(db)
    try:
        created = service.create(
            username=data.username,
            email=data.email,
            role=data.role,
            active=data.active,
            created_by=user.username,
            password=data.password,
            send_magic_link=data.active,
        )
        return _user_to_dict(created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{user_id}")
def update_user(user_id: int, data: UserUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    service = UserService(db)
    try:
        service.update(
            user_id=user_id,
            username=data.username,
            email=data.email,
            role=data.role,
            active=data.active,
            updated_by=user.username,
            expected_version=data.expected_version,
        )
        return _user_to_dict(db.get_user_by_id(user_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{user_id}/password")
def change_password(user_id: int, data: PasswordChange, user: CurrentUser, db: DB):
    _require_write(user)
    service = UserService(db)
    try:
        service.change_password(user_id, data.new_password, updated_by=user.username)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Eigenen Account nicht löschbar")
    service = UserService(db)
    try:
        service.delete(user_id, deleted_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{user_id}/permissions")
def get_permissions(user_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    current = list(db.permissions.get_permissions_for_user(user_id))
    defaults = list(Permission.defaults_for_role(target.role))
    return {
        'user':     _user_to_dict(target),
        'current':  current,
        'defaults': defaults,
    }


@router.put("/{user_id}/permissions")
def set_permissions(user_id: int, data: PermissionsUpdate, user: CurrentUser, db: DB):
    _require_permissions(user)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    if target.role == 'admin' and Permission.PERSONEN_PERMISSIONS not in data.permissions:
        if db.count_active_admins() <= 1:
            raise HTTPException(
                status_code=400,
                detail="Kann personen.permissions nicht entziehen: letzter aktiver Administrator",
            )
    db.permissions.set_permissions_for_user(
        user_id=user_id,
        permissions=set(data.permissions),
        actor=user.username,
    )
    return {"ok": True}
