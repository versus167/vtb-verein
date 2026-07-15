"""Mannschafts-Termine (#95, Spielbetrieb Etappe 1).

Zugriffsmodell (analog Kassen/Tresor, hier mit dem Kader als ACL): wer am Stichtag
aktiv im Kader einer Mannschaft steht (mitglied_mannschaft, von/bis), liest deren
Termine; die Kader-Rollen trainer/betreuer/uebungsleiter verwalten sie (anlegen,
bearbeiten, absagen, löschen). Nur das übergreifende Verwalten aller Mannschaften
hängt am globalen Recht `termine.verwalten`; Admins dürfen ohnehin alles.

Zeiten sind lokale Wandzeit als TEXT: beginn/ende 'YYYY-MM-DDTHH:MM',
treffpunkt_zeit 'HH:MM'. status wird nicht über PUT geändert, sondern über die
Aktions-Endpunkte /absagen und /reaktivieren (klare Audit-Intention; in Etappe 2
Hook für Benachrichtigungen). serie_id/extern_ref sind noch nicht per API setzbar
(kommen mit Terminserien bzw. DFBnet-Import).
"""
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.db.termin_repository import VALID_TYPEN
from app.db.termin_zusage_repository import VALID_ANTWORTEN
from app.db.termin_serie_repository import VALID_SERIE_TYPEN
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/termine", tags=["termine"])


# --------------------------------------------------------------------------- I/O
class TerminCreate(BaseModel):
    typ: str = 'training'
    beginn: str                              # 'YYYY-MM-DDTHH:MM'
    ende: Optional[str] = None
    ort: Optional[str] = None
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None    # 'HH:MM'
    gegner: Optional[str] = None             # nur typ='spiel'
    heim_auswaerts: Optional[str] = None     # 'heim' | 'auswaerts', nur typ='spiel'
    beschreibung: Optional[str] = None


class TerminUpdate(TerminCreate):
    expected_version: int


class TerminAktion(BaseModel):
    expected_version: int


class ZusageSet(BaseModel):
    antwort: str                             # 'zu' | 'vielleicht' | 'ab'
    kommentar: Optional[str] = None


class SerieCreate(BaseModel):
    typ: str = 'training'                    # 'training' | 'sonstiges' (keine Spiel-Serien)
    beginn_zeit: str                         # 'HH:MM'
    ende_zeit: Optional[str] = None
    ort: Optional[str] = None
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None    # 'HH:MM'
    beschreibung: Optional[str] = None
    start_datum: str                         # 'YYYY-MM-DD' (Anker = Wochentag, später fix)
    ende_datum: Optional[str] = None         # None = offenes Ende


class SerieUpdate(BaseModel):
    """Volle Serien-Bearbeitung – nur start_datum/Wochentag bleibt fix."""
    typ: str = 'training'
    beginn_zeit: str
    ende_zeit: Optional[str] = None
    ort: Optional[str] = None
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None
    beschreibung: Optional[str] = None
    ende_datum: Optional[str] = None
    expected_version: int


# ----------------------------------------------------------------- Authorisierung
def _darf_alle_verwalten(user) -> bool:
    return user.role == 'admin' or user.has_permission(Permission.TERMINE_VERWALTEN)


def _zugriff(db: DB, user, mannschaft_id: int) -> Optional[str]:
    """Effektive Stufe auf die Termine einer Mannschaft: 'verwalten' | 'lesen' | None.
    termine.verwalten/Admin => 'verwalten', sonst entscheidet der Kader."""
    if _darf_alle_verwalten(user):
        return 'verwalten'
    return db.termine.get_access_for_user(user.id, mannschaft_id)


def _require_lesen(db: DB, user, mannschaft_id: int) -> str:
    z = _zugriff(db, user, mannschaft_id)
    if z is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Kein Zugriff auf die Termine dieser Mannschaft")
    return z


def _require_verwalten(db: DB, user, mannschaft_id: int) -> None:
    if _zugriff(db, user, mannschaft_id) != 'verwalten':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung, Termine dieser Mannschaft zu verwalten")


# ------------------------------------------------------------------- Validierung
def _parse_wandzeit(wert: str, feld: str) -> datetime:
    try:
        return datetime.fromisoformat(wert)
    except ValueError:
        raise HTTPException(422, f"{feld} muss das Format JJJJ-MM-TTTHH:MM haben")


def _validate_termin(data: TerminCreate) -> None:
    """Prüft Typ/Zeiten/Spielfelder und normalisiert Nicht-Spiel-Termine
    (gegner/heim_auswaerts werden dort serverseitig genullt)."""
    if data.typ not in VALID_TYPEN:
        raise HTTPException(422, f"Ungültiger Typ (erlaubt: {', '.join(VALID_TYPEN)})")
    beginn = _parse_wandzeit(data.beginn, "beginn")
    if data.ende:
        if _parse_wandzeit(data.ende, "ende") < beginn:
            raise HTTPException(422, "Ende darf nicht vor dem Beginn liegen")
    else:
        data.ende = None
    if data.typ == 'spiel':
        if data.heim_auswaerts not in (None, 'heim', 'auswaerts'):
            raise HTTPException(422, "heim_auswaerts muss 'heim' oder 'auswaerts' sein")
    else:
        data.gegner = None
        data.heim_auswaerts = None
    for feld in ('ort', 'treffpunkt', 'gegner', 'beschreibung'):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(data, feld, wert.strip() or None)


def _clean(s: Optional[str]) -> Optional[str]:
    return (s.strip() or None) if s is not None else None


def _parse_uhrzeit(wert: str, feld: str) -> None:
    try:
        datetime.strptime(wert, '%H:%M')
    except (TypeError, ValueError):
        raise HTTPException(422, f"{feld} muss das Format HH:MM haben")


def _parse_datum(wert: str, feld: str) -> None:
    try:
        date.fromisoformat(wert)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{feld} muss das Format JJJJ-MM-TT haben")


def _validate_serie(data) -> None:
    """Gemeinsame Feld-Validierung für SerieCreate/SerieUpdate (normalisiert Strings)."""
    if data.typ not in VALID_SERIE_TYPEN:
        raise HTTPException(422, f"Ungültiger Typ (erlaubt: {', '.join(VALID_SERIE_TYPEN)})")
    _parse_uhrzeit(data.beginn_zeit, "beginn_zeit")
    if data.ende_zeit:
        _parse_uhrzeit(data.ende_zeit, "ende_zeit")
        if data.ende_zeit <= data.beginn_zeit:
            raise HTTPException(422, "ende_zeit muss nach beginn_zeit liegen")
    else:
        data.ende_zeit = None
    if data.treffpunkt_zeit:
        _parse_uhrzeit(data.treffpunkt_zeit, "treffpunkt_zeit")
    else:
        data.treffpunkt_zeit = None
    if data.ende_datum:
        _parse_datum(data.ende_datum, "ende_datum")
    else:
        data.ende_datum = None
    for feld in ('ort', 'treffpunkt', 'beschreibung'):
        setattr(data, feld, _clean(getattr(data, feld)))


def _validate_antwort(antwort: str) -> None:
    if antwort not in VALID_ANTWORTEN:
        raise HTTPException(422, f"Ungültige Antwort (erlaubt: {', '.join(VALID_ANTWORTEN)})")


def _lade_termin(db: DB, termin_id: int):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    return t


def _require_nicht_abgesagt(t) -> None:
    """Abgesagte Termine frieren die Zu-/Absagen ein (auch Zurücknehmen) –
    erst Reaktivieren macht sie wieder änderbar."""
    if t.status == 'abgesagt':
        raise HTTPException(422, "Termin ist abgesagt – Zu-/Absagen sind gesperrt")


# --------------------------------------------------------------------- Zusagen
def _enrich_zusagen(db: DB, user, termine: list[dict]) -> list[dict]:
    """Reichert Termin-Dicts (asdict) um RSVP-Infos an: `zusagen` (Zähler je
    Antwort), `meine_antwort` (eigene aktive Antwort | None) und `kann_zusagen`
    (ob der User als aktives Kader-Mitglied am Termin-Datum selbst antworten darf)."""
    if not termine:
        return termine
    ids = [t['id'] for t in termine]
    counts = db.termin_zusagen.counts_for_termine(ids)
    mitglied = db.get_mitglied_by_user_id(user.id)
    mitglied_id = mitglied.id if mitglied else None
    meine = db.termin_zusagen.answer_for(mitglied_id, ids) if mitglied_id else {}
    kader_cache: dict[tuple, bool] = {}
    for t in termine:
        tag = (t.get('beginn') or '')[:10] or None
        key = (t['mannschaft_id'], tag)
        if key not in kader_cache:
            kader_cache[key] = (
                mitglied_id is not None
                and db.termine.get_kader_mitglied_id(user.id, t['mannschaft_id'], tag) is not None
            )
        t['zusagen'] = counts.get(t['id'], {'zu': 0, 'vielleicht': 0, 'ab': 0})
        t['meine_antwort'] = meine.get(t['id'])
        t['kann_zusagen'] = kader_cache[key]
    return termine


# ------------------------------------------------------------------ Mannschaften
@router.get("/mannschaften")
def list_meine_mannschaften(user: CurrentUser, db: DB):
    """Mannschaften, deren Termine der User sehen/verwalten darf – dient dem
    Frontend auch als ACL-Probe (leere Liste => Nav-Punkt ausblenden)."""
    if _darf_alle_verwalten(user):
        return db.termine.list_all_mannschaften()
    return db.termine.list_mannschaften_for_user(user.id)


@router.get("/mannschaften/{mannschaft_id}")
def list_termine(mannschaft_id: int, user: CurrentUser, db: DB,
                 von: Optional[str] = None, bis: Optional[str] = None):
    """Termine einer Mannschaft (von/bis = ISO-Datum, beide inklusiv)."""
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    zugriff = _require_lesen(db, user, mannschaft_id)
    db.termin_serien.materialize_due([mannschaft_id])   # Serien rollierend nachziehen
    termine = db.termine.list_for_mannschaft(mannschaft_id, von=von, bis=bis)
    return {
        "zugriff": zugriff,
        "darf_verwalten": zugriff == 'verwalten',
        "termine": _enrich_zusagen(db, user, [asdict(t) for t in termine]),
    }


@router.post("/mannschaften/{mannschaft_id}", status_code=status.HTTP_201_CREATED)
def create_termin(mannschaft_id: int, data: TerminCreate, user: CurrentUser, db: DB):
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    _require_verwalten(db, user, mannschaft_id)
    _validate_termin(data)
    t = db.termine.create(
        mannschaft_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username,
    )
    return asdict(t)


# ---------------------------------------------------------------- Meine Termine
@router.get("/meine")
def meine_termine(user: CurrentUser, db: DB,
                  von: Optional[str] = None, bis: Optional[str] = None):
    """Termine aller Mannschaften, in deren Kader der User aktiv steht.
    Ohne von-Filter ab heute (Vergangenes blendet das Frontend explizit ein)."""
    if von is None and bis is None:
        von = date.today().isoformat()
    db.termin_serien.materialize_due()   # alle fälligen Serien rollierend nachziehen
    return _enrich_zusagen(db, user, db.termine.list_for_user(user.id, von=von, bis=bis))


# --------------------------------------------------------------- Einzel-Termine
@router.put("/{termin_id}")
def update_termin(termin_id: int, data: TerminUpdate, user: CurrentUser, db: DB):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    _validate_termin(data)
    ok = db.termine.update(
        termin_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username, data.expected_version,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.termine.get(termin_id))


def _set_status(termin_id: int, neuer_status: str, data: TerminAktion,
                user, db: DB) -> dict:
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    if t.status == neuer_status:
        raise HTTPException(422, f"Termin ist bereits '{neuer_status}'")
    ok = db.termine.set_status(termin_id, neuer_status, user.username,
                               data.expected_version)
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.termine.get(termin_id))


@router.post("/{termin_id}/absagen")
def absagen(termin_id: int, data: TerminAktion, user: CurrentUser, db: DB):
    return _set_status(termin_id, 'abgesagt', data, user, db)


@router.post("/{termin_id}/reaktivieren")
def reaktivieren(termin_id: int, data: TerminAktion, user: CurrentUser, db: DB):
    return _set_status(termin_id, 'geplant', data, user, db)


@router.delete("/{termin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_termin(termin_id: int, user: CurrentUser, db: DB):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    db.termine.mark_deleted(termin_id, user.username)


# ------------------------------------------------------------- Zu-/Absagen (RSVP)
@router.put("/{termin_id}/zusage")
def set_eigene_zusage(termin_id: int, data: ZusageSet, user: CurrentUser, db: DB):
    """Eigene Zu-/Absage. Verlangt Lese-Zugriff auf die Mannschaft UND ein aktives
    Kader-Mitglied des Users am Termin-Datum. Bei 'ab'/'vielleicht' ist ein
    Kommentar Pflicht (Begründung, im Kader-Dialog für die ganze Mannschaft
    sichtbar) – bewusst NUR hier, nicht im On-behalf-Endpunkt (Verwalter tragen
    z. B. telefonische Absagen formlos ein)."""
    t = _lade_termin(db, termin_id)
    _require_lesen(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    _validate_antwort(data.antwort)
    kommentar = _clean(data.kommentar)
    if data.antwort in ('vielleicht', 'ab') and not kommentar:
        raise HTTPException(422, "Bei Absage/Vielleicht ist ein kurzer Kommentar erforderlich")
    mitglied_id = db.termine.get_kader_mitglied_id(user.id, t.mannschaft_id, t.beginn[:10])
    if mitglied_id is None:
        raise HTTPException(403, "Nur aktive Kader-Mitglieder können zu-/absagen")
    z = db.termin_zusagen.set_antwort(termin_id, mitglied_id, data.antwort,
                                      kommentar, user.username)
    return asdict(z)


@router.put("/{termin_id}/zusage/{mitglied_id}")
def set_fremde_zusage(termin_id: int, mitglied_id: int, data: ZusageSet,
                      user: CurrentUser, db: DB):
    """Zu-/Absage für ein anderes Kader-Mitglied setzen (nur Verwalter)."""
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    _validate_antwort(data.antwort)
    if not db.termine.is_mitglied_in_kader(mitglied_id, t.mannschaft_id, t.beginn[:10]):
        raise HTTPException(422, "Mitglied ist am Termin-Datum nicht im Kader")
    z = db.termin_zusagen.set_antwort(termin_id, mitglied_id, data.antwort,
                                      _clean(data.kommentar), user.username)
    return asdict(z)


@router.delete("/{termin_id}/zusage", status_code=status.HTTP_204_NO_CONTENT)
def remove_eigene_zusage(termin_id: int, user: CurrentUser, db: DB):
    """Eigene Zu-/Absage zurücknehmen (Soft-Delete)."""
    t = _lade_termin(db, termin_id)
    _require_lesen(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    mitglied_id = db.termine.get_kader_mitglied_id(user.id, t.mannschaft_id, t.beginn[:10])
    if mitglied_id is None:
        raise HTTPException(403, "Nur aktive Kader-Mitglieder können zu-/absagen")
    db.termin_zusagen.remove_antwort(termin_id, mitglied_id, user.username)


@router.delete("/{termin_id}/zusage/{mitglied_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_fremde_zusage(termin_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    """Zu-/Absage eines anderen Kader-Mitglieds zurücknehmen (nur Verwalter)."""
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    db.termin_zusagen.remove_antwort(termin_id, mitglied_id, user.username)


@router.get("/{termin_id}/kader")
def kader_mit_zusagen(termin_id: int, user: CurrentUser, db: DB):
    """Aktiver Kader der Termin-Mannschaft (Stichtag = Termin-Datum) inkl. Antworten –
    für den Kader-/Übersichtsdialog. Verlangt Lese-Zugriff."""
    t = _lade_termin(db, termin_id)
    zugriff = _require_lesen(db, user, t.mannschaft_id)
    return {
        "darf_verwalten": zugriff == 'verwalten',
        "kader": db.termin_zusagen.list_kader_with_zusage(termin_id),
    }


# ----------------------------------------------------------------- Terminserien
@router.get("/mannschaften/{mannschaft_id}/serien")
def list_serien(mannschaft_id: int, user: CurrentUser, db: DB):
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    zugriff = _require_lesen(db, user, mannschaft_id)
    return {
        "darf_verwalten": zugriff == 'verwalten',
        "serien": [asdict(s) for s in db.termin_serien.list_for_mannschaft(mannschaft_id)],
    }


@router.post("/mannschaften/{mannschaft_id}/serien", status_code=status.HTTP_201_CREATED)
def create_serie(mannschaft_id: int, data: SerieCreate, user: CurrentUser, db: DB):
    if db.get_mannschaft(mannschaft_id) is None:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    _require_verwalten(db, user, mannschaft_id)
    _validate_serie(data)
    _parse_datum(data.start_datum, "start_datum")
    if data.ende_datum and data.ende_datum < data.start_datum:
        raise HTTPException(422, "ende_datum darf nicht vor start_datum liegen")
    s = db.termin_serien.create(
        mannschaft_id, data.typ, data.beginn_zeit, data.ende_zeit, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.beschreibung,
        data.start_datum, data.ende_datum, user.username,
    )
    db.termin_serien.materialize_due([mannschaft_id])   # Instanzen sofort erzeugen
    return asdict(db.termin_serien.get(s.id))


@router.put("/serien/{serie_id}")
def update_serie(serie_id: int, data: SerieUpdate, user: CurrentUser, db: DB):
    """Volle Serien-Bearbeitung: neue Werte gelten für zukünftige, noch unveränderte,
    geplante Instanzen; individuell geänderte/abgesagte/vergangene bleiben unberührt.
    Wochentag (start_datum) ist fix – dafür Serie löschen und neu anlegen."""
    s = db.termin_serien.get(serie_id)
    if s is None:
        raise HTTPException(404, "Serie nicht gefunden")
    _require_verwalten(db, user, s.mannschaft_id)
    _validate_serie(data)
    if data.ende_datum and data.ende_datum < s.start_datum:
        raise HTTPException(422, "ende_datum darf nicht vor start_datum liegen")
    ok = db.termin_serien.update(
        serie_id, data.typ, data.beginn_zeit, data.ende_zeit, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.beschreibung, data.ende_datum,
        user.username, data.expected_version,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    db.termin_serien.materialize_due([s.mannschaft_id])   # bei Verlängerung nachziehen
    return asdict(db.termin_serien.get(serie_id))


@router.delete("/serien/{serie_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_serie(serie_id: int, user: CurrentUser, db: DB):
    """Serie löschen: ALLE Instanzen ab heute werden mit entfernt, Vergangenheit bleibt."""
    s = db.termin_serien.get(serie_id)
    if s is None:
        raise HTTPException(404, "Serie nicht gefunden")
    _require_verwalten(db, user, s.mannschaft_id)
    db.termin_serien.mark_deleted(serie_id, user.username)
