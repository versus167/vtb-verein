from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, field_validator, model_validator

from app.models.mitglied import Mitglied, validate_status
from app.models.permission import BASE_PERMISSIONS, Permission
from app.services.person_service import PersonService
from app.services.user_service import UserService
from ..core.deps import CurrentUser, DB
from ..core.authz import authorize_role_assignment
from ..core.scope import require_mitglied, require_person, visible_mitglied_ids
from ..core.validation import iban_or_422, mailadresse_or_422
from .auth import _client_ip, _ts_iso

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
    geschlecht: Optional[str] = None        # 'm' | 'w' | 'd'
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    telefon: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    mitglied_status: str = 'aktiv'
    art: str = 'mitglied'                   # 'mitglied' | 'gastspieler' (#95 Teil 2)

    @field_validator('eintrittsdatum', 'austrittsdatum', 'geburtsdatum', 'abgerechnet_bis', mode='before')
    @classmethod
    def empty_str_to_none(cls, v): return _none_if_empty(v)

    @field_validator('art')
    @classmethod
    def _art_gueltig(cls, v):
        if v not in ('mitglied', 'gastspieler'):
            raise ValueError("art muss 'mitglied' oder 'gastspieler' sein")
        return v

    @field_validator('mitglied_status')
    @classmethod
    def _mitglied_status_gueltig(cls, v):
        return validate_status(v)
    zahlungsart: str = ''
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None
    # Nur für Admin/Benutzer-only: expliziter Username
    username: Optional[str] = None


class PersonUserUpdate(BaseModel):
    username: str
    # Leer erlaubt: Konto ohne Zugang (z. B. reiner Schlüsselträger). Bei einem Konto
    # mit Mitgliedsdatensatz bleibt die Adresse in der Praxis gesetzt.
    email: Optional[str] = None
    role: str
    active: bool
    expected_version: int


class NutzerFuerMitgliedCreate(BaseModel):
    email: str
    role: str = 'mitglied'
    active: bool = True
    password: Optional[str] = None


class ZugangFreischalten(BaseModel):
    """Eingabe fürs Freischalten durch personen.freischalten.

    Bewusst OHNE role/active/password: Der Account entsteht immer als aktives
    Mitglied ohne Passwort (Login per Willkommens-Mail/Magic-Link, Passwort setzt
    sich der Freigeschaltete danach selbst über /auth/me/password). Damit ist die
    Anlage eines Admin-Kontos über diesen Weg strukturell ausgeschlossen und nicht
    bloß per Prüfung untersagt.
    """
    email: str


class ZugangMailadresse(BaseModel):
    """Neue Login-Adresse für einen noch nie benutzten Zugang."""
    email: str


class PersonMitgliedUpdate(BaseModel):
    vorname: str
    nachname: str
    geburtsdatum: Optional[str] = None
    geschlecht: Optional[str] = None        # 'm' | 'w' | 'd'
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    telefon: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    status: str = 'aktiv'
    art: str = 'mitglied'                   # 'mitglied' | 'gastspieler' (#95 Teil 2)

    @field_validator('eintrittsdatum', 'austrittsdatum', 'geburtsdatum', 'abgerechnet_bis',
                     'trainerlizenz_gueltig_bis', 'trainerlizenz_gueltig_von',
                     'trainerlizenz_nr', mode='before')
    @classmethod
    def empty_str_to_none(cls, v): return _none_if_empty(v)

    @field_validator('art')
    @classmethod
    def _art_gueltig(cls, v):
        if v not in ('mitglied', 'gastspieler'):
            raise ValueError("art muss 'mitglied' oder 'gastspieler' sein")
        return v

    @field_validator('status')
    @classmethod
    def _status_pruefen(cls, v):
        return validate_status(v)
    zahlungsart: str = ''
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None
    trainerlizenz_nr: Optional[str] = None
    qualifikation: Optional[str] = None
    trainerlizenz_gueltig_bis: Optional[str] = None
    trainerlizenz_gueltig_von: Optional[str] = None
    expected_version: int

    @model_validator(mode='after')
    def _lizenz_gekoppelt(self):
        """Trainerlizenz-Nr, Gültig-von und Gültig-bis nur GEMEINSAM (alle drei oder keins) –
        sonst würde z. B. eine Nr ohne Gültigkeitsdatum still als 'ohne Lizenz' abgerechnet (#63)."""
        gesetzt = [bool(self.trainerlizenz_nr),
                   bool(self.trainerlizenz_gueltig_von),
                   bool(self.trainerlizenz_gueltig_bis)]
        if any(gesetzt) and not all(gesetzt):
            raise ValueError(
                "Trainerlizenz nur vollständig: Lizenz-Nr., Gültig-von und Gültig-bis "
                "müssen zusammen ausgefüllt sein (oder alle leer)."
            )
        if all(gesetzt) and self.trainerlizenz_gueltig_von > self.trainerlizenz_gueltig_bis:
            raise ValueError("Lizenz: 'Gültig von' darf nicht nach 'Gültig bis' liegen.")
        return self


class MeinMitgliedUpdate(BaseModel):
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    # Einzugsermächtigung: True → zahlungsart 'lastschrift' (steuert den SEPA-Einzug
    # im Fibu-Export), False → 'sonstiges'. None lässt die Zahlungsart unangetastet.
    einzug_erlaubt: Optional[bool] = None
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

def _require_permissions(user):
    """Recht, Berechtigungen zu vergeben – Gate für das Anlegen von Login-Accounts."""
    if not user.has_permission(Permission.PERSONEN_PERMISSIONS):
        raise HTTPException(status_code=403, detail="Nur mit dem Recht, Berechtigungen zu vergeben, dürfen Login-Accounts angelegt werden")


def _require_freischalten(user):
    """Recht, einem bestehenden Mitglied den Zugang freizuschalten.

    personen.permissions bleibt Obermenge – wer Rechte vergeben darf, durfte auch
    vorher schon Logins anlegen.
    """
    if not (user.has_permission(Permission.PERSONEN_FREISCHALTEN)
            or user.has_permission(Permission.PERSONEN_PERMISSIONS)):
        raise HTTPException(status_code=403,
                            detail="Keine Berechtigung, Zugänge freizuschalten")


def _freischalt_scope(user, db) -> set[int] | None:
    """Mitglieds-IDs, für die dieser User Zugänge verwalten darf (None = alle).

    Wer personen.permissions vereinsweit hat, ist nie eingeschränkt. Für
    personen.freischalten greift die Abteilungs-Scope-Durchsetzung aus Stufe E:
    Ein über eine abteilungsgebundene Funktion geerbtes Recht (z. B. Betreuer)
    wirkt nur für Mitglieder der eigenen Abteilung.
    """
    if user.has_permission_global(Permission.PERSONEN_PERMISSIONS):
        return None
    return visible_mitglied_ids(user, db, Permission.PERSONEN_FREISCHALTEN)


def _require_freischalt_zugriff(user, db, mitglied_id: int) -> None:
    erlaubt = _freischalt_scope(user, db)
    if erlaubt is not None and mitglied_id not in erlaubt:
        raise HTTPException(status_code=403,
                            detail="Dieses Mitglied liegt außerhalb deines Bereichs")


def _nur_mitgliedskonto(user, db, ziel) -> None:
    """Riegelt Eingriffe an Konten ab, die mehr sind als ein Mitgliedszugang.

    Wer Rechte vergeben darf, darf ohnehin alles hier. Alle anderen sollen weder
    einem Administrator noch jemandem mit weitergehenden Rechten (per Funktion oder
    Grant) den Zugang entziehen oder ihn über eine neue Login-Adresse übernehmen –
    das ist Sache der Rechteverwaltung.
    """
    if user.has_permission(Permission.PERSONEN_PERMISSIONS):
        return
    if ziel.role == 'admin':
        raise HTTPException(status_code=403,
                            detail="Administratoren-Zugänge kann nur die Rechteverwaltung ändern")
    weitergehend = db.permissions.get_effective_permissions(ziel.id).keys() - BASE_PERMISSIONS
    if weitergehend:
        raise HTTPException(
            status_code=403,
            detail="Dieser Zugang trägt weitergehende Rechte – bitte über die "
                   "Rechteverwaltung ändern.",
        )


def _log_zugang(db, request, event_type: str, actor, *, detail: str) -> None:
    """Freischalt-Ereignis ins Zugriffsprotokoll – best-effort, nie den Request brechen.

    Protokolliert wird der *Handelnde* (username), das betroffene Konto steckt im
    Detail-Text: So beantwortet das Protokoll die Frage „wer hat wen freigeschaltet".
    """
    try:
        db.access_log_repository.log(
            event_type, category="zugang",
            user_id=actor.id, username=actor.username,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            detail=detail,
        )
    except Exception:
        pass


def _require_eintrittsdatum(data):
    """Jede Person im Personenstamm braucht ein Eintrittsdatum (Ticket #29) –
    bei Gastspielern ist das der Beginn der Gastspielgenehmigung."""
    if not (data.eintrittsdatum or '').strip():
        raise HTTPException(status_code=422, detail="Eintrittsdatum ist erforderlich")


def _apply_art(db, m, art: str) -> None:
    """Setzt die Personenart und zieht bei der Umwandlung Gastspieler →
    Vereinsmitglied die bislang fehlende Mitgliedsnummer nach (Gastspieler
    verbrauchen keine; ein Rückwechsel behält eine bereits vergebene Nummer)."""
    m.art = art
    if art == 'mitglied' and m.mitgliedsnummer is None:
        m.mitgliedsnummer = db.get_next_mitgliedsnummer()


def _mitglied_to_dict(m) -> dict:
    if m is None:
        return None
    return {
        'id': m.id,
        'mitgliedsnummer': m.mitgliedsnummer,
        'vorname': m.vorname,
        'nachname': m.nachname,
        'geburtsdatum': m.geburtsdatum,
        'geschlecht': m.geschlecht,
        'strasse': m.strasse,
        'plz': m.plz,
        'ort': m.ort,
        'land': m.land,
        'email': m.email,
        'telefon': m.telefon,
        'eintrittsdatum': m.eintrittsdatum,
        'austrittsdatum': m.austrittsdatum,
        'status': m.status,
        'art': m.art,
        'zahlungsart': m.zahlungsart,
        'iban': m.iban,
        'bic': m.bic,
        'kontoinhaber': m.kontoinhaber,
        'abgerechnet_bis': m.abgerechnet_bis,
        'trainerlizenz_nr': m.trainerlizenz_nr,
        'qualifikation': m.qualifikation,
        'trainerlizenz_gueltig_bis': m.trainerlizenz_gueltig_bis,
        'trainerlizenz_gueltig_von': m.trainerlizenz_gueltig_von,
        'user_id': m.user_id,
        'version': m.version,
        'created_at': m.created_at,
        'created_by': m.created_by,
        'updated_at': m.updated_at,
        'updated_by': m.updated_by,
    }


def _aktiv_oder_kuenftig(von, bis) -> bool:
    """True, solange die Zuordnung nicht bereits abgelaufen ist (bis < heute).

    Aktive (heute im Zeitraum) UND erst künftig beginnende (von in der Zukunft)
    Abteilungen/Funktionen bleiben damit in der Personenliste sichtbar; nur bereits
    beendete werden ausgeblendet. Die künftigen kennzeichnet das Frontend mit
    „ab <Beginndatum>" (Ticket #91)."""
    heute = date.today().isoformat()
    return not (bis and bis < heute)


def _last_edited_sql(mitglied_alias: str, user_alias: Optional[str]) -> str:
    """SQL-Ausdruck für „zuletzt bearbeitet" (Ticket #58).

    Maximum aus den updated_at-Feldern von User und Mitglied sowie der jüngsten
    Aktivität (created/updated/deleted) aller Unterdatensätze – Abteilungen,
    Funktionen, Kontakte, Mannschaften. So bewegt sich die Spalte auch, wenn z.B.
    eine Abteilung oder Funktion hinzugefügt, geändert oder entfernt wird, ohne
    dass dafür mitglied.updated_at (und damit die Historie) angefasst werden muss.
    Alle Zeitstempel sind TEXT in einheitlichem ISO-Format → lexikalisch
    vergleichbar; GREATEST ignoriert NULL-Werte.
    """
    terms = []
    if user_alias:
        terms.append(f"{user_alias}.updated_at")
    terms.append(f"{mitglied_alias}.updated_at")
    for tbl in ("mitglied_abteilung", "mitglied_funktion",
                "mitglied_kontakt", "mitglied_mannschaft"):
        terms.append(
            f"(SELECT MAX(GREATEST(c.created_at, c.updated_at, c.deleted_at)) "
            f"FROM {tbl} c WHERE c.mitglied_id = {mitglied_alias}.id)"
        )
    return "GREATEST(" + ", ".join(terms) + ")"


def _hat_passwort(user) -> bool:
    """Ob für dieses Konto ein Passwort gesetzt ist – ohne den Hash anzufassen."""
    if user is None:
        return False
    fertig = getattr(user, 'hat_passwort', None)
    if fertig is not None:
        return bool(fertig)
    return bool(getattr(user, 'password_hash', ''))


def _person_row(user, mitglied, abteilungen: list, funktionen: list,
                last_edited: Optional[str] = None,
                lizenz_aktuell_gueltig: Optional[bool] = None) -> dict:
    # In der Personenliste aktive UND erst künftig beginnende Abteilungen/Funktionen
    # zeigen; bereits abgelaufene bleiben ausgeblendet. Künftige (von in der Zukunft)
    # kennzeichnet das Frontend mit „ab <Beginndatum>" (Ticket #91).
    abteilungen = [z for z in abteilungen if _aktiv_oder_kuenftig(z.von, z.bis)]
    funktionen = [f for f in funktionen if _aktiv_oder_kuenftig(f.von, f.bis)]
    # "Zuletzt bearbeitet": Die Personenliste reicht den über alle Unterdatensätze
    # berechneten Wert herein (s. _last_edited_sql). Ohne Vorgabe (Einzel-Endpoints)
    # genügt das Maximum aus User- und Mitglied-updated_at.
    if last_edited is None:
        user_updated = user.updated_at if user else None
        mitglied_updated = mitglied.updated_at if mitglied else None
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
        # Nie der Hash selbst, nur: „kann sich dieses Konto anmelden?". Ohne E-Mail
        # UND ohne Passwort ist es ein Konto ohne Zugang (reiner Namensträger, etwa
        # ein Schlüsselträger) – die Liste zeigt das an, statt es als kaputten Login
        # aussehen zu lassen. Die Personenliste liefert das Flag fertig aus SQL
        # (sie holt die Hashes gar nicht erst), Einzel-Endpoints haben den User.
        'hat_passwort': _hat_passwort(user),
        'role': user.role if user else None,
        'active': bool(user.active) if user else True,
        'last_login': user.last_login if user else None,
        'last_seen': user.last_seen if user else None,
        'last_edited': last_edited,
        # Kleiner Lizenz-Hinweis in der Personenliste (unabhängig von der Funktion, #64):
        # HEUTE im Trainerlizenz-Fenster (server-seitig per CURRENT_DATE berechnet).
        'lizenz_aktuell_gueltig': bool(lizenz_aktuell_gueltig),
        'user_version': user.version if user else None,
        'mitglied': _mitglied_to_dict(mitglied),
        'abteilungen': [
            {
                'id': z.id,
                'abteilung_id': z.abteilung_id,
                'abteilung_name': z.abteilung_name,
                'abteilung_kuerzel': z.abteilung_kuerzel,
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
    # Abteilungs-Scope (Stufe E): nur-scoped personen.read → nur Mitglieder der
    # erlaubten Abteilungen; reine Benutzerkonten ohne Mitglied bleiben dann verborgen.
    visible = visible_mitglied_ids(user, db)
    with db.conn.cursor() as cur:
        cur.execute(f"""
            SELECT * FROM (
                SELECT u.id, u.username, u.email, u.role, u.active, u.last_login, u.last_seen, u.version, u.updated_at,
                       (u.password_hash <> '') AS hat_passwort,
                       m.id AS m_id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS m_email,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS telefon,
                       m.eintrittsdatum, m.austrittsdatum, m.status AS m_status, m.art,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       m.trainerlizenz_gueltig_von, m.trainerlizenz_gueltig_bis,
                       m.trainerlizenz_nr, m.qualifikation,
                       m.user_id AS m_user_id, m.version AS m_version,
                       m.created_at AS m_created_at, m.created_by AS m_created_by,
                       m.updated_at AS m_updated_at, m.updated_by AS m_updated_by,
                       {_last_edited_sql('m', 'u')} AS last_edited,
                       (m.trainerlizenz_gueltig_von IS NOT NULL AND m.trainerlizenz_gueltig_bis IS NOT NULL
                        AND m.trainerlizenz_gueltig_von <= CURRENT_DATE::text
                        AND m.trainerlizenz_gueltig_bis >= CURRENT_DATE::text) AS lizenz_aktuell_gueltig
                FROM users u
                LEFT JOIN mitglied m ON m.user_id = u.id AND m.deleted_at IS NULL
                WHERE u.deleted_at IS NULL
                UNION ALL
                SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, FALSE,
                       m.id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       m.eintrittsdatum, m.austrittsdatum, m.status, m.art,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       m.trainerlizenz_gueltig_von, m.trainerlizenz_gueltig_bis,
                       m.trainerlizenz_nr, m.qualifikation,
                       NULL, m.version,
                       m.created_at, m.created_by, m.updated_at, m.updated_by,
                       {_last_edited_sql('m', None)},
                       (m.trainerlizenz_gueltig_von IS NOT NULL AND m.trainerlizenz_gueltig_bis IS NOT NULL
                        AND m.trainerlizenz_gueltig_von <= CURRENT_DATE::text
                        AND m.trainerlizenz_gueltig_bis >= CURRENT_DATE::text)
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
                'last_seen': r['last_seen'],
                'version': r['version'],
                'updated_at': r['updated_at'],
                'hat_passwort': r['hat_passwort'],
            })()
        m_obj = None
        if r['m_id'] is not None:
            m_obj = Mitglied(
                id=r['m_id'], mitgliedsnummer=r['mitgliedsnummer'],
                vorname=r['vorname'], nachname=r['nachname'], geburtsdatum=r['geburtsdatum'],
                strasse=r['strasse'], plz=r['plz'], ort=r['ort'], land=r['land'],
                email=r['m_email'], telefon=r['telefon'],
                eintrittsdatum=r['eintrittsdatum'], austrittsdatum=r['austrittsdatum'],
                status=r['m_status'], art=r['art'], zahlungsart=r['zahlungsart'],
                iban=r['iban'], bic=r['bic'], kontoinhaber=r['kontoinhaber'],
                abgerechnet_bis=r['abgerechnet_bis'], user_id=r['m_user_id'],
                trainerlizenz_gueltig_von=r['trainerlizenz_gueltig_von'],
                trainerlizenz_gueltig_bis=r['trainerlizenz_gueltig_bis'],
                trainerlizenz_nr=r['trainerlizenz_nr'], qualifikation=r['qualifikation'],
                version=r['m_version'], created_at=r['m_created_at'],
                created_by=r['m_created_by'], updated_at=r['m_updated_at'],
                updated_by=r['m_updated_by'],
            )
        if visible is not None and (m_obj is None or m_obj.id not in visible):
            continue  # außerhalb des erlaubten Abteilungs-Scopes
        abteilungen = db.list_mitglied_abteilungen(m_obj.id) if m_obj else []
        funktionen = db.list_mitglied_funktionen(m_obj.id) if m_obj else []
        result.append(_person_row(u_obj, m_obj, abteilungen, funktionen,
                                  last_edited=r['last_edited'],
                                  lizenz_aktuell_gueltig=r['lizenz_aktuell_gueltig']))
    return result


@router.get("/deleted")
def list_deleted_personen(user: CurrentUser, db: DB):
    """Papierkorb: soft-gelöschte Personen (User inkl. Mitglied) sowie gelöschte
    Mitglieder ohne Login-Account. Erfordert Löschberechtigung (Papierkorb-Verwaltung)."""
    _require_delete(user)
    # Gleicher Abteilungs-Scope wie die lebende Liste: Der Papierkorb zeigt
    # dieselben Stammdaten, nur mit Löschvermerk. Die Zuordnungen überleben den
    # Soft-Delete (s. PersonService.delete_person), der Filter greift also auch hier.
    visible = visible_mitglied_ids(user, db, Permission.PERSONEN_DELETE)
    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM (
                SELECT u.id, u.username, u.email, u.role, u.active, u.last_login, u.last_seen, u.version, u.updated_at,
                       u.deleted_at AS del_at, u.deleted_by AS del_by,
                       m.id AS m_id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS m_email,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS telefon,
                       m.eintrittsdatum, m.austrittsdatum, m.status AS m_status, m.art,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       m.user_id AS m_user_id, m.version AS m_version,
                       m.created_at AS m_created_at, m.created_by AS m_created_by,
                       m.updated_at AS m_updated_at, m.updated_by AS m_updated_by
                FROM users u
                LEFT JOIN mitglied m ON m.user_id = u.id
                WHERE u.deleted_at IS NOT NULL
                UNION ALL
                SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                       m.deleted_at, m.deleted_by,
                       m.id, m.mitgliedsnummer, m.vorname, m.nachname, m.geburtsdatum,
                       m.strasse, m.plz, m.ort, m.land,
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='email'   AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       (SELECT k.wert FROM mitglied_kontakt k WHERE k.mitglied_id = m.id AND k.typ='telefon' AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1),
                       m.eintrittsdatum, m.austrittsdatum, m.status, m.art,
                       m.zahlungsart, m.iban, m.bic, m.kontoinhaber, m.abgerechnet_bis,
                       NULL, m.version,
                       m.created_at, m.created_by, m.updated_at, m.updated_by
                FROM mitglied m
                WHERE m.deleted_at IS NOT NULL AND m.user_id IS NULL
            ) p
            ORDER BY p.del_at DESC
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
                'last_seen': r['last_seen'], 'version': r['version'], 'updated_at': r['updated_at'],
            })()
        m_obj = None
        if r['m_id'] is not None:
            m_obj = Mitglied(
                id=r['m_id'], mitgliedsnummer=r['mitgliedsnummer'],
                vorname=r['vorname'], nachname=r['nachname'], geburtsdatum=r['geburtsdatum'],
                strasse=r['strasse'], plz=r['plz'], ort=r['ort'], land=r['land'],
                email=r['m_email'], telefon=r['telefon'],
                eintrittsdatum=r['eintrittsdatum'], austrittsdatum=r['austrittsdatum'],
                status=r['m_status'], art=r['art'], zahlungsart=r['zahlungsart'],
                iban=r['iban'], bic=r['bic'], kontoinhaber=r['kontoinhaber'],
                abgerechnet_bis=r['abgerechnet_bis'], user_id=r['m_user_id'],
                version=r['m_version'], created_at=r['m_created_at'],
                created_by=r['m_created_by'], updated_at=r['m_updated_at'],
                updated_by=r['m_updated_by'],
            )
        if visible is not None and (m_obj is None or m_obj.id not in visible):
            continue  # außerhalb des erlaubten Abteilungs-Scopes
        # Abteilungen/Funktionen im Papierkorb nicht nötig → leere Listen
        person = _person_row(u_obj, m_obj, [], [])
        person['deleted_at'] = r['del_at']
        person['deleted_by'] = r['del_by']
        result.append(person)
    return result


@router.get("/freischaltung")
def list_freischaltung(user: CurrentUser, db: DB):
    """Schlanke Mitgliederliste für die Zugangs-Freischaltung.

    Bewusst NICHT `list_personen`: Freischalter sollen Zugänge verteilen können,
    ohne Bankdaten, Beiträge oder Adressen zu sehen. Geliefert wird nur, was für
    die Entscheidung „wer bekommt einen Login und an welche Adresse" nötig ist –
    Name, Jahrgang (unterscheidet Namensvettern), Abteilungen, Mannschaften
    (#183: der Rollout läuft kaderweise), hinterlegte Mailadressen und der
    Zustand des Kontos samt Login-/Aktivitätszeitpunkt.

    Ausgetretene sind draußen (Ist-Stand heute, vgl. Statistik-Semantik).
    """
    _require_freischalten(user)
    erlaubt = _freischalt_scope(user, db)
    if erlaubt is not None and not erlaubt:
        return []
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id AS mitglied_id, m.vorname, m.nachname, m.mitgliedsnummer,
                   NULLIF(substring(m.geburtsdatum from 1 for 4), '') AS geburtsjahr,
                   u.id AS user_id, u.username, u.email, u.active, u.last_login,
                   u.last_seen,
                   (u.id IS NOT NULL AND u.deleted_at IS NOT NULL) AS zugang_geloescht,
                   (SELECT string_agg(DISTINCT a.name, ', ' ORDER BY a.name)
                      FROM mitglied_abteilung ma
                      JOIN abteilung a ON a.id = ma.abteilung_id
                     WHERE ma.mitglied_id = m.id AND ma.deleted_at IS NULL) AS abteilungen,
                   -- Kader am heutigen Tag (#183): Beim Rollout geht das Freischalten
                   -- mannschaftsweise, die Abteilung allein ist dafür zu grob. DISTINCT,
                   -- weil dieselbe Mannschaft mehrfach am Mitglied hängen kann (zwei
                   -- Rollen, aufeinanderfolgende Zeiträume).
                   (SELECT json_agg(k ORDER BY k.name)
                      FROM (SELECT DISTINCT t.id, t.name, ta.name AS abteilung
                              FROM mitglied_mannschaft mm
                              JOIN mannschaft t ON t.id = mm.mannschaft_id
                                               AND t.deleted_at IS NULL
                              LEFT JOIN abteilung ta ON ta.id = t.abteilung_id
                             WHERE mm.mitglied_id = m.id AND mm.deleted_at IS NULL
                               AND mm.von <= CURRENT_DATE::text
                               AND (mm.bis IS NULL
                                    OR mm.bis >= CURRENT_DATE::text)) k) AS mannschaften,
                   (SELECT json_agg(json_build_object(
                               'wert', k.wert,
                               'primaer', k.ist_primaer,
                               'belegt_von', (SELECT u2.username FROM users u2
                                               WHERE lower(u2.email) = lower(k.wert)
                                                 AND u2.deleted_at IS NULL
                                                 AND (m.user_id IS NULL OR u2.id <> m.user_id)
                                               LIMIT 1))
                             ORDER BY k.ist_primaer DESC, k.id)
                      FROM mitglied_kontakt k
                     WHERE k.mitglied_id = m.id AND k.typ = 'email'
                       AND k.deleted_at IS NULL AND COALESCE(k.wert, '') <> '') AS mails,
                   -- Versandstand der letzten Einladung direkt vom Konto (v97).
                   -- Vorher stand hier ein max() über das Zugriffsprotokoll – das
                   -- aber den *Handelnden* in user_id führt, nicht den Eingeladenen,
                   -- und deshalb praktisch nie etwas fand.
                   u.einladung_zuletzt, u.einladung_status
              FROM mitglied m
              LEFT JOIN users u ON u.id = m.user_id
             WHERE m.deleted_at IS NULL
               AND (safe_to_date(m.austrittsdatum) IS NULL
                    OR safe_to_date(m.austrittsdatum) >= CURRENT_DATE)
             ORDER BY m.nachname, m.vorname
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    ergebnis = []
    for r in rows:
        if erlaubt is not None and r['mitglied_id'] not in erlaubt:
            continue
        r['mails'] = r['mails'] or []
        r['mannschaften'] = r['mannschaften'] or []
        r['einladung_zuletzt'] = _ts_iso(r['einladung_zuletzt'])
        r['last_login'] = _ts_iso(r['last_login'])
        r['last_seen'] = _ts_iso(r['last_seen'])
        ergebnis.append(r)
    return ergebnis


@router.post("/mitglied/{mitglied_id}/zugang", status_code=status.HTTP_201_CREATED)
def zugang_freischalten(mitglied_id: int, data: ZugangFreischalten, request: Request,
                        user: CurrentUser, db: DB):
    """Login für ein bestehendes Mitglied freischalten (Recht personen.freischalten).

    Der Account entsteht immer als aktives Mitglied ohne Passwort; die Anmeldung
    läuft über die Willkommens-Mail (Magic-Link). Eine noch unbekannte Adresse wird
    dem Mitglied als zusätzlicher E-Mail-Kontakt hinzugefügt – das ist die einzige
    Änderung an Mitgliedsdaten, die dieses Recht erlaubt, und sie nimmt nichts weg.
    """
    _require_freischalten(user)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    _require_freischalt_zugriff(user, db, mitglied_id)
    if m.user_id is not None:
        raise HTTPException(status_code=409, detail="Dieses Mitglied hat bereits einen Zugang")

    # Aufbau prüfen, bevor daraus ein Konto entsteht: Ein Vertipper legte bisher
    # klaglos einen Zugang an, an den nie eine Mail gehen kann – gemerkt hätte man
    # das erst, wenn sich jemand wundert, warum nichts ankommt.
    email = mailadresse_or_422(data.email, pflicht=True)
    # Eine Adresse trägt genau ein Konto (uix_users_email_active). Den Fall vorher
    # abfangen, damit statt eines rohen DB-Fehlers klar wird, wem sie schon gehört –
    # bei Familienadressen entscheiden die Beteiligten dann selbst, wer den Zugang nutzt.
    # Case-insensitiv geprüft (der Unique-Index ist es nicht), sonst entstünden über
    # unterschiedliche Schreibweisen doch zwei Konten auf derselben Adresse.
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT username FROM users WHERE lower(email) = lower(%s) AND deleted_at IS NULL",
            (email,),
        )
        belegt = cur.fetchone()
    if belegt is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Diese E-Mail-Adresse gehört bereits zum Zugang von „{belegt['username']}“. "
                   f"Pro Adresse ist ein Zugang möglich.",
        )

    service = PersonService(db)
    try:
        u = service.create_user_only(
            username=service._generate_username(m.vorname, m.nachname),
            email=email,
            role='mitglied',
            active=True,
            created_by=user.username,
            password=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    m.user_id = u.id
    db.update_mitglied(m, updated_by=user.username)

    # Die Login-Adresse kommt als ZUSÄTZLICHER Kontakt dazu – bewusst nicht über
    # set_mitglied_primaer_kontakt: das überschreibt eine vorhandene Primäradresse
    # in place, und damit wäre z. B. die Familienadresse aus der Mitgliederpflege
    # weg. Ist noch gar keine Mailadresse hinterlegt, wird die neue automatisch zur
    # primären (Invariante in MitgliedKontaktRepository.create).
    bekannt = any(
        k.typ == 'email' and (k.wert or '').strip().lower() == email.lower()
        for k in db.list_mitglied_kontakte(m.id)
    )
    if not bekannt:
        db.create_mitglied_kontakt(m.id, 'email', email, 'Login', False, user.username)

    _log_zugang(db, request, "zugang_freigeschaltet", user,
                detail=f"{m.vorname} {m.nachname} (Mitglied {mitglied_id}) → {u.username} <{email}>")

    m = db.get_mitglied(mitglied_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    funktionen = db.list_mitglied_funktionen(m.id)
    return _person_row(u, m, abteilungen, funktionen)


@router.post("/mitglied/{mitglied_id}/zugang/einladung")
def zugang_einladung_senden(mitglied_id: int, request: Request, user: CurrentUser, db: DB):
    """Willkommens-/Anmelde-Mail erneut senden (neuer Magic-Link, 7 Tage gültig).

    Wird häufiger gebraucht als gedacht: Zugänge werden einzeln verteilt, und die
    erste Mail ist beim Nachfragen meist nicht mehr auffindbar. Selbst anfordern
    könnte der Betroffene sie zwar auf der Anmeldeseite, aber nicht jeder findet dort hin.
    """
    _require_freischalten(user)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    _require_freischalt_zugriff(user, db, mitglied_id)
    if m.user_id is None:
        raise HTTPException(status_code=404, detail="Dieses Mitglied hat noch keinen Zugang")
    ziel = db.get_user_by_id(m.user_id)
    if ziel is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden")
    if not ziel.active:
        raise HTTPException(status_code=409, detail="Der Zugang ist deaktiviert")
    if not ziel.email:
        # Konto ohne hinterlegte Adresse – dann gibt es nichts zu verschicken, und
        # „Versand fehlgeschlagen" wäre die falsche Auskunft.
        raise HTTPException(status_code=409,
                            detail="Für diesen Zugang ist keine E-Mail hinterlegt")

    # Erfolg wie Misserfolg werden protokolliert und am Konto vermerkt (im
    # UserService) – die Zugänge-Liste zeigt daran, ob die letzte Mail rausging.
    versendet = UserService(db).send_magic_link(ziel.email)
    _log_zugang(db, request, "zugang_einladung" if versendet else "zugang_einladung_fehler",
                user,
                detail=f"{m.vorname} {m.nachname} (Mitglied {mitglied_id}) → "
                       f"{ziel.username} <{ziel.email}>")
    if not versendet:
        raise HTTPException(status_code=502, detail="E-Mail-Versand fehlgeschlagen")
    return {"ok": True}


@router.put("/mitglied/{mitglied_id}/zugang/mailadresse")
def zugang_mailadresse_aendern(mitglied_id: int, data: ZugangMailadresse, request: Request,
                               user: CurrentUser, db: DB):
    """Login-Adresse eines noch nie benutzten Zugangs korrigieren – und neu einladen.

    Der Normalfall nach dem Freischalten: Es kommt nichts an, weil die Adresse einen
    Vertipper hat oder gar nicht mehr gelesen wird. Ohne diesen Weg müsste der
    Freischalter in die Benutzerverwaltung – für die er kein Recht hat.

    Bewusst eng, denn eine fremde Login-Adresse zu setzen heißt, das Konto zu
    übernehmen:
      * nur solange sich niemand damit angemeldet hat (`last_login IS NULL`) – ab
        der ersten Anmeldung ist das Konto in Benutzung und die Adresse Sache der
        Benutzerverwaltung,
      * nur bei reinen Mitgliedskonten (dieselbe Grenze wie beim Deaktivieren),
      * nicht am eigenen Konto,
      * die Adresse darf keinem anderen Konto gehören.

    Offene Magic-Links des Kontos werden dabei entwertet: Der Link, der an die alte
    Adresse ging, darf danach nicht mehr hineinführen – er landet in derselben
    Antwort wie ein bereits benutzter.
    """
    _require_freischalten(user)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    _require_freischalt_zugriff(user, db, mitglied_id)
    if m.user_id is None:
        raise HTTPException(status_code=404, detail="Dieses Mitglied hat noch keinen Zugang")
    ziel = db.get_user_by_id(m.user_id)
    if ziel is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden")
    if ziel.id == user.id:
        raise HTTPException(status_code=400,
                            detail="Die eigene Login-Adresse ändert man im Profil")
    _nur_mitgliedskonto(user, db, ziel)
    if ziel.last_login is not None:
        raise HTTPException(
            status_code=409,
            detail="Dieser Zugang war bereits in Benutzung – die Login-Adresse ändert "
                   "nur die Benutzerverwaltung.",
        )
    if not ziel.active:
        raise HTTPException(status_code=409, detail="Der Zugang ist deaktiviert")

    email = mailadresse_or_422(data.email, pflicht=True)
    alt = (ziel.email or '').strip()
    # Fremde Adresse? Wie beim Freischalten case-insensitiv geprüft (der Unique-Index
    # ist es nicht) – das eigene Konto dabei ausgenommen, sonst blockierte es sich selbst.
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT username FROM users WHERE lower(email) = lower(%s) "
            "AND deleted_at IS NULL AND id <> %s",
            (email, ziel.id),
        )
        belegt = cur.fetchone()
    if belegt is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Diese E-Mail-Adresse gehört bereits zum Zugang von „{belegt['username']}“. "
                   f"Pro Adresse ist ein Zugang möglich.",
        )

    geaendert = email.lower() != alt.lower()
    if geaendert:
        try:
            UserService(db).update(
                user_id=ziel.id, username=ziel.username, email=email,
                role=ziel.role, active=ziel.active,
                updated_by=user.username, expected_version=ziel.version,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Der Kontakt, den das Freischalten angelegt hat, trägt dieselbe (falsche)
        # Adresse. Ihn zu korrigieren ist Teil desselben Vorgangs – neu anlegen und
        # den Vertipper stehen lassen hieße, Karteileichen zu produzieren. Andere
        # Kontakte des Mitglieds bleiben unangetastet.
        kontakte = db.list_mitglied_kontakte(m.id)
        login_kontakt = next(
            (k for k in kontakte
             if k.typ == 'email' and k.label == 'Login'
             and (k.wert or '').strip().lower() == alt.lower()), None)
        bekannt = any(
            k.typ == 'email' and (k.wert or '').strip().lower() == email.lower()
            for k in kontakte)
        if login_kontakt is not None and not bekannt:
            db.update_mitglied_kontakt(login_kontakt.id, 'email', email, 'Login',
                                       login_kontakt.ist_primaer, user.username,
                                       login_kontakt.version)
        elif not bekannt:
            db.create_mitglied_kontakt(m.id, 'email', email, 'Login', False, user.username)
        db.auth_token_repository.entwerte_offene_tokens(ziel.id, 'magic_link')

    versendet = UserService(db).send_magic_link(email)
    _log_zugang(db, request, "zugang_mailadresse" if geaendert else "zugang_einladung", user,
                detail=f"{m.vorname} {m.nachname} (Mitglied {mitglied_id}) → "
                       f"{ziel.username} <{alt or '–'}> ⇒ <{email}>"
                       f"{'' if versendet else ' · Versand fehlgeschlagen'}")
    if not versendet:
        raise HTTPException(
            status_code=502,
            detail=("Adresse geändert, aber der E-Mail-Versand ist fehlgeschlagen."
                    if geaendert else "E-Mail-Versand fehlgeschlagen"),
        )
    return {"ok": True, "email": email}


@router.post("/mitglied/{mitglied_id}/zugang/deaktivieren")
def zugang_deaktivieren(mitglied_id: int, request: Request, user: CurrentUser, db: DB):
    """Zugang wieder abschalten – Rückfahrkarte für einen Fehlgriff.

    Bewusst eng: nur solange das Konto ein reines Mitgliedskonto ist. Sobald es Admin
    ist oder Rechte über den Sockel hinaus trägt (per Funktion oder Grant), ist es
    Sache der Rechteverwaltung – ein Freischalter soll niemandem die Arbeitsgrundlage
    entziehen können. Gelöscht wird nichts, der Account bleibt inaktiv bestehen.
    """
    _require_freischalten(user)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    _require_freischalt_zugriff(user, db, mitglied_id)
    if m.user_id is None:
        raise HTTPException(status_code=404, detail="Dieses Mitglied hat keinen Zugang")
    ziel = db.get_user_by_id(m.user_id)
    if ziel is None:
        raise HTTPException(status_code=404, detail="Zugang nicht gefunden")
    if ziel.id == user.id:
        raise HTTPException(status_code=400, detail="Eigenen Zugang nicht deaktivierbar")
    _nur_mitgliedskonto(user, db, ziel)
    if not ziel.active:
        return {"ok": True, "already": True}

    try:
        UserService(db).update(
            user_id=ziel.id, username=ziel.username, email=ziel.email,
            role=ziel.role, active=False,
            updated_by=user.username, expected_version=ziel.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _log_zugang(db, request, "zugang_deaktiviert", user,
                detail=f"{m.vorname} {m.nachname} (Mitglied {mitglied_id}) → {ziel.username}")
    return {"ok": True}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_person(data: PersonCreate, user: CurrentUser, db: DB):
    data.iban = iban_or_422(data.iban)
    data.email = mailadresse_or_422(data.email)
    role = authorize_role_assignment(user, data.role)
    service = PersonService(db)
    try:
        if data.vorname and data.nachname:
            # Reine Mitglieds-Anlage (kein Login-Account) – Schreibrecht genügt.
            _require_write(user)
            _require_eintrittsdatum(data)
            mitglied_data = {
                'geburtsdatum': data.geburtsdatum, 'geschlecht': data.geschlecht,
                'strasse': data.strasse, 'plz': data.plz, 'ort': data.ort, 'land': data.land,
                'telefon': data.telefon,
                'eintrittsdatum': data.eintrittsdatum, 'austrittsdatum': data.austrittsdatum,
                'status': data.mitglied_status, 'art': data.art, 'zahlungsart': data.zahlungsart,
                'iban': data.iban, 'bic': data.bic, 'kontoinhaber': data.kontoinhaber,
                'abgerechnet_bis': data.abgerechnet_bis,
                'email': data.email,  # Für _create_initial_kontakte in create_mitglied_ohne_user
            }
            # Immer nur Mitglied erstellen, kein User – auch bei E-Mail-Angabe
            m = service.create_mitglied_ohne_user(
                vorname=data.vorname, nachname=data.nachname,
                created_by=user.username, mitglied_data=mitglied_data,
            )
            abteilungen = db.list_mitglied_abteilungen(m.id)
            funktionen = db.list_mitglied_funktionen(m.id)
            return _person_row(None, m, abteilungen, funktionen)
        else:
            # Login-Account anlegen: nur mit dem Recht, Berechtigungen zu vergeben.
            _require_permissions(user)
            if not data.username:
                raise HTTPException(status_code=400, detail="Username ist pflicht für Benutzer ohne Mitglied-Datensatz")
            u = service.create_user_only(
                username=data.username, email=data.email, role=role,
                active=data.active, created_by=user.username, password=data.password,
            )
            return _person_row(u, None, [], [])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{user_id}/user")
def update_person_user(user_id: int, data: PersonUserUpdate, user: CurrentUser, db: DB):
    # Account-Daten (Benutzername/E-Mail/aktiv) ändern: nur mit dem Recht,
    # Berechtigungen zu vergeben – wie das Anlegen von Login-Accounts.
    _require_permissions(user)
    require_person(user, db, user_id, Permission.PERSONEN_PERMISSIONS)
    target = db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    role = authorize_role_assignment(user, data.role, current_role=target.role)
    data.email = mailadresse_or_422(data.email)
    svc = UserService(db)
    try:
        ok = svc.update(
            user_id=user_id, username=data.username, email=data.email,
            role=role, active=data.active,
            updated_by=user.username, expected_version=data.expected_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    u = db.get_user_by_id(user_id)
    m = db.get_mitglied_by_user_id(user_id)
    # Primären E-Mail-Kontakt des Mitglieds mit der Login-E-Mail synchron halten.
    # Ohne Login-Adresse gibt es nichts zu spiegeln – der bestehende Kontakt des
    # Mitglieds bleibt dann stehen, statt gelöscht zu werden.
    if m and data.email:
        db.set_mitglied_primaer_kontakt(m.id, 'email', data.email, user.username)
        m = db.get_mitglied_by_user_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id) if m else []
    funktionen = db.list_mitglied_funktionen(m.id) if m else []
    return _person_row(u, m, abteilungen, funktionen)


@router.put("/{user_id}/mitglied")
def update_person_mitglied(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    require_person(user, db, user_id, Permission.PERSONEN_WRITE)
    _require_eintrittsdatum(data)
    data.iban = iban_or_422(data.iban)
    m = db.get_mitglied_by_user_id(user_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Kein Mitglied-Datensatz für diesen User")
    _apply_art(db, m, data.art)
    m.vorname = data.vorname
    m.nachname = data.nachname
    m.geburtsdatum = data.geburtsdatum
    m.geschlecht = data.geschlecht
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
    m.trainerlizenz_nr = data.trainerlizenz_nr
    m.qualifikation = data.qualifikation
    m.trainerlizenz_gueltig_bis = data.trainerlizenz_gueltig_bis
    m.trainerlizenz_gueltig_von = data.trainerlizenz_gueltig_von
    m.version = data.expected_version
    ok = db.update_mitglied(m, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    # Primären Telefon-Kontakt nur pflegen, wenn das Feld explizit mitgeschickt wurde –
    # der Stammdaten-Editor sendet keins mehr (Telefonnummern laufen über den Kontakte-Tab);
    # ein fehlendes Feld darf den Primärkontakt nicht löschen.
    if 'telefon' in data.model_fields_set:
        db.set_mitglied_primaer_kontakt(m.id, 'telefon', data.telefon, user.username)
    u = db.get_user_by_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    funktionen = db.list_mitglied_funktionen(m.id)
    return _person_row(u, db.get_mitglied_by_user_id(user_id), abteilungen, funktionen)


@router.post("/{user_id}/mitglied", status_code=status.HTTP_201_CREATED)
def create_mitglied_fuer_user(user_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    """Verknüpft einen bestehenden User nachträglich mit einem Mitglied-Datensatz."""
    _require_write(user)
    # Ein Konto ohne Mitglied hat keine Abteilung – für abteilungsgebundene
    # Bearbeiter ist es unsichtbar und bleibt es auch hier.
    require_person(user, db, user_id, Permission.PERSONEN_WRITE)
    _require_eintrittsdatum(data)
    data.iban = iban_or_422(data.iban)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    if db.get_mitglied_by_user_id(user_id) is not None:
        raise HTTPException(status_code=409, detail="Dieser User hat bereits einen Mitglied-Datensatz")
    m = Mitglied(
        vorname=data.vorname, nachname=data.nachname,
        geburtsdatum=data.geburtsdatum, geschlecht=data.geschlecht,
        strasse=data.strasse, plz=data.plz, ort=data.ort, land=data.land,
        eintrittsdatum=data.eintrittsdatum, austrittsdatum=data.austrittsdatum,
        status=data.status, art=data.art, zahlungsart=data.zahlungsart,
        iban=data.iban, bic=data.bic, kontoinhaber=data.kontoinhaber,
        abgerechnet_bis=data.abgerechnet_bis,
        trainerlizenz_nr=data.trainerlizenz_nr, qualifikation=data.qualifikation,
        trainerlizenz_gueltig_bis=data.trainerlizenz_gueltig_bis,
        trainerlizenz_gueltig_von=data.trainerlizenz_gueltig_von,
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
    funktionen = db.list_mitglied_funktionen(mitglied.id)
    return _person_row(u, mitglied, abteilungen, funktionen)


@router.put("/mitglied/{mitglied_id}")
def update_mitglied_direkt(mitglied_id: int, data: PersonMitgliedUpdate, user: CurrentUser, db: DB):
    """Vereinsdaten eines Mitglieds direkt per mitglied_id bearbeiten.

    Nötig für Mitglieder ohne Login-Account (user_id ist NULL), die nicht über
    den user_id-basierten Endpoint /{user_id}/mitglied erreichbar sind.
    """
    _require_write(user)
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_WRITE)
    _require_eintrittsdatum(data)
    data.iban = iban_or_422(data.iban)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    _apply_art(db, m, data.art)
    m.vorname = data.vorname
    m.nachname = data.nachname
    m.geburtsdatum = data.geburtsdatum
    m.geschlecht = data.geschlecht
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
    m.trainerlizenz_nr = data.trainerlizenz_nr
    m.qualifikation = data.qualifikation
    m.trainerlizenz_gueltig_bis = data.trainerlizenz_gueltig_bis
    m.trainerlizenz_gueltig_von = data.trainerlizenz_gueltig_von
    m.version = data.expected_version
    ok = db.update_mitglied(m, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    # Wie in update_person_mitglied: Telefon-Sync nur bei explizit gesendetem Feld.
    if 'telefon' in data.model_fields_set:
        db.set_mitglied_primaer_kontakt(m.id, 'telefon', data.telefon, user.username)
    u = db.get_user_by_id(m.user_id) if m.user_id else None
    abteilungen = db.list_mitglied_abteilungen(m.id)
    funktionen = db.list_mitglied_funktionen(m.id)
    return _person_row(u, db.get_mitglied(mitglied_id), abteilungen, funktionen)


@router.post("/mitglied/{mitglied_id}/nutzer", status_code=status.HTTP_201_CREATED)
def create_nutzer_fuer_mitglied(mitglied_id: int, data: NutzerFuerMitgliedCreate,
                                user: CurrentUser, db: DB):
    """Legt einen Login-Account für ein bestehendes Mitglied ohne User-Konto an."""
    _require_permissions(user)
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_PERMISSIONS)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    if m.user_id is not None:
        raise HTTPException(status_code=409, detail="Dieses Mitglied hat bereits einen Login-Account")

    role = authorize_role_assignment(user, data.role)
    data.email = mailadresse_or_422(data.email, pflicht=True)
    service = PersonService(db)
    try:
        u = service.create_user_only(
            username=service._generate_username(m.vorname, m.nachname),
            email=data.email,
            role=role,
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
    funktionen = db.list_mitglied_funktionen(m.id)
    return _person_row(u, m, abteilungen, funktionen)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(user_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    require_person(user, db, user_id, Permission.PERSONEN_DELETE)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Eigener Account kann nicht gelöscht werden")
    try:
        PersonService(db).delete_person(user_id, deleted_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/mitglied/{mitglied_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mitglied_ohne_user(mitglied_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_DELETE)
    m = db.get_mitglied(mitglied_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    if m.user_id is not None:
        raise HTTPException(status_code=400, detail="Mitglied hat einen User-Account — bitte über Person löschen")
    PersonService(db).delete_mitglied_ohne_user(mitglied_id, deleted_by=user.username)


@router.post("/{user_id}/restore")
def restore_person(user_id: int, user: CurrentUser, db: DB):
    """Papierkorb: gelöschte Person (User + verknüpftes Mitglied) wiederherstellen."""
    _require_delete(user)
    require_person(user, db, user_id, Permission.PERSONEN_DELETE)
    PersonService(db).restore_person(user_id, restored_by=user.username)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden oder bereits aktiv")
    m = db.get_mitglied_by_user_id(user_id)
    abteilungen = db.list_mitglied_abteilungen(m.id) if m else []
    funktionen = db.list_mitglied_funktionen(m.id) if m else []
    return _person_row(u, m, abteilungen, funktionen)


@router.post("/mitglied/{mitglied_id}/restore")
def restore_mitglied_ohne_user(mitglied_id: int, user: CurrentUser, db: DB):
    """Papierkorb: gelöschtes Mitglied ohne Login-Account wiederherstellen."""
    _require_delete(user)
    require_mitglied(user, db, mitglied_id, Permission.PERSONEN_DELETE)
    ok = PersonService(db).restore_mitglied_ohne_user(mitglied_id, restored_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Mitglied ist nicht gelöscht oder bereits wiederhergestellt")
    m = db.get_mitglied(mitglied_id)
    abteilungen = db.list_mitglied_abteilungen(m.id)
    funktionen = db.list_mitglied_funktionen(m.id)
    return _person_row(None, m, abteilungen, funktionen)


def _mitglied_abteilung_history(db, mitglied_id: int) -> list[dict]:
    """Versionierte Abteilungs-Zuordnungen eines Mitglieds für die Historie."""
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
            (mitglied_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _mitglied_funktion_history(db, mitglied_id: int) -> list[dict]:
    """Versionierte Funktionen eines Mitglieds für die Historie."""
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT mfh.id, mfh.version, mfh.funktion, mfh.abteilung_id,
                   a.name AS abteilung_name, mfh.von, mfh.bis,
                   mfh.updated_at, mfh.updated_by, mfh.deleted_at, mfh.deleted_by
            FROM mitglied_funktion_history mfh
            LEFT JOIN abteilung a ON a.id = mfh.abteilung_id
            WHERE mfh.mitglied_id = %s
            ORDER BY mfh.id, mfh.version ASC
            """,
            (mitglied_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _mitglied_kontakt_history(db, mitglied_id: int) -> list[dict]:
    """Versionierte Kontakte eines Mitglieds für die Historie."""
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, typ, wert, label, ist_primaer,
                   updated_at, updated_by, deleted_at, deleted_by
            FROM mitglied_kontakt_history
            WHERE mitglied_id = %s
            ORDER BY id, version ASC
            """,
            (mitglied_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _mitglied_mannschaft_history(db, mitglied_id: int) -> list[dict]:
    """Versionierte Mannschafts-Zugehörigkeiten eines Mitglieds für die Historie."""
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT mmh.id, mmh.version, mmh.mannschaft_id,
                   COALESCE(m.name, mmh.mannschaft_id::text) AS mannschaft_name,
                   mmh.rolle, mmh.von, mmh.bis,
                   mmh.updated_at, mmh.updated_by, mmh.deleted_at, mmh.deleted_by
            FROM mitglied_mannschaft_history mmh
            LEFT JOIN mannschaft m ON m.id = mmh.mannschaft_id
            WHERE mmh.mitglied_id = %s
            ORDER BY mmh.id, mmh.version ASC
            """,
            (mitglied_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@router.get("/{user_id}/history")
def get_person_history(user_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    require_person(user, db, user_id)
    u = db.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")

    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, username, email, role, active, last_login, last_seen,
                   telegram_id, matrix_id, preferred_contact, password_hash,
                   created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            FROM users_history WHERE id = %s ORDER BY version ASC
            """,
            (user_id,),
        )
        user_history = [dict(r) for r in cur.fetchall()]
        # Passwortänderung je Version ableiten (Hash-Vergleich zur Vorversion). Den Hash
        # selbst NICHT ausliefern – nur das abgeleitete Flag passwort_geaendert.
        prev_hash = None
        for h in user_history:
            cur_hash = h.pop('password_hash', None)
            h['passwort_geaendert'] = prev_hash is not None and cur_hash != prev_hash
            prev_hash = cur_hash

    mitglied = db.get_mitglied_by_user_id(user_id)
    mitglied_history = db.get_mitglied_history(mitglied.id) if mitglied else []
    abteilung_history = _mitglied_abteilung_history(db, mitglied.id) if mitglied else []

    mid = mitglied.id if mitglied else None
    return {
        'user': user_history,
        'mitglied': mitglied_history,
        'abteilungen': abteilung_history,
        'funktionen': _mitglied_funktion_history(db, mid) if mid else [],
        'kontakte': _mitglied_kontakt_history(db, mid) if mid else [],
        'mannschaften': _mitglied_mannschaft_history(db, mid) if mid else [],
    }


@router.get("/mitglied/{mitglied_id}/history")
def get_mitglied_history_direkt(mitglied_id: int, user: CurrentUser, db: DB):
    """Änderungshistorie eines Mitglieds ohne Login-Account (per mitglied_id).

    Liefert dieselbe Struktur wie /{user_id}/history, nur ohne User-Teil –
    so können auch Mitglieder ohne Login-Konto einen Verlauf bekommen.
    """
    _require_read(user)
    require_mitglied(user, db, mitglied_id)
    try:
        m = db.get_mitglied(mitglied_id)
    except KeyError:
        m = None
    if m is None:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    return {
        'user': [],
        'mitglied': db.get_mitglied_history(mitglied_id),
        'abteilungen': _mitglied_abteilung_history(db, mitglied_id),
        'funktionen': _mitglied_funktion_history(db, mitglied_id),
        'kontakte': _mitglied_kontakt_history(db, mitglied_id),
        'mannschaften': _mitglied_mannschaft_history(db, mitglied_id),
    }


# ---------------------------------------------------------------------------
# Eigenes Profil (für Rolle 'mitglied')
# ---------------------------------------------------------------------------

@router.get("/mein-mitglied")
def get_mein_mitglied(user: CurrentUser, db: DB):
    m = db.get_mitglied_by_user_id(user.id)
    return _mitglied_to_dict(m)


@router.put("/mein-mitglied")
def update_mein_mitglied(data: MeinMitgliedUpdate, user: CurrentUser, db: DB):
    data.iban = iban_or_422(data.iban)
    m = db.get_mitglied_by_user_id(user.id)
    if m is None:
        raise HTTPException(status_code=404, detail="Kein Mitglied-Datensatz für diesen Account")
    m.strasse = data.strasse
    m.plz = data.plz
    m.ort = data.ort
    m.land = data.land
    m.iban = data.iban
    m.bic = data.bic
    m.kontoinhaber = data.kontoinhaber
    if data.einzug_erlaubt is not None:
        m.zahlungsart = 'lastschrift' if data.einzug_erlaubt else 'sonstiges'
    # Telefon läuft nicht mehr über dieses Einzelfeld, sondern über die
    # Self-Service-Kontakte (/personen/mein-mitglied/kontakte).
    m.version = data.expected_version
    ok = db.update_mitglied(m, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return _mitglied_to_dict(db.get_mitglied_by_user_id(user.id))
