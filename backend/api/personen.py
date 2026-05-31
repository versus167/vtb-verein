from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.mitglied import Mitglied
from app.models.permission import Permission
from app.services.person_service import PersonService
from app.services.user_service import UserService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/personen", tags=["personen"])


# ---------------------------------------------------------------------------
# Pydantic-Schemas
# ---------------------------------------------------------------------------

class PersonCreate(BaseModel):
    email: str
    role: str = 'mitglied'
    active: bool = True
    password: Optional[str] = None
    # Mitglied-Felder (wenn vorname+nachname gesetzt → Vereinsmitglied anlegen)
    vorname: Optional[str] = None
    nachname: Optional[str] = None
    geburtsdatum: Optional[str] = None
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    telefon: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    mitglied_status: str = 'aktiv'
    zahlungsart: str = ''
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None
    # Nur für Admin/Benutzer-only: expliziter Username
    username: Optional[str] = None


class PersonUserUpdate(BaseModel):
    username: str
    email: str
    role: str
    active: bool
    expected_version: int


class PersonMitgliedUpdate(BaseModel):
    vorname: str
    nachname: str
    geburtsdatum: Optional[str] = None
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    telefon: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    status: str = 'aktiv'
    zahlungsart: str = ''
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None
    expected_version: int


class MeinMitgliedUpdate(BaseModel):
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    telefon: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    expected_version: int


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _require_manage(user):
    if not user.has_permission(Permission.USERS_MANAGE):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def _mitglied_to_dict(m) -> dict:
    if m is None:
        return None
    return {
        'id': m.id,
        'mitgliedsnummer': m.mitgliedsnummer,
        'vorname': m.vorname,
        'nachname': m.nachname,
        'geburtsdatum': m.geburtsdatum,
        'strasse': m.strasse,
        'plz': m.plz,
        'ort': m.ort,
        'land': m.land,
        'email': m.email,
        'telefon': m.telefon,
        'eintrittsdatum': m.eintrittsdatum,
        'austrittsdatum': m.austrittsdatum,
        'status': m.status,
        'zahlungsart': m.zahlungsart,
        'iban': m.iban,
        'bic': m.bic,
        'kontoinhaber': m.kontoinhaber,
        'abgerechnet_bis': m.abgerechnet_bis,
        'user_id': m.user_id,
        'version': m.version,
        'created_at': m.created_at,
        'created_by': m.created_by,
        'updated_at': m.updated_at,
        'updated_by': m.updated_by,
    }


def _person_row(user, mitglied, abteilungen: list) -> dict:
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'role': user.role,
        'active': bool(user.active),
        'last_login': user.last_login,
        'user_version': user.version,
        'mitglied': _mitglied_to_dict(mitglied),
        'abteilungen': [
            {
                'id': z.id,
                'abteilung_id': z.abteilung_id,
                'abteilung_name': z.abteilung_name,
                'abteilung_kuerzel': z.abteilung_kuerzel,
                'status': z.status,
                'von': z.von,
                'bis': z.bis,
            }
            for z in abteilungen
        ],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_personen(user: CurrentUser, db: DB):
    _require_manage(user)
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT u.id, u.username, u.email, u.role, u.active, u.last_login, u.version,
                   m.id AS m_id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                   m.strasse, m.plz, m.ort, m.land, m.email AS m_email, m.telefon,
                   m.eintrittsdatum, m.austrittsdatum, m.status AS m_status,
                   m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                   m.user_id AS m_user_id, m.version AS m_version,
                   m.created_at AS m_created_at, m.created_by AS m_created_by,
                   m.updated_at AS m_updated_at, m.updated_by AS m_updated_by
            FROM users u
            LEFT JOIN mitglied m ON m.user_id = u.id AND m.deleted_at IS NULL
            WHERE u.deleted_at IS NULL
            ORDER BY COALESCE(m.nachname, u.username), COALESCE(m.vorname, '')
        """)
        rows = cur.fetchall()

    result = []
    for row in rows:
        r = dict(row)
        u_obj = type('U', (), {
            'id': r['id'], 'username': r['username'], 'email': r['email'],
            'role': r['role'], 'active': r['active'], 'last_login': r['last_login'],
            'version': r['version'],
        })()
        m_obj = None
        if r['m_id'] is not None:
            m_obj = Mitglied(
                id=r['m_id'], mitgliedsnummer=r['mitgliedsnummer'],
                vorname=r['vorname'], nachname=r['nachname'], geburtsdatum=r['geburtsdatum'],
                strasse=r['strasse'], plz=r['plz'], ort=r['ort'], land=r['land'],
                email=r['m_email'], telefon=r['telefon'],
                eintrittsdatum=r['eintrittsdatum'], austrittsdatum=r['austrittsdatum'],
                status=r['m_status'], zahlungsart=r['zahlungsart'],
                iban=r['iban'], bic=r['bic'], kontoinhaber=r['kontoinhaber'],
                abgerechnet_bis=r['abgerechnet_bis'], user_id=r['m_user_id'],
                version=r['m_version'], created_at=r['m_created_at'],
                created_by=r['m_created_by'], updated_at=r['m_updated_at'],
                updated_by=r['m_updated_by'],
            )
        abteilungen = db.list_mitglied_abteilungen(m_obj.id) if m_obj else []
        result.append(_person_row(u_obj, m_obj, abteilungen))
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_person(data: PersonCreate, user: CurrentUser, db: DB):
    _require_manage(user)
    service = PersonService(db)
    try:
        if data.vorname and data.nachname:
            mitglied_data = {
                'geburtsdatum': data.geburtsdatum,
                'strasse': data.strasse, 'plz': data.plz, 'ort': data.ort, 'land': data.land,
                'telefon': data.telefon,
                'eintrittsdatum': data.eintrittsdatum, 'austrittsdatum': data.austrittsdatum,
                'status': data.mitglied_status, 'zahlungsart': data.zahlungsart,
                'iban': data.iban, 'bic': data.bic, 'kontoinhaber': data.kontoinhaber,
                'abgerechnet_bis': data.abgerechnet_bis,
            }
            u, m = service.create_vereinsmitglied(
                vorname=data.vorname, nachname=data.nachname,
                email=data.email, role=data.role, active=data.active,
                created_by=user.username, mitglied_data=mitglied_data,
                password=data.password,
            )
            abteilungen = db.list_mitglied_abteilungen(m.id)
            return _person_row(u, m, abteilungen)
        else:
            if not data.username:
                raise HTTPException(status_code=400, detail="Username ist pflicht für Benutzer ohne Mitglied-Datensatz")
            u = service.create_user_only(
                username=data.username, email=data.email, role=data.role,
                active=data.active, created_by=user.username, password=data.password,
            )
            return _person_row(u, None, [])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{user_id}/user")
def update_person_user(user_id: int, data: PersonUserUpdate, user: CurrentUser, db: DB):
    _require_manage(user)
    svc = UserService(db)
    try:
        ok = svc.update(
            user_id=user_id, username=data.username, email=data.email,
            role=data.role, active=data.active,
            updated_by=user.username, expected_version=data.expected_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    u = db.get_user_by_id(user_id)
    m = db.get_mitglied_by_user_id(user_id)
    # E-Mail im Mitglied-Datensatz synchron halten
    if m and m.email != data.email:
        m.email = data.email
        db.update_mitglied(m, updated_by=user.username)
        m = db.get_mitglied_by_user_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id) if m else []
    return _person_row(u, m, abteilungen)


@router.put("/{user_id}/mitglied")
def update_person_mitglied(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    _require_manage(user)
    m = db.get_mitglied_by_user_id(user_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Kein Mitglied-Datensatz für diesen User")
    m.vorname = data.vorname
    m.nachname = data.nachname
    m.geburtsdatum = data.geburtsdatum
    m.strasse = data.strasse
    m.plz = data.plz
    m.ort = data.ort
    m.land = data.land
    m.telefon = data.telefon
    m.eintrittsdatum = data.eintrittsdatum
    m.austrittsdatum = data.austrittsdatum
    m.status = data.status
    m.zahlungsart = data.zahlungsart
    m.iban = data.iban
    m.bic = data.bic
    m.kontoinhaber = data.kontoinhaber
    m.abgerechnet_bis = data.abgerechnet_bis
    m.version = data.expected_version
    ok = db.update_mitglied(m, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    u = db.get_user_by_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    return _person_row(u, db.get_mitglied_by_user_id(user_id), abteilungen)


@router.post("/{user_id}/mitglied", status_code=status.HTTP_201_CREATED)
def create_mitglied_fuer_user(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    """Verknüpft einen bestehenden User nachträglich mit einem Mitglied-Datensatz."""
    _require_manage(user)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    if db.get_mitglied_by_user_id(user_id) is not None:
        raise HTTPException(status_code=409, detail="Dieser User hat bereits einen Mitglied-Datensatz")
    m = Mitglied(
        vorname=data.vorname, nachname=data.nachname,
        geburtsdatum=data.geburtsdatum,
        strasse=data.strasse, plz=data.plz, ort=data.ort, land=data.land,
        telefon=data.telefon,
        eintrittsdatum=data.eintrittsdatum, austrittsdatum=data.austrittsdatum,
        status=data.status, zahlungsart=data.zahlungsart,
        iban=data.iban, bic=data.bic, kontoinhaber=data.kontoinhaber,
        abgerechnet_bis=data.abgerechnet_bis,
        email=u.email,
        user_id=user_id,
    )
    mitglied = db.create_mitglied(m, created_by=user.username)
    abteilungen = db.list_mitglied_abteilungen(mitglied.id)
    return _person_row(u, mitglied, abteilungen)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(user_id: int, user: CurrentUser, db: DB):
    _require_manage(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Eigener Account kann nicht gelöscht werden")
    try:
        PersonService(db).delete_person(user_id, deleted_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{user_id}/history")
def get_person_history(user_id: int, user: CurrentUser, db: DB):
    _require_manage(user)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")

    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, username, email, role, active, last_login,
                   created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            FROM users_history WHERE id = %s ORDER BY version ASC
            """,
            (user_id,),
        )
        user_history = [dict(r) for r in cur.fetchall()]

    mitglied = db.get_mitglied_by_user_id(user_id)
    mitglied_history = db.get_mitglied_history(mitglied.id) if mitglied else []

    return {'user': user_history, 'mitglied': mitglied_history}


# ---------------------------------------------------------------------------
# Eigenes Profil (für Rolle 'mitglied')
# ---------------------------------------------------------------------------

@router.get("/mein-mitglied")
def get_mein_mitglied(user: CurrentUser, db: DB):
    m = db.get_mitglied_by_user_id(user.id)
    return _mitglied_to_dict(m)


@router.put("/mein-mitglied")
def update_mein_mitglied(data: MeinMitgliedUpdate, user: CurrentUser, db: DB):
    m = db.get_mitglied_by_user_id(user.id)
    if m is None:
        raise HTTPException(status_code=404, detail="Kein Mitglied-Datensatz für diesen Account")
    m.strasse = data.strasse
    m.plz = data.plz
    m.ort = data.ort
    m.land = data.land
    m.telefon = data.telefon
    m.iban = data.iban
    m.bic = data.bic
    m.kontoinhaber = data.kontoinhaber
    m.version = data.expected_version
    ok = db.update_mitglied(m, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return _mitglied_to_dict(db.get_mitglied_by_user_id(user.id))
