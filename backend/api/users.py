from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.models.permission import Permission
from app.services.user_service import UserService
from ..core.deps import CurrentUser, DB
from ..core.authz import authorize_role_assignment

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
        'label': 'Mannschaften', 'icon': 'groups',
        'permissions': [
            (Permission.MANNSCHAFTEN_READ,   'Ansehen'),
            (Permission.MANNSCHAFTEN_WRITE,  'Bearbeiten'),
            (Permission.MANNSCHAFTEN_DELETE, 'Löschen'),
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
        'label': 'Gebühren', 'icon': 'receipt_long',
        'permissions': [
            (Permission.GEBUEHREN_READ,      'Ansehen'),
            (Permission.GEBUEHREN_WRITE,     'Bearbeiten'),
            (Permission.GEBUEHREN_ABRECHNEN, 'Abrechnen'),
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
        'label': 'Verwaltung', 'icon': 'admin_panel_settings',
        'permissions': [
            (Permission.FUNKTIONEN_VERWALTEN, 'Funktionen verwalten'),
            (Permission.KASSEN_VERWALTEN,     'Kassen verwalten'),
            (Permission.SYSTEM_CONFIG,        'System-Konfiguration'),
            (Permission.SYSTEM_PROTOKOLL,     'Protokoll einsehen'),
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


def permission_groups_payload():
    """Statische Berechtigungsgruppen für die UI (Label + Keys je Gruppe)."""
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
    # Neues Format (Stufe C): Tri-State-Overrides.
    grants: list[str] | None = None
    denies: list[str] | None = None
    # Legacy-Format (vor Stufe C): nur Grants – weiterhin akzeptiert.
    permissions: list[str] | None = None


# --- Endpoints ---

@router.get("/")
def list_users(user: CurrentUser, db: DB):
    _require_read(user)
    service = UserService(db)
    return [_user_to_dict(u) for u in service.list_all()]


@router.get("/permission-groups")
def get_permission_groups(user: CurrentUser):
    _require_read(user)
    return permission_groups_payload()


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
    role = authorize_role_assignment(user, data.role)
    service = UserService(db)
    try:
        created = service.create(
            username=data.username,
            email=data.email,
            role=role,
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
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    role = authorize_role_assignment(user, data.role, current_role=target.role)
    service = UserService(db)
    try:
        service.update(
            user_id=user_id,
            username=data.username,
            email=data.email,
            role=role,
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


def _permissions_payload(target, db):
    """Effektive Rechte + Herkunft + Overrides eines Users (siehe BERECHTIGUNGEN.md)."""
    from app.models.permission import BASE_PERMISSIONS
    eff = db.permissions.get_effective_permissions(target.id)
    overrides = db.permissions.get_overrides_for_user(target.id)
    # Geerbt = aus Sockel oder Funktion (ohne individuelle Grants)
    inherited = sorted({
        key for key, srcs in eff.sources.items()
        if any(s['typ'] in ('sockel', 'funktion') for s in srcs)
    })
    effective = []
    for key in sorted(eff.keys()):
        scopes = 'global' if key in eff.global_perms else sorted(eff.scoped.get(key, set()))
        effective.append({'key': key, 'scopes': scopes})
    return {
        'user':      _user_to_dict(target),
        'base':      sorted(BASE_PERMISSIONS),
        'inherited': inherited,
        'sources':   eff.sources,
        'grants':    sorted(overrides['grants']),
        'denies':    sorted(overrides['denies']),
        'effective': effective,
    }


@router.get("/{user_id}/permissions")
def get_permissions(user_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    return _permissions_payload(target, db)


@router.put("/{user_id}/permissions")
def set_permissions(user_id: int, data: PermissionsUpdate, user: CurrentUser, db: DB):
    _require_permissions(user)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    valid = set(Permission.all())
    if data.grants is not None or data.denies is not None:
        grants = set(data.grants or [])
        denies = set(data.denies or [])
        unbekannt = (grants | denies) - valid
        if unbekannt:
            raise HTTPException(status_code=422, detail=f"Unbekannte Permission(s): {sorted(unbekannt)}")
        if grants & denies:
            raise HTTPException(status_code=422, detail=f"Permission gleichzeitig grant und deny: {sorted(grants & denies)}")
        db.permissions.set_overrides_for_user(user_id, grants, denies, actor=user.username)
    elif data.permissions is not None:
        # Legacy: nur Grants setzen (keine Denies)
        perms = set(data.permissions)
        unbekannt = perms - valid
        if unbekannt:
            raise HTTPException(status_code=422, detail=f"Unbekannte Permission(s): {sorted(unbekannt)}")
        db.permissions.set_permissions_for_user(user_id, perms, actor=user.username)
    else:
        raise HTTPException(status_code=422, detail="grants/denies oder permissions erforderlich")

    return _permissions_payload(target, db)
