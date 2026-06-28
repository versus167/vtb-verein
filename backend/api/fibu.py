"""API für den Fibu-Delta-Export der Sollstellungen (Format hmd FBASC)."""
import io
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.permission import Permission
from app.models.fibu import FibuEinstellungen, FibuExport, FibuExportPosition
from app.services.fibu_export_service import FibuExportService, FibuExportFehler
from app.services.fibu_formatter import FBASC_DATEINAME
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/fibu", tags=["fibu"])


def _require_export(user):
    if not user.has_permission(Permission.FIBU_EXPORT):
        raise HTTPException(status_code=403, detail="Keine Berechtigung für den Fibu-Export")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EinstellungenUpdate(BaseModel):
    debitor_konto_basis: Optional[int] = None
    default_gegenkonto: Optional[str] = None
    default_steuerschluessel: Optional[str] = None
    verein_kostenstelle: int = 12
    default_kostentraeger: int = 1
    ul_aufwand_konto: Optional[str] = None
    ul_kreditor_konto_basis: Optional[int] = None


# ---------------------------------------------------------------------------
# Serialisierung
# ---------------------------------------------------------------------------

def _einst_dict(e: FibuEinstellungen) -> dict:
    return {
        'debitor_konto_basis': e.debitor_konto_basis,
        'default_gegenkonto': e.default_gegenkonto,
        'default_steuerschluessel': e.default_steuerschluessel,
        'verein_kostenstelle': e.verein_kostenstelle,
        'default_kostentraeger': e.default_kostentraeger,
        'ul_aufwand_konto': e.ul_aufwand_konto,
        'ul_kreditor_konto_basis': e.ul_kreditor_konto_basis,
        'version': e.version,
    }


def _pos_dict(p: FibuExportPosition) -> dict:
    return {
        'art': p.art,
        'quelle_typ': p.quelle_typ,
        'quelle_id': p.quelle_id,
        'mitglied_name': p.mitglied_name,
        'bezeichnung': p.bezeichnung,
        'konto': p.konto,
        'gegenkonto': p.gegenkonto,
        'betrag': p.betrag,
        'soll_haben': p.soll_haben,
        'belegnummer': p.belegnummer,
        'kostenstelle': p.kostenstelle,
        'kostentraeger': p.kostentraeger,
        'belegdatum': p.belegdatum,
        'iban': p.iban,
        'mandatsref': p.mandatsref,
    }


def _export_dict(x: FibuExport) -> dict:
    return {
        'id': x.id,
        'exportiert_am': x.exportiert_am,
        'exportiert_von': x.exportiert_von,
        'dateiname': x.dateiname,
        'format': x.format,
        'anzahl_positionen': x.anzahl_positionen,
        'summe_cent': x.summe_cent,
        'storno_von_export_id': x.storno_von_export_id,
    }


def _datei_response(content: bytes) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{FBASC_DATEINAME}"'},
    )


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------

@router.get("/einstellungen")
def get_einstellungen(user: CurrentUser, db: DB):
    _require_export(user)
    return _einst_dict(db.fibu_einstellungen.get())


@router.put("/einstellungen")
def update_einstellungen(data: EinstellungenUpdate, user: CurrentUser, db: DB):
    _require_export(user)
    e = FibuEinstellungen(
        debitor_konto_basis=data.debitor_konto_basis,
        default_gegenkonto=(data.default_gegenkonto or None),
        default_steuerschluessel=(data.default_steuerschluessel or None),
        verein_kostenstelle=data.verein_kostenstelle,
        default_kostentraeger=data.default_kostentraeger,
        ul_aufwand_konto=(data.ul_aufwand_konto or None),
        ul_kreditor_konto_basis=data.ul_kreditor_konto_basis,
    )
    return _einst_dict(db.fibu_einstellungen.update(e, updated_by=user.username))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/vorschau")
def vorschau(user: CurrentUser, db: DB):
    _require_export(user)
    v = FibuExportService(db).vorschau()
    forderungen = [_pos_dict(p) for p in v['forderungen']]
    gegenbuchungen = [_pos_dict(p) for p in v['gegenbuchungen']]
    # Vorzeichenbehaftete Netto-Summe (Soll +, Haben −) über alle Positionen. Abteilungs-
    # Umbuchungen liegen als S/H-Paar in den Forderungen und heben sich so korrekt auf.
    def _signiert(p):
        return p.betrag if p.soll_haben == 'S' else -p.betrag
    summe = sum(_signiert(p) for p in v['forderungen'] + v['gegenbuchungen'])
    return {
        'forderungen': forderungen,
        'gegenbuchungen': gegenbuchungen,
        'fehler': v['fehler'],
        'anzahl': len(forderungen) + len(gegenbuchungen),
        'summe': round(summe, 2),
    }


@router.post("/export")
def export(user: CurrentUser, db: DB):
    _require_export(user)
    try:
        _, content = FibuExportService(db).exportieren(erstellt_von=user.username)
    except FibuExportFehler as e:
        raise HTTPException(status_code=400, detail={
            'message': "Export nicht möglich – unvollständige Konten-Konfiguration.",
            'fehler': e.fehler,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _datei_response(content)


@router.get("/exporte")
def list_exporte(user: CurrentUser, db: DB):
    _require_export(user)
    return [_export_dict(x) for x in db.fibu_exporte.list_exporte()]


@router.get("/exporte/{export_id}/download")
def download_export(export_id: int, user: CurrentUser, db: DB):
    _require_export(user)
    try:
        db.fibu_exporte.get_export(export_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Export nicht gefunden")
    content = FibuExportService(db).re_download(export_id)
    return _datei_response(content)


@router.post("/exporte/{export_id}/zuruecknehmen")
def zuruecknehmen(export_id: int, user: CurrentUser, db: DB):
    """Un-Export: jüngsten, noch nicht in die Fibu eingelesenen Lauf zurücknehmen."""
    _require_export(user)
    try:
        return FibuExportService(db).zuruecknehmen(export_id, benutzer=user.username)
    except KeyError:
        raise HTTPException(status_code=404, detail="Export nicht gefunden")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/exporte/{export_id}/storno")
def storno_lauf(export_id: int, user: CurrentUser, db: DB):
    """Gegenbuchungs-Lauf für einen bereits eingelesenen Lauf (bucht ihn komplett gegen)."""
    _require_export(user)
    try:
        _, content = FibuExportService(db).stornieren(export_id, benutzer=user.username)
    except KeyError:
        raise HTTPException(status_code=404, detail="Export nicht gefunden")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _datei_response(content)
