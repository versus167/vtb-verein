from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import io

from app.models.beitrag import Beitragsregel
from app.models.permission import Permission
from app.services.beitrags_service import BeitragsService
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/beitraege", tags=["beitraege"])


# ---------------------------------------------------------------------------
# Berechtigungs-Helfer
# ---------------------------------------------------------------------------

def _require_read(user):
    if not user.has_permission(Permission.BEITRAEGE_READ):
        raise HTTPException(status_code=403, detail="Keine Leseberechtigung für Beiträge")

def _require_write(user):
    if not user.has_permission(Permission.BEITRAEGE_WRITE):
        raise HTTPException(status_code=403, detail="Keine Schreibberechtigung für Beiträge")

def _require_abrechnen(user):
    if not user.has_permission(Permission.BEITRAEGE_ABRECHNEN):
        raise HTTPException(status_code=403, detail="Keine Berechtigung für Beitragsabrechnung")


# ---------------------------------------------------------------------------
# Pydantic-Schemas
# ---------------------------------------------------------------------------

class RegelCreate(BaseModel):
    name: str
    abteilung_id: Optional[int] = None
    betrag_pro_monat: float
    einzug_turnus: str = 'quartal'
    gueltig_ab: str
    gueltig_bis: Optional[str] = None
    bedingung_abteilung_status: Optional[str] = None
    bedingung_funktionen: list[str] = []
    bedingung_funktion_abteilung_id: Optional[int] = None
    ausnahme_funktionen: list[str] = []
    ausnahme_funktion_abteilung_id: Optional[int] = None
    bedingung_alter_min: Optional[int] = None
    bedingung_alter_max: Optional[int] = None
    zahler_typ: str = 'mitglied'


class RegelUpdate(RegelCreate):
    expected_version: int


class AbrechnungRequest(BaseModel):
    stichtag: str    # ISO-Datum, z.B. "2026-10-01"


class SollstellungStatusUpdate(BaseModel):
    bezahlt_am: Optional[str] = None   # ISO-Datum; None → stornieren


# ---------------------------------------------------------------------------
# Beitragsregeln
# ---------------------------------------------------------------------------

@router.get("/regeln")
def list_regeln(user: CurrentUser, db: DB):
    _require_read(user)
    regeln = db.beitragsregeln.list_all()
    return [_regel_dict(r) for r in regeln]


@router.post("/regeln", status_code=status.HTTP_201_CREATED)
def create_regel(data: RegelCreate, user: CurrentUser, db: DB):
    _require_write(user)
    r = Beitragsregel(
        name=data.name, abteilung_id=data.abteilung_id,
        betrag_pro_monat=data.betrag_pro_monat, einzug_turnus=data.einzug_turnus,
        gueltig_ab=data.gueltig_ab, gueltig_bis=data.gueltig_bis,
        bedingung_abteilung_status=data.bedingung_abteilung_status,
        bedingung_funktionen=data.bedingung_funktionen,
        bedingung_funktion_abteilung_id=data.bedingung_funktion_abteilung_id,
        ausnahme_funktionen=data.ausnahme_funktionen,
        ausnahme_funktion_abteilung_id=data.ausnahme_funktion_abteilung_id,
        bedingung_alter_min=data.bedingung_alter_min,
        bedingung_alter_max=data.bedingung_alter_max,
        zahler_typ=data.zahler_typ,
    )
    created = db.beitragsregeln.create(r, created_by=user.username)
    return _regel_dict(created)


@router.put("/regeln/{regel_id}")
def update_regel(regel_id: int, data: RegelUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    r = db.beitragsregeln.get(regel_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Regel nicht gefunden")
    r.name = data.name
    r.abteilung_id = data.abteilung_id
    r.betrag_pro_monat = data.betrag_pro_monat
    r.einzug_turnus = data.einzug_turnus
    r.gueltig_ab = data.gueltig_ab
    r.gueltig_bis = data.gueltig_bis
    r.bedingung_abteilung_status = data.bedingung_abteilung_status
    r.bedingung_funktionen = data.bedingung_funktionen
    r.bedingung_funktion_abteilung_id = data.bedingung_funktion_abteilung_id
    r.ausnahme_funktionen = data.ausnahme_funktionen
    r.ausnahme_funktion_abteilung_id = data.ausnahme_funktion_abteilung_id
    r.bedingung_alter_min = data.bedingung_alter_min
    r.bedingung_alter_max = data.bedingung_alter_max
    r.zahler_typ = data.zahler_typ
    r.version = data.expected_version
    ok = db.beitragsregeln.update(r, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden")
    return _regel_dict(db.beitragsregeln.get(regel_id))


@router.delete("/regeln/{regel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_regel(regel_id: int, user: CurrentUser, db: DB):
    _require_write(user)
    db.beitragsregeln.mark_deleted(regel_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Abrechnung
# ---------------------------------------------------------------------------

@router.post("/vorschau")
def vorschau(data: AbrechnungRequest, user: CurrentUser, db: DB):
    _require_read(user)
    positionen = BeitragsService(db).vorschau(data.stichtag)
    return [
        {
            'mitglied_id': p.mitglied_id,
            'mitglied_name': f"{p.mitglied_nachname}, {p.mitglied_vorname}",
            'mitglied_iban': p.mitglied_iban,
            'beitragsregel_id': p.beitragsregel_id,
            'beitragsregel_name': p.beitragsregel_name,
            'abteilung_id': p.beitragsregel_abteilung_id,
            'abteilung_name': p.beitragsregel_abteilung_name,
            'mitglied_abteilung_ids': p.mitglied_abteilung_ids,
            'betrag': p.betrag,
            'zahler_typ': p.zahler_typ,
            'zeitraum': p.zeitraum,
            'faelligkeitsdatum': p.faelligkeitsdatum,
            'bereits_vorhanden': p.bereits_vorhanden,
            'anzahl_monate': p.anzahl_monate,
            'monate_im_zeitraum': p.monate_im_zeitraum,
        }
        for p in positionen
    ]


@router.get("/dashboard")
def dashboard(user: CurrentUser, db: DB, stichtag: Optional[str] = None):
    _require_read(user)
    if not stichtag:
        stichtag = date.today().isoformat()
    erg = BeitragsService(db).dashboard(stichtag)
    return {
        'zeitraum': erg.zeitraum,
        'stichtag': erg.stichtag,
        'gesamt_summe': erg.gesamt_summe,
        'gesamt_zahler': erg.gesamt_zahler,
        'gesamt_positionen': erg.gesamt_positionen,
        'gruppen': [
            {
                'abteilung_id': g.abteilung_id,
                'abteilung_name': g.abteilung_name,
                'summe': g.summe,
                'anzahl_zahler': g.anzahl_zahler,
                'anzahl_positionen': g.anzahl_positionen,
            }
            for g in erg.gruppen
        ],
    }


@router.post("/abrechnen", status_code=status.HTTP_201_CREATED)
def abrechnen(data: AbrechnungRequest, user: CurrentUser, db: DB):
    _require_abrechnen(user)
    ergebnis = BeitragsService(db).abrechnen(data.stichtag, erstellt_von=user.username)
    return {
        'zeitraum': ergebnis.zeitraum,
        'angelegt': ergebnis.angelegt,
        'uebersprungen': ergebnis.uebersprungen,
    }


# ---------------------------------------------------------------------------
# Sollstellungen
# ---------------------------------------------------------------------------

@router.get("/sollstellungen")
def list_sollstellungen(zeitraum: str, user: CurrentUser, db: DB):
    _require_read(user)
    sollstellungen = db.sollstellungen.list_by_zeitraum(zeitraum)
    return [_soll_dict(s) for s in sollstellungen]


@router.get("/sollstellungen/zeitraeume")
def list_sollstellung_zeitraeume(user: CurrentUser, db: DB):
    """Vorhandene Zeiträume für das Filter-Dropdown (neueste zuerst)."""
    _require_read(user)
    return db.sollstellungen.list_zeitraeume()


@router.get("/sollstellungen/mitglied/{mitglied_id}")
def list_sollstellungen_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [_soll_dict(s) for s in db.sollstellungen.list_by_mitglied(mitglied_id)]


@router.patch("/sollstellungen/{soll_id}")
def update_sollstellung_status(soll_id: int, data: SollstellungStatusUpdate,
                                user: CurrentUser, db: DB):
    _require_abrechnen(user)
    if data.bezahlt_am:
        ok = db.sollstellungen.mark_bezahlt(soll_id, data.bezahlt_am, updated_by=user.username)
    else:
        ok = db.sollstellungen.mark_storniert(soll_id, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Sollstellung nicht gefunden oder bereits abgeschlossen")
    return {'ok': True}


@router.delete("/sollstellungen/{soll_id}")
def delete_sollstellung(soll_id: int, user: CurrentUser, db: DB):
    """Soft-Delete: anders als Storno wird die Sollstellung bei einer erneuten
    Abrechnung wieder neu angelegt. Nur offene/stornierte; bezahlte bleiben
    vorerst gesperrt (bereits bezahlt)."""
    _require_abrechnen(user)
    ok = db.sollstellungen.soft_delete(soll_id, deleted_by=user.username)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Sollstellung nicht gefunden oder nicht löschbar (nur offene/stornierte – bezahlte werden nicht gelöscht)",
        )
    return {'ok': True}


# ---------------------------------------------------------------------------
# SEPA-Export (einfaches CSV-Format)
# ---------------------------------------------------------------------------

@router.get("/sepa-export/{zeitraum}")
def sepa_export(zeitraum: str, user: CurrentUser, db: DB):
    _require_abrechnen(user)
    sollstellungen = db.sollstellungen.list_offen_fuer_sepa(zeitraum)
    if not sollstellungen:
        raise HTTPException(status_code=404, detail="Keine offenen SEPA-Lastschriften für diesen Zeitraum")

    lines = ["Name;IBAN;Kontoinhaber;Betrag;Zeitraum;Regel"]
    for s in sollstellungen:
        lines.append(
            f"{s.mitglied_nachname} {s.mitglied_vorname};"
            f"{s.mitglied_iban or ''};"
            f"{s.mitglied_kontoinhaber or ''};"
            f"{s.betrag_soll:.2f};"
            f"{s.zeitraum};"
            f"{s.beitragsregel_name}"
        )

    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sepa_{zeitraum}.csv"'},
    )


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _regel_dict(r: Beitragsregel) -> dict:
    return {
        'id': r.id, 'name': r.name,
        'abteilung_id': r.abteilung_id, 'abteilung_name': r.abteilung_name,
        'betrag_pro_monat': r.betrag_pro_monat,
        'betrag_pro_einzug': r.betrag_pro_einzug,
        'einzug_turnus': r.einzug_turnus,
        'gueltig_ab': r.gueltig_ab, 'gueltig_bis': r.gueltig_bis,
        'bedingung_abteilung_status': r.bedingung_abteilung_status,
        'bedingung_funktionen': r.bedingung_funktionen,
        'bedingung_funktion_abteilung_id': r.bedingung_funktion_abteilung_id,
        'ausnahme_funktionen': r.ausnahme_funktionen,
        'ausnahme_funktion_abteilung_id': r.ausnahme_funktion_abteilung_id,
        'bedingung_alter_min': r.bedingung_alter_min,
        'bedingung_alter_max': r.bedingung_alter_max,
        'zahler_typ': r.zahler_typ,
        'version': r.version,
    }


def _soll_dict(s) -> dict:
    return {
        'id': s.id,
        'mitglied_id': s.mitglied_id,
        'mitglied_name': f"{s.mitglied_nachname}, {s.mitglied_vorname}",
        'mitglied_iban': s.mitglied_iban,
        'beitragsregel_id': s.beitragsregel_id,
        'beitragsregel_name': s.beitragsregel_name,
        'zeitraum': s.zeitraum,
        'betrag_soll': s.betrag_soll,
        'faelligkeitsdatum': s.faelligkeitsdatum,
        'status': s.status,
        'bezahlt_am': s.bezahlt_am,
        'zahler_typ': s.zahler_typ,
        'kassenbuchung_id': s.kassenbuchung_id,
        'version': s.version,
    }
