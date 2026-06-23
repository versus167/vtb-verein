from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.beitrag import Beitragsregel, BeitragEinstellungen
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
    # Index-gleich zu bedingung_funktionen: je Einschluss eine optionale Abteilung (None = vereinsweit)
    bedingung_abteilung_ids: list[Optional[int]] = []
    ausnahme_funktionen: list[str] = []
    # Index-gleich zu ausnahme_funktionen: je Ausnahme eine optionale Abteilung (None = vereinsweit)
    ausnahme_abteilung_ids: list[Optional[int]] = []
    bedingung_alter_min: Optional[int] = None
    bedingung_alter_max: Optional[int] = None
    zahler_typ: str = 'mitglied'
    gegenkonto: Optional[str] = None
    steuerschluessel: Optional[str] = None


class RegelUpdate(RegelCreate):
    expected_version: int


class AbrechnungRequest(BaseModel):
    stichtag: str    # ISO-Datum = "bis"-Grenze; abgerechnet wird bis zu dessen Quartal


class EinstellungenUpdate(BaseModel):
    quartale_rueckschau: int    # Quartale vor dem aktuellen, die mitabgerechnet werden (>= 0)




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
        bedingung_abteilung_ids=data.bedingung_abteilung_ids,
        ausnahme_funktionen=data.ausnahme_funktionen,
        ausnahme_abteilung_ids=data.ausnahme_abteilung_ids,
        bedingung_alter_min=data.bedingung_alter_min,
        bedingung_alter_max=data.bedingung_alter_max,
        zahler_typ=data.zahler_typ,
        gegenkonto=(data.gegenkonto or None),
        steuerschluessel=(data.steuerschluessel or None),
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
    r.bedingung_abteilung_ids = data.bedingung_abteilung_ids
    r.ausnahme_funktionen = data.ausnahme_funktionen
    r.ausnahme_abteilung_ids = data.ausnahme_abteilung_ids
    r.bedingung_alter_min = data.bedingung_alter_min
    r.bedingung_alter_max = data.bedingung_alter_max
    r.zahler_typ = data.zahler_typ
    r.gegenkonto = (data.gegenkonto or None)
    r.steuerschluessel = (data.steuerschluessel or None)
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

@router.get("/einstellungen")
def get_einstellungen(user: CurrentUser, db: DB):
    _require_read(user)
    e = db.beitrag_einstellungen.get()
    return {'quartale_rueckschau': e.quartale_rueckschau, 'version': e.version}


@router.put("/einstellungen")
def update_einstellungen(data: EinstellungenUpdate, user: CurrentUser, db: DB):
    _require_write(user)
    if data.quartale_rueckschau < 0:
        raise HTTPException(status_code=422, detail="Quartale-Rückschau darf nicht negativ sein")
    e = db.beitrag_einstellungen.update(
        BeitragEinstellungen(quartale_rueckschau=data.quartale_rueckschau),
        updated_by=user.username,
    )
    return {'quartale_rueckschau': e.quartale_rueckschau, 'version': e.version}


@router.post("/vorschau")
def vorschau(data: AbrechnungRequest, user: CurrentUser, db: DB):
    _require_read(user)
    rueckschau = db.beitrag_einstellungen.get().quartale_rueckschau
    positionen = BeitragsService(db).vorschau_aufholen(data.stichtag, rueckschau)
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
    rueckschau = db.beitrag_einstellungen.get().quartale_rueckschau
    ergebnis = BeitragsService(db).abrechnen(
        data.stichtag, erstellt_von=user.username, quartale_rueckschau=rueckschau)
    return {
        'zeitraum': ergebnis.zeitraum,
        'angelegt': ergebnis.angelegt,
        'uebersprungen': ergebnis.uebersprungen,
        'zeitraeume': ergebnis.zeitraeume,
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


@router.get("/sollstellungen/papierkorb")
def list_sollstellungen_papierkorb(user: CurrentUser, db: DB):
    """Papierkorb: gelöschte Sollstellungen (vereinsweit)."""
    _require_read(user)
    return [_soll_dict(s) for s in db.sollstellungen.list_deleted()]


@router.get("/sollstellungen/papierkorb/mitglied/{mitglied_id}")
def list_sollstellungen_papierkorb_mitglied(mitglied_id: int, user: CurrentUser, db: DB):
    _require_read(user)
    return [_soll_dict(s) for s in db.sollstellungen.list_deleted_by_mitglied(mitglied_id)]


@router.patch("/sollstellungen/{soll_id}")
def storniere_sollstellung(soll_id: int, user: CurrentUser, db: DB):
    """Storniert eine Sollstellung. Sie bleibt bestehen und wird bei einer erneuten
    Abrechnung nicht neu erzeugt. Eine bereits an die Fibu übergebene Sollstellung
    fließt nach dem Storno als Gegenbuchung in den nächsten Export.
    Zahlung/Ausgleich kennt die VTB-App nicht – das passiert in der Fibu."""
    _require_abrechnen(user)
    ok = db.sollstellungen.mark_storniert(soll_id, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Sollstellung nicht gefunden oder bereits abgeschlossen")
    return {'ok': True}


@router.delete("/sollstellungen/{soll_id}")
def delete_sollstellung(soll_id: int, user: CurrentUser, db: DB):
    """Soft-Delete: anders als Storno wird die Sollstellung bei einer erneuten
    Abrechnung wieder neu angelegt. Nur offene/stornierte und noch nicht an die
    Fibu übergebene; bezahlte und bereits exportierte bleiben gesperrt."""
    _require_abrechnen(user)
    ok = db.sollstellungen.soft_delete(soll_id, deleted_by=user.username)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Sollstellung nicht löschbar: bereits an die Fibu übergeben "
                   "(Rücknahme nur per Storno → Gegenbuchung) oder bezahlt.",
        )
    return {'ok': True}


@router.post("/sollstellungen/{soll_id}/restore")
def restore_sollstellung(soll_id: int, user: CurrentUser, db: DB):
    """Sollstellung aus dem Papierkorb wiederherstellen. Verweigert, wenn für
    (Mitglied, Regel, Zeitraum) zwischenzeitlich wieder eine aktive Sollstellung
    besteht (etwa durch erneute Abrechnung)."""
    _require_abrechnen(user)
    ok = db.sollstellungen.restore(soll_id, restored_by=user.username)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Wiederherstellen nicht möglich (nicht im Papierkorb oder es besteht bereits eine aktive Sollstellung für diesen Zeitraum)",
        )
    return {'ok': True}


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
        'bedingung_abteilung_ids': r.bedingung_abteilung_ids,
        'ausnahme_funktionen': r.ausnahme_funktionen,
        'ausnahme_abteilung_ids': r.ausnahme_abteilung_ids,
        'bedingung_alter_min': r.bedingung_alter_min,
        'bedingung_alter_max': r.bedingung_alter_max,
        'zahler_typ': r.zahler_typ,
        'gegenkonto': r.gegenkonto,
        'steuerschluessel': r.steuerschluessel,
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
        'exportiert_in_export_id': s.exportiert_in_export_id,
        'storno_exportiert_in_export_id': s.storno_exportiert_in_export_id,
        'version': s.version,
    }
