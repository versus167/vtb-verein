"""
Rechnungen API – einreichen, freigeben, exportieren.

Berechtigungsmodell (siehe BERECHTIGUNGEN.md):
  - rechnungen.einreichen: eigene Rechnungen anlegen, Belege hochladen, einreichen
  - rechnungen.freigeben:  freigeben/ablehnen – abteilungs-scoped, STRICT geprüft
    (has_permission_for_abteilung); ein Abteilungsleiter sieht und entscheidet nur
    über die Rechnungen seiner Abteilung(en)
  - rechnungen.verwalten:  Geschäftsstelle – alles sehen, Kategorien pflegen,
    exportieren und Vereinsrechnungen (ohne Abteilung) freigeben

Die Routen /kategorien und /export stehen bewusst VOR /{rechnung_id} – sonst
würde der Pfadparameter sie schlucken.
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from backend.core.deps import CurrentUser, DB
from app.models.permission import Permission
from app.models.rechnung import STATUS_FILTER_WERTE
from app.services.anhang_service import DateitypNichtErlaubtError, DateiZuGrossError
from app.services.rechnung_service import (
    BelegFehltError,
    BetragFehltError,
    EmpfaengerFehltError,
    FalscherStatusError,
    KategorieInBenutzungError,
    KeineFreigabeberechtigungError,
    KeinZugriffError,
    RechnungGesperrtError,
)
from app.services.rechnung_export_service import (
    KeineRechnungenError,
    NichtJuengsterLaufError,
)

router = APIRouter(prefix="/rechnungen", tags=["rechnungen"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class RechnungWrite(BaseModel):
    kategorie_id: int
    abteilung_id: Optional[int] = None
    beschreibung: Optional[str] = None
    # Am Entwurf optional, beim Einreichen Pflicht (RechnungService prüft das) –
    # so lässt sich eine Rechnung zwischenspeichern, bevor der Betrag feststeht.
    betrag_cent: Optional[int] = None
    rechnungsdatum: Optional[str] = None
    rechnungsnummer: Optional[str] = None
    empfaenger_typ: Optional[str] = None
    empfaenger_mitglied_id: Optional[int] = None
    empfaenger_name: Optional[str] = None
    empfaenger_iban: Optional[str] = None


class RechnungUpdate(RechnungWrite):
    expected_version: int


class AblehnenWrite(BaseModel):
    grund: Optional[str] = None


class KategorieWrite(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    sachkonto: Optional[str] = None
    kostenstelle: Optional[int] = None
    kostentraeger: Optional[int] = None


class KategorieUpdate(KategorieWrite):
    expected_version: int


# ---------------------------------------------------------------------------
# Fehler-Mapping
# ---------------------------------------------------------------------------

def _fehler_zu_http(exc: Exception) -> HTTPException:
    """Fachliche Fehler auf HTTP-Codes abbilden – an einer Stelle, damit die
    Endpunkte nicht jeder ihre eigene Übersetzung mitbringen."""
    if isinstance(exc, (KeinZugriffError, KeineFreigabeberechtigungError)):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    if isinstance(exc, (FalscherStatusError, RechnungGesperrtError,
                        KategorieInBenutzungError, NichtJuengsterLaufError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (BelegFehltError, EmpfaengerFehltError, BetragFehltError,
                        ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


def _serialisiere(r) -> dict:
    """Dataclass + abgeleitete Felder, die das Frontend fürs Gating braucht."""
    d = asdict(r)
    d["ist_exportiert"] = r.ist_exportiert
    return d


def _pruefe_status_filter(status: Optional[str]) -> Optional[str]:
    """'exportiert' ist als Filterwert erlaubt, obwohl es kein Spaltenwert ist –
    das Repository übersetzt es auf den Export-Stempel."""
    if status and status not in STATUS_FILTER_WERTE:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannter Status – erlaubt: {', '.join(STATUS_FILTER_WERTE)}.")
    return status or None


# ---------------------------------------------------------------------------
# Kategorien (vor /{rechnung_id}!)
# ---------------------------------------------------------------------------

@router.get("/kategorien")
def list_kategorien(user: CurrentUser, db: DB):
    """Auswahlliste fürs Einreichen – jeder eingeloggte Benutzer darf sie lesen."""
    return [asdict(k) for k in db.rechnungen.list_kategorien()]


@router.post("/kategorien", status_code=201)
def create_kategorie(payload: KategorieWrite, user: CurrentUser, db: DB):
    try:
        return asdict(db.rechnungen.kategorie_anlegen(user, **payload.model_dump()))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.patch("/kategorien/{kategorie_id}")
def update_kategorie(kategorie_id: int, payload: KategorieUpdate,
                     user: CurrentUser, db: DB):
    daten = payload.model_dump()
    expected_version = daten.pop("expected_version")
    try:
        return asdict(db.rechnungen.kategorie_aktualisieren(
            kategorie_id, user, expected_version=expected_version, **daten))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.delete("/kategorien/{kategorie_id}", status_code=204)
def delete_kategorie(kategorie_id: int, user: CurrentUser, db: DB):
    try:
        db.rechnungen.kategorie_loeschen(kategorie_id, user)
    except Exception as exc:
        raise _fehler_zu_http(exc)


# ---------------------------------------------------------------------------
# Export (vor /{rechnung_id}!)
# ---------------------------------------------------------------------------

def _require_verwalten(user) -> None:
    if not user.has_permission(Permission.RECHNUNGEN_VERWALTEN):
        raise HTTPException(status_code=403,
                            detail="Nur mit dem Recht 'rechnungen.verwalten'.")


def _zip_response(dateiname: str, zip_bytes: bytes) -> Response:
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


@router.get("/export/vorschau")
def export_vorschau(user: CurrentUser, db: DB):
    _require_verwalten(user)
    v = db.rechnung_export.vorschau()
    return {**v, "rechnungen": [_serialisiere(r) for r in v["rechnungen"]]}


@router.get("/export")
def list_exporte(user: CurrentUser, db: DB):
    _require_verwalten(user)
    return [asdict(e) for e in db.rechnung_export.list_exporte()]


@router.post("/export")
def exportieren(user: CurrentUser, db: DB):
    """Neuer Lauf: Zip mit Belegen + uebersicht.csv; stempelt die Rechnungen."""
    _require_verwalten(user)
    try:
        dateiname, zip_bytes = db.rechnung_export.exportieren(user.username)
    except KeineRechnungenError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _zip_response(dateiname, zip_bytes)


@router.get("/export/{export_id}")
def re_download(export_id: int, user: CurrentUser, db: DB):
    _require_verwalten(user)
    try:
        dateiname, zip_bytes = db.rechnung_export.re_download(export_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    return _zip_response(dateiname, zip_bytes)


@router.delete("/export/{export_id}")
def export_zuruecknehmen(export_id: int, user: CurrentUser, db: DB):
    """Un-Export des jüngsten Laufs – die Rechnungen werden wieder offen."""
    _require_verwalten(user)
    try:
        return db.rechnung_export.zuruecknehmen(export_id, user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except NichtJuengsterLaufError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ---------------------------------------------------------------------------
# Rechnungen
# ---------------------------------------------------------------------------

@router.get("/meine-abteilungen")
def meine_abteilungen(user: CurrentUser, db: DB):
    """Abteilungen, für die dieser Benutzer einreichen kann.

    Genau eine → das Frontend setzt sie ohne Auswahlfeld; leer → Vereinsrechnung.
    """
    return db.rechnungen.abteilungen_fuer_user(user)


@router.get("")
def list_rechnungen(
    user: CurrentUser,
    db: DB,
    sicht: str = Query("mine", pattern="^(mine|freigabe|alle)$"),
    status: Optional[str] = None,
):
    status = _pruefe_status_filter(status)
    try:
        if sicht == "freigabe":
            rechnungen = db.rechnungen.list_zur_freigabe(user, status)
        elif sicht == "alle":
            rechnungen = db.rechnungen.list_alle(user, status)
        else:
            rechnungen = db.rechnungen.list_meine(user, status)
    except Exception as exc:
        raise _fehler_zu_http(exc)
    return [_serialisiere(r) for r in rechnungen]


@router.post("", status_code=201)
def create_rechnung(payload: RechnungWrite, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.anlegen(user, **payload.model_dump()))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.get("/{rechnung_id}")
def get_rechnung(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.get(rechnung_id, user))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.patch("/{rechnung_id}")
def update_rechnung(rechnung_id: int, payload: RechnungUpdate,
                    user: CurrentUser, db: DB):
    daten = payload.model_dump()
    expected_version = daten.pop("expected_version")
    try:
        return _serialisiere(db.rechnungen.aktualisieren(
            rechnung_id, user, expected_version=expected_version, **daten))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.delete("/{rechnung_id}", status_code=204)
def delete_rechnung(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        db.rechnungen.loeschen(rechnung_id, user)
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.post("/{rechnung_id}/einreichen")
def einreichen(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.einreichen(rechnung_id, user))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.post("/{rechnung_id}/freigeben")
def freigeben(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.freigeben(rechnung_id, user))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.post("/{rechnung_id}/ablehnen")
def ablehnen(rechnung_id: int, payload: AblehnenWrite, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.ablehnen(rechnung_id, user, payload.grund))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.post("/{rechnung_id}/zuruecksetzen")
def zuruecksetzen(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        return _serialisiere(db.rechnungen.zuruecksetzen(rechnung_id, user))
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.get("/{rechnung_id}/history")
def get_history(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        db.rechnungen.get(rechnung_id, user)   # Sichtbarkeit prüfen
    except Exception as exc:
        raise _fehler_zu_http(exc)
    return db.rechnung_repository.get_history(rechnung_id)


# ---------------------------------------------------------------------------
# Belege
# ---------------------------------------------------------------------------

@router.get("/{rechnung_id}/anhaenge")
def list_anhaenge(rechnung_id: int, user: CurrentUser, db: DB):
    try:
        return [asdict(a) for a in db.rechnungen.list_anhaenge(rechnung_id, user)]
    except Exception as exc:
        raise _fehler_zu_http(exc)


@router.post("/{rechnung_id}/anhaenge", status_code=201)
async def upload_anhang(rechnung_id: int, user: CurrentUser, db: DB,
                        file: UploadFile = File(...)):
    inhalt = await file.read()
    try:
        anhang = db.rechnungen.add_anhang(
            rechnung_id, user,
            original_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            inhalt=inhalt,
        )
    except (DateitypNichtErlaubtError, DateiZuGrossError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except IOError as exc:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {exc}")
    except Exception as exc:
        raise _fehler_zu_http(exc)
    return asdict(anhang)


@router.delete("/{rechnung_id}/anhaenge/{anhang_id}", status_code=204)
def delete_anhang(rechnung_id: int, anhang_id: int, user: CurrentUser, db: DB):
    try:
        db.rechnungen.delete_anhang(rechnung_id, anhang_id, user)
    except Exception as exc:
        raise _fehler_zu_http(exc)
