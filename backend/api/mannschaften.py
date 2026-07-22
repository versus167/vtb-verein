from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.db.mannschaft_repository import Mannschaft
from app.db.mitglied_mannschaft_repository import VALID_ROLLEN
from ..core.deps import CurrentUser, DB
from ..core.validation import zuordnungsbeginn_or_400

router = APIRouter(tags=["mannschaften"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MannschaftCreate(BaseModel):
    abteilung_id: int
    name: str
    saison: Optional[str] = None
    beschreibung: Optional[str] = None


class MannschaftUpdate(MannschaftCreate):
    expected_version: int


class KaderCreate(BaseModel):
    mitglied_id: int
    rolle: str = 'spieler'
    von: Optional[str] = None
    bis: Optional[str] = None


class KaderUpdate(BaseModel):
    rolle: str
    von: Optional[str] = None
    bis: Optional[str] = None
    expected_version: int


class BulkKaderCreate(BaseModel):
    mitglied_ids: list[int]
    rolle: str = 'spieler'
    von: str


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _require_read(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_READ):
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung für Mannschaften")

def _require_write(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_WRITE):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung für Mannschaften")

def _require_delete(user):
    if not user.has_permission(Permission.MANNSCHAFTEN_DELETE):
        raise HTTPException(status_code=403, detail="Keine Löschberechtigung für Mannschaften")

def _validate_rolle(rolle: str):
    if rolle not in VALID_ROLLEN:
        raise HTTPException(status_code=422, detail=f"Ungültige Rolle. Erlaubt: {VALID_ROLLEN}")


# --- Scoped Zugriff für Kader-ÜL/Betreuer (#121) -----------------------------
# Ohne globales mannschaften.read darf man den Bereich trotzdem sehen, wenn man
# in einem Team ÜL/Betreuer ist – dann abteilungsweit lesen und den Kader der
# eigenen Teams pflegen. Team anlegen/bearbeiten/löschen bleibt global.

def _read_scope_abteilungen(user, db):
    """None = darf alle Mannschaften lesen (globales Recht); sonst die Menge der
    Abteilungs-IDs, auf die der Kader-ÜL/Betreuer beschränkt ist."""
    if user.has_permission(Permission.MANNSCHAFTEN_READ):
        return None
    return db.mannschaft_scope_abteilungen(user.id)


def _kader_write_ids(user, db):
    """None = darf jeden Kader pflegen (globales Schreibrecht); sonst die Menge der
    Mannschafts-IDs, in denen der User selbst Kader-ÜL/Betreuer ist."""
    if user.has_permission(Permission.MANNSCHAFTEN_WRITE):
        return None
    return db.mannschaft_kader_verwalten_ids(user.id)


def _require_read_team(user, db, m):
    scope = _read_scope_abteilungen(user, db)
    if scope is not None and m.abteilung_id not in scope:
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Mannschaft")


def _require_kader_write(user, db, mannschaft_id: int):
    ids = _kader_write_ids(user, db)
    if ids is not None and mannschaft_id not in ids:
        raise HTTPException(status_code=403, detail="Keine Berechtigung, diesen Kader zu bearbeiten")


def _alter_jahrgang(geburtsdatum):
    """(alter_in_jahren, geburtsjahr) aus 'YYYY-MM-DD'; (None, None) wenn fehlt/ungültig."""
    if not geburtsdatum:
        return None, None
    try:
        d = date.fromisoformat(str(geburtsdatum)[:10])
    except (ValueError, TypeError):
        return None, None
    today = date.today()
    alter = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return alter, d.year


# ---------------------------------------------------------------------------
# Mannschaften
# ---------------------------------------------------------------------------

@router.get("/mannschaften")
def list_mannschaften(user: CurrentUser, db: DB, abteilung_id: Optional[int] = None):
    scope = _read_scope_abteilungen(user, db)
    if scope is not None and not scope:
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung für Mannschaften")
    kader_ids = _kader_write_ids(user, db)
    out = []
    for m in db.list_mannschaften(abteilung_id):
        if scope is not None and m.abteilung_id not in scope:
            continue
        d = asdict(m)
        d['darf_kader_verwalten'] = kader_ids is None or m.id in kader_ids
        out.append(d)
    return out


def _require_aktive_abteilung(db, abteilung_id: int):
    """Gegenstück zum Lösch-Guard der Abteilung: kein Team in einer gelöschten
    oder fehlenden Abteilung anlegen/dorthin verschieben (get kennt nur aktive
    und wirft sonst KeyError)."""
    try:
        db.get_abteilung(abteilung_id)
    except KeyError:
        raise HTTPException(status_code=422, detail="Abteilung nicht gefunden oder gelöscht")


@router.post("/mannschaften", status_code=status.HTTP_201_CREATED)
def create_mannschaft(data: MannschaftCreate, user: CurrentUser, db: DB):
    _require_write(user)
    if not data.name.strip():
        raise HTTPException(status_code=422, detail="Name ist erforderlich")
    _require_aktive_abteilung(db, data.abteilung_id)
    m = Mannschaft(abteilung_id=data.abteilung_id, name=data.name.strip(),
                   saison=data.saison, beschreibung=data.beschreibung)
    return asdict(db.create_mannschaft(m, created_by=user.username))


@router.put("/mannschaften/{mannschaft_id}")
def update_mannschaft(mannschaft_id: int, data: MannschaftUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    m = db.get_mannschaft(mannschaft_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    if data.abteilung_id != m.abteilung_id:
        _require_aktive_abteilung(db, data.abteilung_id)
    m.abteilung_id = data.abteilung_id
    m.name = data.name.strip()
    m.saison = data.saison
    m.beschreibung = data.beschreibung
    m.version = data.expected_version
    if not db.update_mannschaft(m, updated_by=user.username):
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mannschaft(mannschaft_id))


@router.delete("/mannschaften/{mannschaft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mannschaft(mannschaft_id: int, user: CurrentUser, db: DB):
    _require_delete(user)
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    if db.mannschaft_has_active_mitglieder(mannschaft_id):
        raise HTTPException(status_code=400, detail="Mannschaft hat noch Kader-Mitglieder – bitte zuerst entfernen")
    db.mark_mannschaft_deleted(mannschaft_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Kader (Mitglied <-> Mannschaft)
# ---------------------------------------------------------------------------

@router.get("/mannschaften/{mannschaft_id}/mitglieder")
def list_kader(mannschaft_id: int, user: CurrentUser, db: DB):
    m = db.get_mannschaft(mannschaft_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    _require_read_team(user, db, m)
    return [asdict(z) for z in db.list_mannschaft_kader(mannschaft_id)]


@router.get("/mannschaften/{mannschaft_id}/kandidaten")
def list_kandidaten(mannschaft_id: int, user: CurrentUser, db: DB):
    """Mitglieder der Team-Abteilung, die noch nicht in diesem Team sind (für Sammel-Hinzufügen).
    Inkl. Alter/Jahrgang und aktueller Mannschaften; sortiert: ohne Team zuerst, dann nach Team/Alter."""
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    _require_kader_write(user, db, mannschaft_id)
    out = []
    for r in db.list_mannschaft_kandidaten(mannschaft_id):
        alter, jahrgang = _alter_jahrgang(r.get('geburtsdatum'))
        out.append({
            'id': r['id'], 'vorname': r['vorname'], 'nachname': r['nachname'],
            'geburtsdatum': r.get('geburtsdatum'),
            'alter': alter, 'jahrgang': jahrgang,
            'teams': r.get('teams') or [],
        })
    out.sort(key=lambda c: (
        1 if c['teams'] else 0,
        c['teams'][0].lower() if c['teams'] else '',
        c['alter'] if c['alter'] is not None else 999,
        (c['nachname'] or '').lower(), (c['vorname'] or '').lower(),
    ))
    return out


@router.post("/mannschaften/{mannschaft_id}/mitglieder", status_code=status.HTTP_201_CREATED)
def add_kader(mannschaft_id: int, data: KaderCreate, user: CurrentUser, db: DB):
    _require_kader_write(user, db, mannschaft_id)
    _validate_rolle(data.rolle)
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    zuordnungsbeginn_or_400(db, data.mitglied_id, data.von)
    z = db.create_mitglied_mannschaft(
        data.mitglied_id, mannschaft_id, data.rolle, data.von, data.bis,
        created_by=user.username,
    )
    return asdict(z)


@router.post("/mannschaften/{mannschaft_id}/mitglieder/bulk", status_code=status.HTTP_201_CREATED)
def add_kader_bulk(mannschaft_id: int, data: BulkKaderCreate, user: CurrentUser, db: DB):
    """Mehrere Mitglieder auf einmal zum Kader hinzufügen (gleiche Rolle + Von)."""
    _require_kader_write(user, db, mannschaft_id)
    _validate_rolle(data.rolle)
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(status_code=404, detail="Mannschaft nicht gefunden")
    existing = {z.mitglied_id for z in db.list_mannschaft_kader(mannschaft_id)}
    added, skipped = 0, 0
    for mid in data.mitglied_ids:
        if mid in existing:
            skipped += 1
            continue
        zuordnungsbeginn_or_400(db, mid, data.von)
        db.create_mitglied_mannschaft(mid, mannschaft_id, data.rolle, data.von, None,
                                      created_by=user.username)
        existing.add(mid)
        added += 1
    return {'added': added, 'skipped': skipped}


@router.put("/mannschaften/{mannschaft_id}/mitglieder/{zuordnung_id}")
def update_kader(mannschaft_id: int, zuordnung_id: int, data: KaderUpdate,
                 user: CurrentUser, db: DB):
    _require_kader_write(user, db, mannschaft_id)
    _validate_rolle(data.rolle)
    if not (data.von or '').strip():
        raise HTTPException(status_code=422, detail="Zeitraum-Beginn (Von) ist erforderlich")
    z = db.get_mitglied_mannschaft(zuordnung_id)
    if z is None or z.mannschaft_id != mannschaft_id:
        raise HTTPException(status_code=404, detail="Kader-Zuordnung nicht gefunden")
    zuordnungsbeginn_or_400(db, z.mitglied_id, data.von)
    ok = db.update_mitglied_mannschaft(
        zuordnung_id, data.rolle, data.von, data.bis,
        updated_by=user.username, expected_version=data.expected_version,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return asdict(db.get_mitglied_mannschaft(zuordnung_id))


@router.delete("/mannschaften/{mannschaft_id}/mitglieder/{zuordnung_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_kader(mannschaft_id: int, zuordnung_id: int, user: CurrentUser, db: DB):
    _require_kader_write(user, db, mannschaft_id)
    z = db.get_mitglied_mannschaft(zuordnung_id)
    if z is None or z.mannschaft_id != mannschaft_id:
        raise HTTPException(status_code=404, detail="Kader-Zuordnung nicht gefunden")
    db.mark_mitglied_mannschaft_deleted(zuordnung_id, deleted_by=user.username)


@router.get("/mitglieder/{mitglied_id}/mannschaften")
def list_fuer_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(z) for z in db.list_mitglied_mannschaften(mitglied_id)]
