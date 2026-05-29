"""
Kassenbuch API – Kassen, Buchungen, Exporte und Berechtigungen.

Berechtigungsmodell:
  - Kassen anlegen/bearbeiten/löschen: nur Admin (role == 'admin')
  - Buchungen lesen/schreiben: kassenspezifisch via kasse_berechtigungen
  - Berechtigungen verwalten: nur Admin
"""

from dataclasses import asdict
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, field_validator
from typing import Optional

from backend.core.deps import CurrentUser, DB
from app.models.kasse import Kasse, Kassenbuchung
from app.services.kassenbuch_service import (
    BuchungGesperrtError,
    NegativerBestandError,
    KeinLesezugriffError,
    KeinSchreibzugriffError,
    KeinExportrechtError,
    DatumAusserhalbBereichError,
)
from app.services.anhang_service import DateitypNichtErlaubtError, DateiZuGrossError

router = APIRouter(prefix="/kassen", tags=["kassenbuch"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class KasseWrite(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    anfangsbestand_cent: int = 0
    abteilung_id: Optional[int] = None


class KasseUpdate(KasseWrite):
    expected_version: int


class BuchungWrite(BaseModel):
    buchungsdatum: str          # YYYY-MM-DD
    buchungstext: str
    kategorie: str = ''
    einnahme_cent: int = 0
    ausgabe_cent: int = 0
    notiz: Optional[str] = None

    @field_validator("buchungsdatum")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Datum muss im Format YYYY-MM-DD sein.")
        return v

    @field_validator("einnahme_cent", "ausgabe_cent")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Betrag darf nicht negativ sein.")
        return v


class BuchungUpdate(BuchungWrite):
    expected_version: int


class ExportRequest(BaseModel):
    bis_datum: str              # YYYY-MM-DD – alle unexoportierten Buchungen bis einschl. dieses Datums


class BerechtigungWrite(BaseModel):
    darf_lesen: bool = False
    darf_schreiben: bool = False
    darf_exportieren: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin(user) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen diese Aktion ausführen.")


def _kassenbuch_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeinLesezugriffError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeinSchreibzugriffError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeinExportrechtError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, BuchungGesperrtError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, NegativerBestandError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, DatumAusserhalbBereichError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail="Interner Fehler.")


# ---------------------------------------------------------------------------
# Kassen-Verwaltung (Admin)
# ---------------------------------------------------------------------------

@router.get("/")
def list_kassen(user: CurrentUser, db: DB):
    """Alle Kassen, auf die der User Zugriff hat. Admins sehen alle."""
    from app.models.kasse import Kasse
    kassen = db.kassenbuch.get_kassen_fuer_user(user.id, is_admin=(user.role == "admin"))
    result = []
    for k in kassen:
        d = asdict(k)
        d["bestand_cent"] = db.kassen.get_bestand_cent(k.id)
        result.append(d)
    return result


@router.post("/", status_code=201)
def create_kasse(data: KasseWrite, user: CurrentUser, db: DB):
    _require_admin(user)
    kasse = Kasse(
        name=data.name,
        beschreibung=data.beschreibung,
        anfangsbestand_cent=data.anfangsbestand_cent,
        abteilung_id=data.abteilung_id,
    )
    created = db.kassenbuch.create_kasse(kasse, created_by=user.username)
    return asdict(created)


@router.put("/{kasse_id}")
def update_kasse(kasse_id: int, data: KasseUpdate, user: CurrentUser, db: DB):
    _require_admin(user)
    try:
        kasse = db.kassen.get_kasse(kasse_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Kasse {kasse_id} nicht gefunden.")
    kasse.name = data.name
    kasse.beschreibung = data.beschreibung
    kasse.anfangsbestand_cent = data.anfangsbestand_cent
    kasse.abteilung_id = data.abteilung_id
    kasse.version = data.expected_version
    ok = db.kassenbuch.update_kasse(kasse, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return asdict(db.kassen.get_kasse(kasse_id))


@router.delete("/{kasse_id}", status_code=204)
def delete_kasse(kasse_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    try:
        db.kassenbuch.delete_kasse(kasse_id, deleted_by=user.username)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Kasse {kasse_id} nicht gefunden.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Buchungen
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/buchungen")
def list_buchungen(
    kasse_id: int,
    user: CurrentUser,
    db: DB,
    von: Optional[str] = None,
    bis: Optional[str] = None,
    storniert: bool = False,
):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        buchungen = db.kassenbuch._buchung.list_kassenbuchungen(
            kasse_id,
            von_datum=von,
            bis_datum=bis,
            include_storniert=storniert,
        )
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [asdict(b) for b in buchungen]


@router.get("/{kasse_id}/bestand")
def get_bestand(kasse_id: int, user: CurrentUser, db: DB, bis: Optional[str] = None):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        if bis:
            bestand = db.kassen.get_bestand_zum_datum_cent(kasse_id, bis)
        else:
            bestand = db.kassen.get_bestand_cent(kasse_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"kasse_id": kasse_id, "bestand_cent": bestand}


@router.post("/{kasse_id}/buchungen", status_code=201)
def create_buchung(kasse_id: int, data: BuchungWrite, user: CurrentUser, db: DB):
    buchung = Kassenbuchung(
        kasse_id=kasse_id,
        buchungsdatum=data.buchungsdatum,
        buchungstext=data.buchungstext,
        kategorie=data.kategorie,
        einnahme_cent=data.einnahme_cent,
        ausgabe_cent=data.ausgabe_cent,
        notiz=data.notiz,
    )
    try:
        created = db.kassenbuch.create_buchung(
            buchung, created_by=user.username,
            user_id=user.id, is_admin=(user.role == "admin"),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)
    return asdict(created)


@router.put("/{kasse_id}/buchungen/{buchung_id}")
def update_buchung(kasse_id: int, buchung_id: int, data: BuchungUpdate, user: CurrentUser, db: DB):
    try:
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")

    buchung.buchungsdatum = data.buchungsdatum
    buchung.buchungstext = data.buchungstext
    buchung.kategorie = data.kategorie
    buchung.einnahme_cent = data.einnahme_cent
    buchung.ausgabe_cent = data.ausgabe_cent
    buchung.notiz = data.notiz
    buchung.version = data.expected_version

    try:
        ok = db.kassenbuch.update_buchung(
            buchung, updated_by=user.username,
            user_id=user.id, is_admin=(user.role == "admin"),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)

    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return asdict(db.kassenbuch._buchung.get_kassenbuchung(buchung_id))


@router.delete("/{kasse_id}/buchungen/{buchung_id}", status_code=204)
def storniere_buchung(kasse_id: int, buchung_id: int, user: CurrentUser, db: DB):
    try:
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")
    try:
        db.kassenbuch.storniere_buchung(
            buchung_id, deleted_by=user.username,
            user_id=user.id, is_admin=(user.role == "admin"),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)


@router.get("/{kasse_id}/datum-bereich")
def get_datum_bereich(kasse_id: int, user: CurrentUser, db: DB):
    """Gibt den erlaubten Datumsbereich für neue Buchungen zurück."""
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        min_datum, max_datum = db.kassenbuch.get_datum_bereich(kasse_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"min_datum": min_datum, "max_datum": max_datum}


# ---------------------------------------------------------------------------
# CSV-Export
# ---------------------------------------------------------------------------

@router.post("/{kasse_id}/exporte")
def create_export(kasse_id: int, data: ExportRequest, user: CurrentUser, db: DB):
    """Exportiert nicht-exportierte Buchungen bis bis_datum als CSV.

    Sperrt die Buchungen danach. Gibt Export-Metadaten + CSV als Download zurück.
    """
    try:
        dateiname, csv_bytes = db.kassenbuch.exportiere_csv(
            kasse_id,
            bis_datum=data.bis_datum,
            exported_by=user.username,
            user_id=user.id,
            is_admin=(user.role == "admin"),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


@router.get("/{kasse_id}/exporte")
def list_exporte(kasse_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        exporte = db.kassenbuch._export.list_exporte(kasse_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [asdict(e) for e in exporte]


@router.get("/{kasse_id}/exporte/{export_id}/download")
def redownload_export(kasse_id: int, export_id: int, user: CurrentUser, db: DB):
    """Lädt einen bereits abgeschlossenen Export erneut herunter."""
    try:
        dateiname, csv_bytes = db.kassenbuch.reexportiere_csv(
            export_id,
            user_id=user.id,
            is_admin=(user.role == "admin"),
        )
    except KeinExportrechtError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


# ---------------------------------------------------------------------------
# Berechtigungen (Admin)
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/berechtigungen")
def list_berechtigungen(kasse_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    berechtigungen = db.kasse_berechtigungen.get_berechtigungen_fuer_kasse(kasse_id)
    # user_id → username anreichern für die UI
    result = []
    for b in berechtigungen:
        u = db.get_user_by_id(b.user_id)
        result.append({
            "id": b.id,
            "kasse_id": b.kasse_id,
            "user_id": b.user_id,
            "username": u.username if u else f"User {b.user_id}",
            "darf_lesen": b.darf_lesen,
            "darf_schreiben": b.darf_schreiben,
            "darf_exportieren": b.darf_exportieren,
            "version": b.version,
        })
    return result


@router.put("/{kasse_id}/berechtigungen/{user_id}", status_code=200)
def set_berechtigung(kasse_id: int, user_id: int, data: BerechtigungWrite, user: CurrentUser, db: DB):
    _require_admin(user)
    b = db.kasse_berechtigungen.set_berechtigung(
        kasse_id=kasse_id,
        user_id=user_id,
        darf_lesen=data.darf_lesen,
        darf_schreiben=data.darf_schreiben,
        darf_exportieren=data.darf_exportieren,
        actor=user.username,
    )
    u = db.get_user_by_id(user_id)
    return {
        "kasse_id": b.kasse_id,
        "user_id": b.user_id,
        "username": u.username if u else f"User {user_id}",
        "darf_lesen": b.darf_lesen,
        "darf_schreiben": b.darf_schreiben,
        "darf_exportieren": b.darf_exportieren,
        "version": b.version,
    }


@router.delete("/{kasse_id}/berechtigungen/{user_id}", status_code=204)
def revoke_berechtigung(kasse_id: int, user_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    ok = db.kasse_berechtigungen.revoke_berechtigung(kasse_id, user_id, actor=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Berechtigung nicht gefunden.")


# ---------------------------------------------------------------------------
# Anhänge (Belegfotos)
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/buchungen/{buchung_id}/anhaenge")
def list_anhaenge(kasse_id: int, buchung_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")
    return [asdict(a) for a in db.kassenbuch.get_anhaenge(buchung_id)]


@router.post("/{kasse_id}/buchungen/{buchung_id}/anhaenge", status_code=201)
async def upload_anhang(
    kasse_id: int,
    buchung_id: int,
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
):
    try:
        db.kassenbuch._pruefe_schreibzugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeinSchreibzugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")

    inhalt = await file.read()
    try:
        anhang = db.kassenbuch.add_anhang(
            buchung_id=buchung_id,
            original_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            inhalt=inhalt,
            hochgeladen_von=user.id,
        )
    except DateitypNichtErlaubtError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DateiZuGrossError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except IOError as exc:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {exc}")
    return asdict(anhang)


@router.delete("/{kasse_id}/buchungen/{buchung_id}/anhaenge/{anhang_id}", status_code=204)
def delete_anhang(kasse_id: int, buchung_id: int, anhang_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_schreibzugriff(kasse_id, user.id, is_admin=(user.role == "admin"))
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeinSchreibzugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")
    ok = db.kassenbuch.mark_anhang_deleted(anhang_id, deleted_by=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Anhang {anhang_id} nicht gefunden.")
