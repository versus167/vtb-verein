from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from app.models.mitglied import Mitglied
from app.models.permission import Permission
from app.services.person_service import PersonService
from app.services.user_service import UserService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/personen", tags=["personen"])


# ---------------------------------------------------------------------------
# Pydantic-Schemas
# ---------------------------------------------------------------------------

def _none_if_empty(v):
    return None if v == '' else v


class PersonCreate(BaseModel):
    email: Optional[str] = None
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

    @field_validator('eintrittsdatum', 'austrittsdatum', 'geburtsdatum', 'abgerechnet_bis', mode='before')
    @classmethod
    def empty_str_to_none(cls, v): return _none_if_empty(v)
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


class NutzerFuerMitgliedCreate(BaseModel):
    email: str
    role: str = 'mitglied'
    active: bool = True
    password: Optional[str] = None


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

    @field_validator('eintrittsdatum', 'austrittsdatum', 'geburtsdatum', 'abgerechnet_bis', mode='before')
    @classmethod
    def empty_str_to_none(cls, v): return _none_if_empty(v)
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

def _require_read(user):
    if not user.has_permission(Permission.PERSONEN_READ):
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung")

def _require_write(user):
    if not user.has_permission(Permission.PERSONEN_WRITE):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung")

def _require_delete(user):
    if not user.has_permission(Permission.PERSONEN_DELETE):
        raise HTTPException(status_code=403, detail="Keine Löschberechtigung")


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


def _person_row(user, mitglied, abteilungen: list, funktionen: list) -> dict:
    # Berechne "zuletzt bearbeitet" als Maximum der updated_at Felder
    user_updated = user.updated_at if user else None
    mitglied_updated = mitglied.updated_at if mitglied else None
    last_edited = None
    if user_updated and mitglied_updated:
        last_edited = user_updated if user_updated > mitglied_updated else mitglied_updated
    elif user_updated:
        last_edited = user_updated
    elif mitglied_updated:
        last_edited = mitglied_updated
    
    return {
        'user_id': user.id if user else None,
        'username': user.username if user else None,
        'email': user.email if user else None,
        'role': user.role if user else None,
        'active': bool(user.active) if user else True,
        'last_login': user.last_login if user else None,
        'last_edited': last_edited,
        'user_version': user.version if user else None,
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
        'funktionen': [
            {
                'id': f.id,
                'funktion': f.funktion,
                'abteilung_id': f.abteilung_id,
                'abteilung_name': f.abteilung_name,
                'von': f.von,
                'bis': f.bis,
            }
            for f in funktionen
        ],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_personen(user: CurrentUser, db: DB):
    _require_read(user)
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM (
                SELECT u.id, u.username, u.email, u.role, u.active, u.last_login, u.version, u.updated_at,
                       m.id AS m_id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS m_email,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS telefon,
                       m.eintrittsdatum, m.austrittsdatum, m.status AS m_status,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       m.user_id AS m_user_id, m.version AS m_version,
                       m.created_at AS m_created_at, m.created_by AS m_created_by,
                       m.updated_at AS m_updated_at, m.updated_by AS m_updated_by
                FROM users u
                LEFT JOIN mitglied m ON m.user_id = u.id AND m.deleted_at IS NULL
                WHERE u.deleted_at IS NULL
                UNION ALL
                SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                       m.id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       m.eintrittsdatum, m.austrittsdatum, m.status,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       NULL, m.version,
                       m.created_at, m.created_by, m.updated_at, m.updated_by
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND m.user_id IS NULL
            ) p
            ORDER BY COALESCE(p.vorname, p.username), COALESCE(p.nachname, '')
        """)
        rows = cur.fetchall()

    result = []
    for row in rows:
        r = dict(row)
        u_obj = None
        if r['id'] is not None:
            u_obj = type('U', (), {
                'id': r['id'], 'username': r['username'], 'email': r['email'],
                'role': r['role'], 'active': r['active'], 'last_login': r['last_login'],
                'version': r['version'],
                'updated_at': r['updated_at'],
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
        funktionen = db.list_mitglied_funktionen(m_obj.id) if m_obj else []
        result.append(_person_row(u_obj, m_obj, abteilungen, funktionen))
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_person(data: PersonCreate, user: CurrentUser, db: DB):
    _require_write(user)
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
            if data.email:
                u, m = service.create_vereinsmitglied(
                    vorname=data.vorname, nachname=data.nachname,
                    email=data.email, role=data.role, active=data.active,
                    created_by=user.username, mitglied_data=mitglied_data,
                    password=data.password,
                )
                abteilungen = db.list_mitglied_abteilungen(m.id)
                return _person_row(u, m, abteilungen)
            else:
                m = service.create_mitglied_ohne_user(
                    vorname=data.vorname, nachname=data.nachname,
                    created_by=user.username, mitglied_data=mitglied_data,
                )
                abteilungen = db.list_mitglied_abteilungen(m.id)
                return _person_row(None, m, abteilungen)
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
    _require_write(user)
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
    # Primären E-Mail-Kontakt des Mitglieds mit der Login-E-Mail synchron halten
    if m:
        db.set_mitglied_primaer_kontakt(m.id, 'email', data.email, user.username)
        m = db.get_mitglied_by_user_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id) if m else []
    return _person_row(u, m, abteilungen)


@router.put("/{user_id}/mitglied")
def update_person_mitglied(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    _require_write(user)
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
    # Primären Telefon-Kontakt aus dem Einzelfeld pflegen (weitere Kontakte über /kontakte)
    db.set_mitglied_primaer_kontakt(m.id, 'telefon', data.telefon, user.username)
    u = db.get_user_by_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    return _person_row(u, db.get_mitglied_by_user_id(user_id), abteilungen)


@router.post("/{user_id}/mitglied", status_code=status.HTTP_201_CREATED)
def create_mitglied_fuer_user(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    """Verknüpft einen bestehenden User nachträglich mit einem Mitglied-Datensatz."""
    _require_write(user)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    if db.get_mitglied_by_user_id(user_id) is not None:
        raise HTTPException(status_code=409, detail="Dieser User hat bereits einen Mitglied-Datensatz")
    m = Mitglied(
        vorname=data.vorname, nachname=data.nachname,
        geburtsdatum=data.geburtsdatum,
        strasse=data.strasse, plz=data.plz, ort=data.ort, land=data.land,
        eintrittsdatum=data.eintrittsdatum, austrittsdatum=data.austrittsdatum,
        status=data.status, zahlungsart=data.zahlungsart,
        iban=data.iban, bic=data.bic, kontoinhaber=data.kontoinhaber,
        abgerechnet_bis=data.abgerechnet_bis,
        user_id=user_id,
    )
    mitglied = db.create_mitglied(m, created_by=user.username)
    # Primäre Kontakte anlegen (E-Mail = Login-E-Mail, Telefon aus Formular)
    if u.email:
        db.create_mitglied_kontakt(mitglied.id, 'email', u.email, None, True, user.username)
        mitglied.email = u.email
    if data.telefon:
        db.create_mitglied_kontakt(mitglied.id, 'telefon', data.telefon, None, True, user.username)
        mitglied.telefon = data.telefon
    abteilungen = db.list_mitglied_abteilungen(mitglied.id)
    return _person_row(u, mitglied, abteilungen)


@router.post("/mitglied/{mitglied_id}/nutzer", status_code=status.HTTP_201_CREATED)
def create_nutzer_fuer_mitglied(mitglied_id: int, data: NutzerFuerMitgliedCreate,
                                user: CurrentUser, db: DB):
    """Legt einen Login-Account für ein bestehendes Mitglied ohne User-Konto an."""
    _require_write(user)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    if m.user_id is not None:
        raise HTTPException(status_code=409, detail="Dieses Mitglied hat bereits einen Login-Account")

    service = PersonService(db)
    try:
        u = service.create_user_only(
            username=service._generate_username(m.vorname, m.nachname),
            email=data.email,
            role=data.role,
            active=data.active,
            created_by=user.username,
            password=data.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Mitglied mit dem neuen User verknüpfen
    m.user_id = u.id
    db.update_mitglied(m, updated_by=user.username)

    # E-Mail als primären Kontakt setzen
    db.set_mitglied_primaer_kontakt(m.id, 'email', data.email, user.username)

    m = db.get_mitglied(mitglied_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    return _person_row(u, m, abteilungen)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(user_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Eigener Account kann nicht gelöscht werden")
    try:
        PersonService(db).delete_person(user_id, deleted_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/mitglied/{mitglied_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mitglied_ohne_user(mitglied_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    m = db.get_mitglied(mitglied_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    if m.user_id is not None:
        raise HTTPException(status_code=400, detail="Mitglied hat einen User-Account — bitte über Person löschen")
    PersonService(db).delete_mitglied_ohne_user(mitglied_id, deleted_by=user.username)


@router.get("/{user_id}/history")
def get_person_history(user_id: int, user: CurrentUser, db: DB):
    _require_read(user)
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

    abteilung_history = []
    if mitglied:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT mah.id, mah.version, mah.abteilung_id,
                       COALESCE(a.name, mah.abteilung_id::text) AS abteilung_name,
                       a.kuerzel AS abteilung_kuerzel,
                       mah.status, mah.von, mah.bis,
                       mah.created_at, mah.created_by,
                       mah.updated_at, mah.updated_by,
                       mah.deleted_at, mah.deleted_by
                FROM mitglied_abteilung_history mah
                LEFT JOIN abteilung a ON a.id = mah.abteilung_id
                WHERE mah.mitglied_id = %s
                ORDER BY mah.id, mah.version ASC
                """,
                (mitglied.id,),
            )
            abteilung_history = [dict(r) for r in cur.fetchall()]

    return {'user': user_history, 'mitglied': mitglied_history, 'abteilungen': abteilung_history}


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
    db.set_mitglied_primaer_kontakt(m.id, 'telefon', data.telefon, user.username)
    return _mitglied_to_dict(db.get_mitglied_by_user_id(user.id))
