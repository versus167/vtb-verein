"""API für die Übungsleiter-Stundenerfassung.

Rollen:
- Übungsleiter (Funktion 'uebungsleiter' → ulstunden.erfassen): erfasst/bearbeitet/
  reicht NUR die eigenen Abrechnungen ein (Bezug über mitglied.user_id).
- Abteilungsleiter (Funktion 'abteilungsleiter' → ulstunden.bestaetigen, scoped):
  bestätigt/lehnt Abrechnungen seiner Abteilung(en) ab.
- Verwaltung/Fibu (ulstunden.verwalten): sieht alle Abrechnungen, pflegt Sätze.
"""
import unicodedata
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.models.ul_stunden import ULSatz
from app.services.ul_stunden_service import ULStundenService
from app.services.ul_stundennachweis_pdf_service import erstelle_stundennachweis_pdf
from ..core.config import settings
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/ul-stunden", tags=["ul-stunden"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AbrechnungCreate(BaseModel):
    abteilung_id: int
    zeitraum_von: str
    zeitraum_bis: str
    lizenz_klassifikation: str = 'ohne_lizenz'
    foerder_klassifikation: Optional[str] = None


class AbrechnungUpdate(AbrechnungCreate):
    expected_version: int


class StundeCreate(BaseModel):
    datum: str
    stunden: float
    angebot: Optional[str] = None
    bemerkung: Optional[str] = None


class AblehnenBody(BaseModel):
    grund: Optional[str] = None


class SatzCreate(BaseModel):
    lizenz_klassifikation: str
    satz: float
    mitglied_id: Optional[int] = None
    abteilung_id: Optional[int] = None
    gueltig_ab: Optional[str] = None


class SatzUpdate(SatzCreate):
    expected_version: int


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _own_mitglied_id(user, db) -> int:
    m = db.get_mitglied_by_user_id(user.id)
    if m is None:
        raise HTTPException(status_code=400,
                            detail="Kein Mitglied mit diesem Benutzer verknüpft")
    return m.id


def _can_verwalten(user) -> bool:
    return user.has_permission(Permission.UL_STUNDEN_VERWALTEN)


def _can_confirm(user, abteilung_id: int) -> bool:
    return (_can_verwalten(user)
            or user.has_permission_for_abteilung(Permission.UL_STUNDEN_BESTAETIGEN, abteilung_id))


def _load(db, abrechnung_id: int):
    a = db.ul_abrechnungen.get(abrechnung_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Abrechnung nicht gefunden")
    return a


def _can_view(user, db, a) -> bool:
    """Eigentümer, Abteilungsleiter der Abteilung oder Verwaltung."""
    own = db.get_mitglied_by_user_id(user.id)
    is_owner = own is not None and own.id == a.mitglied_id
    return is_owner or _can_confirm(user, a.abteilung_id)


def _require_owner_entwurf(user, db, a):
    """Stellt sicher, dass der aktuelle User Eigentümer und die Abrechnung im Entwurf ist."""
    if a.mitglied_id != _own_mitglied_id(user, db):
        raise HTTPException(status_code=403, detail="Nur die eigene Abrechnung ist bearbeitbar")
    if a.status != 'entwurf':
        raise HTTPException(status_code=409, detail="Abrechnung ist nicht mehr im Entwurf")


def _abrechnung_dict(db, a, *, with_details: bool = False) -> dict:
    svc = ULStundenService(db)
    d = asdict(a)
    d['summen'] = svc.summen(a)
    if with_details:
        d['stunden'] = [asdict(s) for s in db.ul_abrechnungen.list_stunden(a.id)]
        d['erfassbar_ab'] = svc.erfassbar_ab(a.mitglied_id, a.abteilung_id)
    return d


# ---------------------------------------------------------------------------
# Listen
# ---------------------------------------------------------------------------

@router.get("/meine")
def list_meine(user: CurrentUser, db: DB, status_filter: Optional[str] = None):
    """Eigene Abrechnungen des eingeloggten Übungsleiters."""
    if not (user.has_permission(Permission.UL_STUNDEN_ERFASSEN) or _can_verwalten(user)):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zur Stundenerfassung")
    mid = _own_mitglied_id(user, db)
    return [_abrechnung_dict(db, a)
            for a in db.ul_abrechnungen.list_for_mitglied(mid, status_filter)]


@router.get("/zu-bestaetigen")
def list_zu_bestaetigen(user: CurrentUser, db: DB, status_filter: Optional[str] = 'eingereicht'):
    """Abrechnungen zur Bestätigung – auf die Abteilungen des Abteilungsleiters beschränkt."""
    if _can_verwalten(user):
        abteilungen = None
    elif user.has_permission(Permission.UL_STUNDEN_BESTAETIGEN):
        abteilungen = user.allowed_abteilungen(Permission.UL_STUNDEN_BESTAETIGEN)
    else:
        raise HTTPException(status_code=403, detail="Keine Berechtigung zur Bestätigung")
    return [_abrechnung_dict(db, a)
            for a in db.ul_abrechnungen.list_for_abteilungen(abteilungen, status_filter)]


@router.get("")
def list_alle(user: CurrentUser, db: DB, status_filter: Optional[str] = None):
    """Alle Abrechnungen (Verwaltung/Fibu)."""
    if not _can_verwalten(user):
        raise HTTPException(status_code=403, detail="Keine Verwaltungsberechtigung")
    return [_abrechnung_dict(db, a) for a in db.ul_abrechnungen.list_all(status_filter)]


# ---------------------------------------------------------------------------
# Vergütungssätze (Verwaltung)
# ---------------------------------------------------------------------------

@router.get("/saetze")
def list_saetze(user: CurrentUser, db: DB):
    if not _can_verwalten(user):
        raise HTTPException(status_code=403, detail="Keine Verwaltungsberechtigung")
    return [asdict(s) for s in db.ul_saetze.list_all()]


@router.post("/saetze", status_code=status.HTTP_201_CREATED)
def create_satz(data: SatzCreate, user: CurrentUser, db: DB):
    if not _can_verwalten(user):
        raise HTTPException(status_code=403, detail="Keine Verwaltungsberechtigung")
    s = ULSatz(mitglied_id=data.mitglied_id, abteilung_id=data.abteilung_id,
               lizenz_klassifikation=data.lizenz_klassifikation, satz=data.satz,
               gueltig_ab=(data.gueltig_ab or None))
    return asdict(db.ul_saetze.create(s, created_by=user.username))


@router.put("/saetze/{satz_id}")
def update_satz(satz_id: int, data: SatzUpdate, user: CurrentUser, db: DB):
    if not _can_verwalten(user):
        raise HTTPException(status_code=403, detail="Keine Verwaltungsberechtigung")
    s = db.ul_saetze.get(satz_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Satz nicht gefunden")
    s.mitglied_id = data.mitglied_id
    s.abteilung_id = data.abteilung_id
    s.lizenz_klassifikation = data.lizenz_klassifikation
    s.satz = data.satz
    s.gueltig_ab = (data.gueltig_ab or None)
    s.version = data.expected_version
    if not db.ul_saetze.update(s, updated_by=user.username):
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte neu laden")
    return asdict(db.ul_saetze.get(satz_id))


@router.delete("/saetze/{satz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_satz(satz_id: int, user: CurrentUser, db: DB):
    if not _can_verwalten(user):
        raise HTTPException(status_code=403, detail="Keine Verwaltungsberechtigung")
    db.ul_saetze.soft_delete(satz_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Einzelne Abrechnung
# ---------------------------------------------------------------------------

@router.get("/{abrechnung_id}")
def get_abrechnung(abrechnung_id: int, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    if not _can_view(user, db, a):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Abrechnung")
    return _abrechnung_dict(db, a, with_details=True)


@router.get("/{abrechnung_id}/beleg.pdf")
def beleg_pdf(abrechnung_id: int, user: CurrentUser, db: DB):
    """Erzeugt den Übungsleiter-Stundennachweis als PDF-Beleg (A4 quer)."""
    a = _load(db, abrechnung_id)
    if not _can_view(user, db, a):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Abrechnung")
    # Lizenz-/Qualifikations-Stammdaten am Mitglied (für den Beleg-Kopf)
    try:
        m = db.get_mitglied(a.mitglied_id)
    except KeyError:
        m = None
    verein = {
        'name': settings.VEREIN_NAME,
        'strasse': settings.VEREIN_STRASSE,
        'plz_ort': settings.VEREIN_PLZ_ORT,
        'registrier_nr': settings.VEREIN_REGISTRIER_NR,
    }
    pdf = erstelle_stundennachweis_pdf(
        verein=verein,
        ul_name=f"{a.mitglied_vorname or ''} {a.mitglied_nachname or ''}".strip(),
        sportart=a.abteilung_name or '',
        iban=a.mitglied_iban,
        trainerlizenz_nr=(m.trainerlizenz_nr if m else None),
        qualifikation=(m.qualifikation if m else None),
        lizenz_klassifikation=a.lizenz_klassifikation,
        foerder_klassifikation=a.foerder_klassifikation,
        zeitraum_von=a.zeitraum_von,
        zeitraum_bis=a.zeitraum_bis,
        termine=[asdict(s) for s in db.ul_abrechnungen.list_stunden(a.id)],
        summen=ULStundenService(db).summen(a),
        erstellt_von=user.username,
    )
    nachname = (a.mitglied_nachname or 'UL').replace(' ', '_')
    dateiname = f"Stundennachweis_{nachname}_{a.zeitraum_von}_{a.zeitraum_bis}.pdf"
    # Content-Disposition muss latin-1-codierbar sein → Dateiname auf ASCII reduzieren
    # (Umlaute transliterieren), damit Belege mit Umlaut-Namen nicht am Header scheitern.
    ascii_name = (unicodedata.normalize('NFKD', dateiname)
                  .encode('ascii', 'ignore').decode('ascii')) or 'Stundennachweis.pdf'
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{ascii_name}"'})


@router.post("", status_code=status.HTTP_201_CREATED)
def create_abrechnung(data: AbrechnungCreate, user: CurrentUser, db: DB):
    if not (user.has_permission(Permission.UL_STUNDEN_ERFASSEN) or _can_verwalten(user)):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zur Stundenerfassung")
    mid = _own_mitglied_id(user, db)
    try:
        a = ULStundenService(db).create_abrechnung(
            mitglied_id=mid, abteilung_id=data.abteilung_id,
            von=data.zeitraum_von, bis=data.zeitraum_bis,
            lizenz_klassifikation=data.lizenz_klassifikation,
            foerder_klassifikation=data.foerder_klassifikation,
            erstellt_von=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _abrechnung_dict(db, a, with_details=True)


@router.put("/{abrechnung_id}")
def update_abrechnung(abrechnung_id: int, data: AbrechnungUpdate, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    try:
        ok = ULStundenService(db).update_kopf(
            a, von=data.zeitraum_von, bis=data.zeitraum_bis,
            lizenz_klassifikation=data.lizenz_klassifikation,
            foerder_klassifikation=data.foerder_klassifikation,
            expected_version=data.expected_version, updated_by=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte neu laden")
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


@router.delete("/{abrechnung_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_abrechnung(abrechnung_id: int, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    db.ul_abrechnungen.soft_delete(abrechnung_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Einzeltermine
# ---------------------------------------------------------------------------

@router.post("/{abrechnung_id}/stunden", status_code=status.HTTP_201_CREATED)
def add_stunde(abrechnung_id: int, data: StundeCreate, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    try:
        ULStundenService(db).add_stunde(
            a, datum=data.datum, stunden=data.stunden,
            angebot=data.angebot, bemerkung=data.bemerkung, erstellt_von=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


@router.put("/{abrechnung_id}/stunden/{stunde_id}")
def update_stunde(abrechnung_id: int, stunde_id: int, data: StundeCreate,
                  user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    s = db.ul_abrechnungen.get_stunde(stunde_id)
    if s is None or s.abrechnung_id != abrechnung_id:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    try:
        ULStundenService(db).update_stunde(
            a, s, datum=data.datum, stunden=data.stunden,
            angebot=data.angebot, bemerkung=data.bemerkung, updated_by=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


@router.delete("/{abrechnung_id}/stunden/{stunde_id}")
def delete_stunde(abrechnung_id: int, stunde_id: int, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    s = db.ul_abrechnungen.get_stunde(stunde_id)
    if s is None or s.abrechnung_id != abrechnung_id:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    db.ul_abrechnungen.delete_stunde(stunde_id, deleted_by=user.username)
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

@router.post("/{abrechnung_id}/einreichen")
def einreichen(abrechnung_id: int, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    _require_owner_entwurf(user, db, a)
    try:
        a = ULStundenService(db).einreichen(a, eingereicht_von=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _abrechnung_dict(db, a, with_details=True)


@router.post("/{abrechnung_id}/bestaetigen")
def bestaetigen(abrechnung_id: int, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    if not _can_confirm(user, a.abteilung_id):
        raise HTTPException(status_code=403, detail="Keine Bestätigungsberechtigung für diese Abteilung")
    if not db.ul_abrechnungen.bestaetigen(abrechnung_id, bestaetigt_von=user.username):
        raise HTTPException(status_code=409, detail="Nur eingereichte Abrechnungen können bestätigt werden")
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


@router.post("/{abrechnung_id}/ablehnen")
def ablehnen(abrechnung_id: int, data: AblehnenBody, user: CurrentUser, db: DB):
    a = _load(db, abrechnung_id)
    if not _can_confirm(user, a.abteilung_id):
        raise HTTPException(status_code=403, detail="Keine Bestätigungsberechtigung für diese Abteilung")
    if not db.ul_abrechnungen.ablehnen(abrechnung_id, grund=(data.grund or None),
                                       abgelehnt_von=user.username):
        raise HTTPException(status_code=409, detail="Nur eingereichte Abrechnungen können abgelehnt werden")
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)


@router.post("/{abrechnung_id}/zuruecksetzen")
def zuruecksetzen(abrechnung_id: int, user: CurrentUser, db: DB):
    """Setzt eine bestätigte/abgelehnte (noch nicht exportierte) Abrechnung zurück
    auf 'entwurf', sodass der ÜL nachbessern kann.

    Erlaubt für AL/Verwaltung (jeder Status) sowie für den Eigentümer selbst,
    solange die Abrechnung abgelehnt wurde."""
    a = _load(db, abrechnung_id)
    own = db.get_mitglied_by_user_id(user.id)
    is_owner = own is not None and own.id == a.mitglied_id
    if not (_can_confirm(user, a.abteilung_id) or (is_owner and a.status == 'abgelehnt')):
        raise HTTPException(status_code=403, detail="Keine Berechtigung für diese Abteilung")
    if not db.ul_abrechnungen.zuruecksetzen(abrechnung_id, updated_by=user.username):
        raise HTTPException(status_code=409,
                            detail="Zurücksetzen nicht möglich (bereits an Fibu übergeben?)")
    return _abrechnung_dict(db, _load(db, abrechnung_id), with_details=True)
