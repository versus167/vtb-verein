from dataclasses import asdict
from typing import Optional
import io

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.gebuehr import Gebuehr
from app.models.permission import Permission
from app.services.gebuehren_service import GebuehrenService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/gebuehren", tags=["gebuehren"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GebuehrCreate(BaseModel):
    name: str
    abteilung_id: Optional[int] = None
    betrag: float
    anlass: str = 'aufnahme'
    gueltig_ab: str
    gueltig_bis: Optional[str] = None
    zahler_typ: str = 'mitglied'


class GebuehrUpdate(GebuehrCreate):
    expected_version: int


class ForderungCreate(BaseModel):
    mitglied_id: int
    gebuehr_id: int
    datum: str


class ForderungStatusUpdate(BaseModel):
    bezahlt_am: Optional[str] = None   # ISO-Datum -> bezahlt; None -> stornieren


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _require_read(user):
    if not user.has_permission(Permission.GEBUEHREN_READ):
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung für Gebühren")

def _require_write(user):
    if not user.has_permission(Permission.GEBUEHREN_WRITE):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung für Gebühren")

def _require_abrechnen(user):
    if not user.has_permission(Permission.GEBUEHREN_ABRECHNEN):
        raise HTTPException(status_code=403, detail="Keine Berechtigung für Gebühren-Einzug")


def _gebuehr_dict(g: Gebuehr) -> dict:
    return {
        'id': g.id, 'name': g.name,
        'abteilung_id': g.abteilung_id, 'abteilung_name': g.abteilung_name,
        'betrag': g.betrag, 'anlass': g.anlass,
        'gueltig_ab': g.gueltig_ab, 'gueltig_bis': g.gueltig_bis,
        'zahler_typ': g.zahler_typ,
        'version': g.version,
    }


# ---------------------------------------------------------------------------
# Gebühren-Katalog
# ---------------------------------------------------------------------------

@router.get("")
def list_gebuehren(user: CurrentUser, db: DB):
    _require_read(user)
    return [_gebuehr_dict(g) for g in db.gebuehren.list_all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_gebuehr(data: GebuehrCreate, user: CurrentUser, db: DB):
    _require_write(user)
    if not data.name.strip():
        raise HTTPException(status_code=422, detail="Name ist erforderlich")
    if not (data.gueltig_ab or '').strip():
        raise HTTPException(status_code=422, detail="Gültig ab ist erforderlich")
    g = Gebuehr(name=data.name.strip(), abteilung_id=data.abteilung_id, betrag=data.betrag,
                anlass=data.anlass, gueltig_ab=data.gueltig_ab, gueltig_bis=data.gueltig_bis,
                zahler_typ=data.zahler_typ)
    return _gebuehr_dict(db.gebuehren.create(g, created_by=user.username))


@router.put("/{gebuehr_id}")
def update_gebuehr(gebuehr_id: int, data: GebuehrUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    g = db.gebuehren.get(gebuehr_id)
    if g is None:
        raise HTTPException(status_code=404, detail="Gebühr nicht gefunden")
    g.name = data.name.strip()
    g.abteilung_id = data.abteilung_id
    g.betrag = data.betrag
    g.anlass = data.anlass
    g.gueltig_ab = data.gueltig_ab
    g.gueltig_bis = data.gueltig_bis
    g.zahler_typ = data.zahler_typ
    g.version = data.expected_version
    if not db.gebuehren.update(g, updated_by=user.username):
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return _gebuehr_dict(db.gebuehren.get(gebuehr_id))


@router.delete("/{gebuehr_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gebuehr(gebuehr_id: int, user: CurrentUser, db: DB):
    _require_write(user)
    db.gebuehren.mark_deleted(gebuehr_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Forderungen
# ---------------------------------------------------------------------------

@router.get("/forderungen")
def list_forderungen(user: CurrentUser, db: DB, status_filter: Optional[str] = None):
    _require_read(user)
    return [asdict(f) for f in db.gebuehr_forderungen.list_all(status_filter)]


@router.get("/forderungen/mitglied/{mitglied_id}")
def list_forderungen_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [asdict(f) for f in db.gebuehr_forderungen.list_for_mitglied(mitglied_id)]


@router.post("/forderungen", status_code=status.HTTP_201_CREATED)
def create_forderung(data: ForderungCreate, user: CurrentUser, db: DB):
    _require_write(user)
    try:
        db.get_mitglied(data.mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    try:
        forderung = GebuehrenService(db).create_forderung(
            data.mitglied_id, data.gebuehr_id, data.datum, erstellt_von=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return asdict(forderung)


@router.patch("/forderungen/{forderung_id}")
def update_forderung_status(forderung_id: int, data: ForderungStatusUpdate,
                            user: CurrentUser, db: DB):
    _require_abrechnen(user)
    f = db.get_gebuehr_forderung(forderung_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Forderung nicht gefunden")
    if data.bezahlt_am:
        ok = db.gebuehr_forderungen.set_status(forderung_id, 'bezahlt', data.bezahlt_am, user.username)
    else:
        ok = db.gebuehr_forderungen.set_status(forderung_id, 'storniert', None, user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Aktualisierung fehlgeschlagen")
    return asdict(db.get_gebuehr_forderung(forderung_id))


@router.get("/sepa-export")
def sepa_export(user: CurrentUser, db: DB):
    _require_abrechnen(user)
    offen = [f for f in db.gebuehr_forderungen.list_all('offen') if f.zahler_typ == 'mitglied']
    if not offen:
        raise HTTPException(status_code=404, detail="Keine offenen SEPA-Gebühren")
    lines = ["Name;IBAN;Kontoinhaber;Betrag;Datum;Gebuehr"]
    for f in offen:
        lines.append(
            f"{f.mitglied_nachname} {f.mitglied_vorname};"
            f"{f.mitglied_iban or ''};"
            f"{f.mitglied_kontoinhaber or ''};"
            f"{f.betrag_soll:.2f};"
            f"{f.datum};"
            f"{f.gebuehr_name}"
        )
    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sepa_gebuehren.csv"'},
    )
