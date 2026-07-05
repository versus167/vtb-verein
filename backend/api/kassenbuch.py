"""
Kassenbuch API – Kassen, Buchungen, Exporte und Berechtigungen.

Berechtigungsmodell (seit Stufe D, siehe BERECHTIGUNGEN.md):
  - Kassen anlegen/bearbeiten/löschen: Permission kassen.verwalten
  - Berechtigungen pro Kasse verwalten: Permission kassen.verwalten
  - Buchungen lesen/schreiben: kassenspezifisch via kasse_berechtigungen
    (per-Kasse-ACL); kassen.verwalten umgeht diese ACL (globaler Kassen-Admin).
"""

from dataclasses import asdict
from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, field_validator
from typing import Optional

from backend.core.deps import CurrentUser, DB
from app.models.permission import Permission
from app.models.kasse import Kasse, Kassenbuchung, KassenKategorie, EURO_STUECKELUNG_CENT
from app.services.kassenbuch_service import (
    BuchungGesperrtError,
    NegativerBestandError,
    KeinLesezugriffError,
    KeinSchreibzugriffError,
    KeinExportrechtError,
    DatumAusserhalbBereichError,
    KategorieUngueltigError,
    ZaehlungUngueltigError,
    FibuKassenExportFehler,
)
from app.services.anhang_service import DateitypNichtErlaubtError, DateiZuGrossError
from app.services.kassenbuch_pdf_service import erstelle_kassenbuch_pdf

router = APIRouter(prefix="/kassen", tags=["kassenbuch"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class KasseWrite(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    anfangsbestand_cent: int = 0
    abteilung_id: Optional[int] = None
    sachkonto: Optional[str] = None     # FBASC-Feld 00 (Sachkonto der Barkasse)


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


class KategorieWrite(BaseModel):
    name: str
    kasse_id: Optional[int] = None      # None = allgemein (gilt für alle Kassen)
    loest_zaehlung_aus: bool = False    # True → Buchung mit dieser Kategorie fordert eine Kassenzählung an
    gegenkonto: Optional[str] = None    # FBASC-Feld 01 (Erlös-/Aufwandskonto dieser Kategorie)
    kostentraeger: Optional[int] = None  # FBASC-Feld 08 (None = Default aus Fibu-Einstellungen)

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Name darf nicht leer sein.")
        return v


class KategorieUpdate(KategorieWrite):
    expected_version: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kassen_admin(user) -> bool:
    """Globaler Kassen-Admin (umgeht die per-Kasse-ACL). Admins haben das Recht
    immer (has_permission → True für role 'admin')."""
    return user.has_permission(Permission.KASSEN_VERWALTEN)


def _require_kassen_verwalten(user) -> None:
    if not user.has_permission(Permission.KASSEN_VERWALTEN):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zur Kassenverwaltung.")


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
    if isinstance(exc, KategorieUngueltigError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ZaehlungUngueltigError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, FibuKassenExportFehler):
        return HTTPException(status_code=422, detail={"message": str(exc), "fehler": exc.fehler})
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
    is_admin = _kassen_admin(user)
    kassen = db.kassenbuch.get_kassen_fuer_user(user.id, is_admin=is_admin)
    result = []
    for k in kassen:
        d = asdict(k)
        d["bestand_cent"] = db.kassen.get_bestand_cent(k.id)
        if is_admin:
            d["darf_lesen"] = True
            d["darf_schreiben"] = True
            d["darf_exportieren"] = True
        else:
            b = db.kasse_berechtigungen.get_berechtigung(k.id, user.id)
            d["darf_lesen"] = bool(b and b.darf_lesen)
            d["darf_schreiben"] = bool(b and b.darf_schreiben)
            d["darf_exportieren"] = bool(b and b.darf_exportieren)
        result.append(d)
    return result


@router.post("/", status_code=201)
def create_kasse(data: KasseWrite, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
    kasse = Kasse(
        name=data.name,
        beschreibung=data.beschreibung,
        anfangsbestand_cent=data.anfangsbestand_cent,
        abteilung_id=data.abteilung_id,
        sachkonto=data.sachkonto,
    )
    created = db.kassenbuch.create_kasse(kasse, created_by=user.username)
    return asdict(created)


@router.put("/{kasse_id}")
def update_kasse(kasse_id: int, data: KasseUpdate, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
    try:
        kasse = db.kassen.get_kasse(kasse_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Kasse {kasse_id} nicht gefunden.")
    kasse.name = data.name
    kasse.beschreibung = data.beschreibung
    kasse.anfangsbestand_cent = data.anfangsbestand_cent
    kasse.abteilung_id = data.abteilung_id
    kasse.sachkonto = data.sachkonto
    kasse.version = data.expected_version
    ok = db.kassenbuch.update_kasse(kasse, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return asdict(db.kassen.get_kasse(kasse_id))


@router.delete("/{kasse_id}", status_code=204)
def delete_kasse(kasse_id: int, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
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
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
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
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
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
            user_id=user.id, is_admin=_kassen_admin(user),
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
            user_id=user.id, is_admin=_kassen_admin(user),
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
            user_id=user.id, is_admin=_kassen_admin(user),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)


@router.get("/{kasse_id}/datum-bereich")
def get_datum_bereich(kasse_id: int, user: CurrentUser, db: DB):
    """Gibt den erlaubten Datumsbereich für neue Buchungen zurück."""
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
        min_datum, max_datum = db.kassenbuch.get_datum_bereich(kasse_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"min_datum": min_datum, "max_datum": max_datum}


# ---------------------------------------------------------------------------
# FBASC-Export (hmd) – Zip mit fbasc.hia + Belegen + Kassenbericht
# ---------------------------------------------------------------------------

def _zip_response(dateiname: str, zip_bytes: bytes) -> Response:
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


def _csv_response(dateiname: str, csv_bytes: bytes) -> Response:
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


@router.post("/{kasse_id}/exporte")
def create_export(kasse_id: int, data: ExportRequest, user: CurrentUser, db: DB):
    """Exportiert die offenen Buchungen bis bis_datum als hmd-FBASC-Zip.

    Das Zip enthält flach im Root: fbasc.hia, alle Belege (Feld 39) und den
    Perioden-Kassenbericht. Sperrt die Buchungen danach (Export-Schutz).
    """
    try:
        dateiname, zip_bytes = db.kassenbuch.exportiere_fbasc(
            kasse_id,
            bis_datum=data.bis_datum,
            exported_by=user.username,
            user_id=user.id,
            is_admin=_kassen_admin(user),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)

    return _zip_response(dateiname, zip_bytes)


@router.get("/{kasse_id}/exporte")
def list_exporte(kasse_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
        exporte = db.kassenbuch._export.list_exporte(kasse_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [asdict(e) for e in exporte]


@router.get("/{kasse_id}/exporte/{export_id}/download")
def redownload_export(kasse_id: int, export_id: int, user: CurrentUser, db: DB):
    """Lädt einen abgeschlossenen Export erneut herunter (FBASC-Zip bzw. Altbestand-CSV)."""
    try:
        export = db.kassenbuch._export.get_export(export_id)
        if export.format == "csv":
            dateiname, inhalt = db.kassenbuch.reexportiere_csv(
                export_id, user_id=user.id, is_admin=_kassen_admin(user))
            return _csv_response(dateiname, inhalt)
        dateiname, inhalt = db.kassenbuch.reexportiere_fbasc(
            export_id, user_id=user.id, is_admin=_kassen_admin(user))
        return _zip_response(dateiname, inhalt)
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)


@router.delete("/{kasse_id}/exporte/{export_id}", status_code=200)
def zuruecknehmen_export(kasse_id: int, export_id: int, user: CurrentUser, db: DB):
    """Un-Export: den jüngsten Export einer Kasse zurücknehmen.

    Gibt die gesperrten Buchungen wieder frei und soft-deletet den Export-Header.
    """
    try:
        return db.kassenbuch.zuruecknehmen_export(
            export_id,
            benutzer=user.username,
            user_id=user.id,
            is_admin=_kassen_admin(user),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)


# ---------------------------------------------------------------------------
# PDF-Kassenbericht
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/bericht.pdf")
def kassenbuch_pdf_bericht(
    kasse_id: int,
    user: CurrentUser,
    db: DB,
    von: str = Query(..., description="Startdatum ISO (YYYY-MM-DD)"),
    bis: str = Query(..., description="Enddatum ISO (YYYY-MM-DD)"),
):
    try:
        bericht_daten = db.kassenbuch.get_kassenbericht_daten(
            kasse_id,
            von_datum=von,
            bis_datum=bis,
            include_storniert=True,
            user_id=user.id,
            is_admin=_kassen_admin(user),
        )
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="Kasse nicht gefunden.")

    buchungen_pdf = [
        {**asdict(e["buchung"]), "ist_storniert": e["buchung"].ist_storniert}
        for e in bericht_daten["buchungen"]
    ]
    pdf_bytes = erstelle_kassenbuch_pdf(
        kasse_name=bericht_daten["kasse"].name,
        von_datum=von,
        bis_datum=bis,
        buchungen=buchungen_pdf,
        anfangsbestand_cent=bericht_daten["anfangsbestand_cent"],
        erstellt_von=user.username,
    )
    kasse_slug = bericht_daten["kasse"].name.lower().replace(" ", "_")
    dateiname = f"kassenbuch_{kasse_slug}_{von}_{bis}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


# ---------------------------------------------------------------------------
# Zählprotokoll (Kassenzählung / Stückelung)
# ---------------------------------------------------------------------------

class ZaehlungWrite(BaseModel):
    stueckelung: dict[str, int] = {}        # {"5000": 2, ...} Cent-Wert (String) → Anzahl
    notiz: Optional[str] = None
    ausloesende_buchung_id: Optional[int] = None
    # Kategorie-getriebene Zählung (Ticket #38): die Zählung IST die Buchung dieser Kategorie
    # (Betrag = Zählung − Altbestand). Buchungstext ist der Text der erzeugten Buchung.
    kategorie: Optional[str] = None
    buchungstext: Optional[str] = None


def _zaehlung_dict(z, belegnummer: Optional[str] = None) -> dict:
    d = asdict(z)
    d["belegnummer"] = belegnummer          # Beleg-Nr. der zugehörigen Zähl-Buchung (Anzeige)
    return d


def _beleg_fuer_buchung(db, buchung_id: Optional[int]) -> Optional[str]:
    if buchung_id is None:
        return None
    try:
        return db.kassenbuch._buchung.get_kassenbuchung(buchung_id).belegnummer
    except KeyError:
        return None


@router.get("/stueckelung")
def get_stueckelung(user: CurrentUser):
    """Gültige Münz-/Scheinwerte (Cent, absteigend) für die Zähl-Erfassung."""
    return {"werte_cent": list(EURO_STUECKELUNG_CENT)}


@router.get("/{kasse_id}/zaehlungen")
def list_zaehlungen(kasse_id: int, user: CurrentUser, db: DB):
    """Zählprotokolle einer Kasse (neueste zuerst)."""
    try:
        zaehlungen = db.kassenbuch.list_zaehlungen(
            kasse_id, user_id=user.id, is_admin=_kassen_admin(user)
        )
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [_zaehlung_dict(z, _beleg_fuer_buchung(db, z.buchung_id)) for z in zaehlungen]


@router.post("/{kasse_id}/zaehlungen", status_code=201)
def create_zaehlung(kasse_id: int, data: ZaehlungWrite, user: CurrentUser, db: DB):
    """Erfasst eine Kassenzählung: legt die Zähl-/Differenzbuchung an, speichert das
    Protokoll und hängt das Zählprotokoll-PDF an die Buchung."""
    try:
        zaehlung = db.kassenbuch.erstelle_zaehlung(
            kasse_id,
            stueckelung=data.stueckelung,
            notiz=data.notiz,
            ausloesende_buchung_id=data.ausloesende_buchung_id,
            kategorie=data.kategorie,
            buchungstext=data.buchungstext,
            created_by=user.username,
            user_id=user.id,
            is_admin=_kassen_admin(user),
        )
    except Exception as exc:
        raise _kassenbuch_error_to_http(exc)
    return _zaehlung_dict(zaehlung, _beleg_fuer_buchung(db, zaehlung.buchung_id))


# ---------------------------------------------------------------------------
# Kategorien (Stammdaten für Buchungs-Kategorien)
# ---------------------------------------------------------------------------

def _kassen_namen(db) -> dict:
    return {k.id: k.name for k in db.kassen.list_kassen()}


def _kategorie_dict(k: KassenKategorie, kasse_name: Optional[str]) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "kasse_id": k.kasse_id,
        "kasse_name": kasse_name,            # None bei allgemeiner Kategorie
        "ist_allgemein": k.kasse_id is None,
        "loest_zaehlung_aus": k.loest_zaehlung_aus,
        "gegenkonto": k.gegenkonto,
        "kostentraeger": k.kostentraeger,
        "version": k.version,
    }


@router.get("/{kasse_id}/kategorien")
def list_kategorien_fuer_kasse(kasse_id: int, user: CurrentUser, db: DB):
    """Effektive Kategorie-Auswahl einer Kasse (allgemein ∪ kassenspezifisch).

    Für das Dropdown bei der Buchungserfassung – braucht nur Lesezugriff.
    """
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return [
        {"id": k.id, "name": k.name, "kasse_id": k.kasse_id,
         "ist_allgemein": k.kasse_id is None, "loest_zaehlung_aus": k.loest_zaehlung_aus}
        for k in db.kassen_kategorien.list_for_kasse(kasse_id)
    ]


@router.get("/kategorien")
def list_alle_kategorien(user: CurrentUser, db: DB):
    """Alle Kategorien (allgemein + kassenspezifisch) für die Verwaltung."""
    _require_kassen_verwalten(user)
    namen = _kassen_namen(db)
    return [_kategorie_dict(k, namen.get(k.kasse_id)) for k in db.kassen_kategorien.list_all()]


@router.post("/kategorien", status_code=201)
def create_kategorie(data: KategorieWrite, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
    if data.kasse_id is not None:
        try:
            db.kassen.get_kasse(data.kasse_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Kasse {data.kasse_id} nicht gefunden.")
    if db.kassen_kategorien.name_konflikt(data.kasse_id, data.name):
        raise HTTPException(status_code=409, detail="Eine Kategorie mit diesem Namen existiert hier bereits.")
    kat = db.kassen_kategorien.create(
        KassenKategorie(name=data.name, kasse_id=data.kasse_id,
                        loest_zaehlung_aus=data.loest_zaehlung_aus,
                        gegenkonto=data.gegenkonto, kostentraeger=data.kostentraeger),
        created_by=user.username,
    )
    return _kategorie_dict(kat, _kassen_namen(db).get(kat.kasse_id))


@router.put("/kategorien/{kategorie_id}")
def update_kategorie(kategorie_id: int, data: KategorieUpdate, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
    kat = db.kassen_kategorien.get(kategorie_id)
    if kat is None or kat.deleted_at is not None:
        raise HTTPException(status_code=404, detail=f"Kategorie {kategorie_id} nicht gefunden.")
    if data.kasse_id is not None:
        try:
            db.kassen.get_kasse(data.kasse_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Kasse {data.kasse_id} nicht gefunden.")
    if db.kassen_kategorien.name_konflikt(data.kasse_id, data.name, exclude_id=kategorie_id):
        raise HTTPException(status_code=409, detail="Eine Kategorie mit diesem Namen existiert hier bereits.")
    kat.name = data.name
    kat.kasse_id = data.kasse_id
    kat.loest_zaehlung_aus = data.loest_zaehlung_aus
    kat.gegenkonto = data.gegenkonto
    kat.kostentraeger = data.kostentraeger
    kat.version = data.expected_version
    if not db.kassen_kategorien.update(kat, updated_by=user.username):
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    updated = db.kassen_kategorien.get(kategorie_id)
    return _kategorie_dict(updated, _kassen_namen(db).get(updated.kasse_id))


@router.delete("/kategorien/{kategorie_id}", status_code=204)
def delete_kategorie(kategorie_id: int, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
    if not db.kassen_kategorien.mark_deleted(kategorie_id, deleted_by=user.username):
        raise HTTPException(status_code=404, detail=f"Kategorie {kategorie_id} nicht gefunden.")


# ---------------------------------------------------------------------------
# Berechtigungen (Admin)
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/berechtigungen")
def list_berechtigungen(kasse_id: int, user: CurrentUser, db: DB):
    _require_kassen_verwalten(user)
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
    _require_kassen_verwalten(user)
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
    _require_kassen_verwalten(user)
    ok = db.kasse_berechtigungen.revoke_berechtigung(kasse_id, user_id, actor=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Berechtigung nicht gefunden.")


# ---------------------------------------------------------------------------
# Anhänge (Belegfotos)
# ---------------------------------------------------------------------------

@router.get("/{kasse_id}/buchungen/{buchung_id}/anhaenge")
def list_anhaenge(kasse_id: int, buchung_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
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
        db.kassenbuch._pruefe_schreibzugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
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
        db.kassenbuch._pruefe_schreibzugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
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


@router.get("/{kasse_id}/buchungen/{buchung_id}/history")
def get_buchung_history(kasse_id: int, buchung_id: int, user: CurrentUser, db: DB):
    try:
        db.kassenbuch._pruefe_lesezugriff(kasse_id, user.id, is_admin=_kassen_admin(user))
        buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
    except KeinLesezugriffError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Buchung {buchung_id} nicht gefunden.")
    if buchung.kasse_id != kasse_id:
        raise HTTPException(status_code=404, detail="Buchung gehört nicht zu dieser Kasse.")
    return {
        "buchungen": db.kassenbuch._buchung.get_history(buchung_id),
        "anhaenge": db.kassenbuch._anhang_repo.list_all_by_buchung(buchung_id),
    }
