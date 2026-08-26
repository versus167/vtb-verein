"""Mannschafts-Termine (#95, Spielbetrieb Etappe 1).

Zugriffsmodell (analog Kassen/Tresor, hier mit dem Kader als ACL): wer am Stichtag
aktiv im Kader einer Mannschaft steht (mitglied_mannschaft, von/bis), liest deren
Termine; die Kader-Rollen betreuer/uebungsleiter verwalten sie (anlegen,
bearbeiten, absagen, löschen). Nur das übergreifende Verwalten aller Mannschaften
hängt am globalen Recht `termine.verwalten`; Admins dürfen ohnehin alles.

Zeiten sind lokale Wandzeit als TEXT: beginn/ende 'YYYY-MM-DDTHH:MM',
treffpunkt_zeit 'HH:MM'. status wird nicht über PUT geändert, sondern über die
Aktions-Endpunkte /absagen und /reaktivieren (klare Audit-Intention).

Benachrichtigungen sind Opt-in: Anlegen/Bearbeiten/Absagen/Reaktivieren (und die
Serien-Anlage) nehmen ein `benachrichtigen`-Flag entgegen; der Kader wird dann
über termin_notification_service informiert (beim Bearbeiten nur, wenn sich
fachlich etwas geändert hat). extern_ref ist noch nicht per API setzbar
(kommt mit dem DFBnet-Import).

Erinnerungen (#95-Nachgang): Ein Sidecar-Lauf (termin_erinnerung_service) erinnert
kurz vor dem Termin – und am Spieltag selbst – die, von denen noch keine Meldung
vorliegt. Den Vorlauf setzt `/erinnerung-einstellungen` – vereinsweit, deshalb am
globalen Recht `termine.verwalten` statt an der Kader-ACL.

Gäste: Verwalter können Mitglieder derselben ABTEILUNG (unabhängig von einer
eigenen Kader-Zugehörigkeit) als Gäste zu einem Termin eintragen (z. B.
AH-Spieler hilft in der Ersten aus). Mit dem Recht `termine.gaeste_vereinsweit`
fällt die Abteilungsgrenze weg – für die gelegentliche abteilungsübergreifende
Runde (Vorstand, einmal im Jahr die Abteilungsleiter).
Gast = aktive Zeile ohne Kader-Zugehörigkeit am Termin-Datum, keine eigene
Tabelle. Zwei Wege dorthin: eintragen (Verwalter sagt FÜR jemanden zu) oder
einladen (Zeile mit antwort NULL, Antwort steht aus – /einladungen). Gäste sehen
genau diesen Termin unter „Meine Termine", dürfen ihre Antwort selbst ändern und
werden mitbenachrichtigt; Zurücknehmen der Antwort beendet den Gast-Status.
"""
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.spielstaette_repository import PLATZHALTER_UNBEKANNT
from app.models.permission import Permission
from app.models.termin import TerminErinnerungEinstellungen
from app.db.termin_repository import VALID_TYPEN
from app.db.termin_abweichung_repository import (
    FELD_ENTFALLEN, STATUS_OFFEN, STATUS_UEBERNOMMEN, VALID_ENTSCHEIDUNGEN,
)
from app.db.termin_zusage_repository import VALID_ANTWORTEN
from app.db.termin_serie_repository import VALID_SERIE_TYPEN
from app.services import dfbnet_import_service as dfbnet
from app.services import termin_notification_service as terminmeldung
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/termine", tags=["termine"])


# --------------------------------------------------------------------------- I/O
class TerminCreate(BaseModel):
    typ: str = 'training'
    beginn: str                              # 'YYYY-MM-DDTHH:MM'
    ende: Optional[str] = None
    ort: Optional[str] = None
    spielstaette_id: int                     # Pflicht seit v80 (#95)
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None    # 'HH:MM'
    gegner: Optional[str] = None             # nur typ='spiel'
    heim_auswaerts: Optional[str] = None     # 'heim' | 'auswaerts', nur typ='spiel'
    beschreibung: Optional[str] = None
    benachrichtigen: bool = False            # Opt-in: Kader informieren


class TerminUpdate(TerminCreate):
    expected_version: int


class TerminAktion(BaseModel):
    expected_version: int
    benachrichtigen: bool = False            # Opt-in: Kader informieren


class ZusageSet(BaseModel):
    antwort: str                             # 'zu' | 'vielleicht' | 'ab'
    kommentar: Optional[str] = None


class EinladungCreate(BaseModel):
    """Einladung mehrerer Mitglieder zu einem Termin (Schnappschuss der Auswahl)."""
    mitglied_ids: list[int]
    benachrichtigen: bool = True


class AbweichungEntscheidung(BaseModel):
    """Entscheidung über eine offene Abweichung aus dem Spielplan-Import (#95)."""
    entscheidung: str                        # 'uebernommen' | 'verworfen'
    expected_version: int
    benachrichtigen: bool = False            # Opt-in: Kader informieren


class DfbnetUebernahme(BaseModel):
    """Termin auf den zuletzt importierten DFBnet-Stand ziehen (#95)."""
    expected_version: int
    benachrichtigen: bool = False            # Opt-in: Kader informieren


class SerieCreate(BaseModel):
    typ: str = 'training'                    # 'training' | 'sonstiges' (keine Spiel-Serien)
    beginn_zeit: str                         # 'HH:MM'
    spielstaette_id: int                     # Pflicht seit v80 (#95)
    ende_zeit: Optional[str] = None
    ort: Optional[str] = None
    treffpunkt: Optional[str] = None
    treffpunkt_zeit: Optional[str] = None    # 'HH:MM'
    beschreibung: Optional[str] = None
    start_datum: str                         # 'YYYY-MM-DD' (Anker = Wochentag, später fix)
    ende_datum: Optional[str] = None         # None = offenes Ende
    benachrichtigen: bool = False            # Opt-in: Kader informieren


class SerieUpdate(BaseModel):
    """Volle Serien-Bearbeitung – nur start_datum/Wochentag bleibt fix."""
    typ: str = 'training'
    beginn_zeit: str
    spielstaette_id: int                     # Pflicht seit v80 (#95)
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


def _require_alle_verwalten(user) -> None:
    """Für vereinsweite Einstellungen (Erinnerungs-Vorlauf): Die Kader-ACL hilft
    hier nicht weiter – die Zeile gilt für alle Mannschaften."""
    if not _darf_alle_verwalten(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung, Termine zu verwalten")


def _darf_vereinsweit_einladen(user) -> bool:
    """Gäste über die Abteilung der Mannschaft hinaus auswählen dürfen.

    Erweitert NUR den Kreis der Auswählbaren – wer den Termin verwalten darf,
    entscheidet weiterhin die Kader-ACL bzw. termine.verwalten.
    """
    return user.role == 'admin' or user.has_permission(
        Permission.TERMINE_GAESTE_VEREINSWEIT)


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


def _require_gast_erlaubt(db: DB, user, t, mitglied_id: int, tag: str) -> None:
    """Darf dieses Mitglied an diesem Termin hängen (Kader, Abteilung – oder alle)?

    Gemeinsame Prüfung für das Eintragen einer Antwort und für die Einladung:
    Beide erzeugen dieselbe Zeile und dürfen sich deshalb nicht unterscheiden.
    """
    if db.termine.is_mitglied_in_kader(mitglied_id, t.mannschaft_id, tag):
        return
    if _darf_vereinsweit_einladen(user):
        try:
            db.get_mitglied(mitglied_id)
        except KeyError:
            raise HTTPException(422, "Mitglied nicht gefunden")
        return
    if not db.termine.is_mitglied_in_abteilung(mitglied_id, t.mannschaft_id, tag):
        raise HTTPException(422, "Mitglied ist am Termin-Datum weder im Kader noch "
                                 "Mitglied der Abteilung")


def _require_lesen_termin(db: DB, user, t) -> str:
    """Lese-Zugriff auf einen konkreten Termin: Kader-ACL der Mannschaft ODER
    Gast (eigene aktive Zu-/Absage zu genau diesem Termin)."""
    z = _zugriff(db, user, t.mannschaft_id)
    if z is not None:
        return z
    if db.termin_zusagen.has_active_zusage(t.id, user.id):
        return 'lesen'
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Kein Zugriff auf diesen Termin")


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


def _require_spielstaette(db: DB, spielstaette_id: int) -> None:
    """Spielstätte muss existieren und auswählbar sein.

    'unbekannt' („Nicht erfasst") trägt ausschließlich den Altbestand aus der
    Migration – wer einen Termin speichert, muss sich festlegen (echte Spielstätte
    oder ausdrücklich „Kein Vereinsgelände"). Sonst wäre der spätere
    Belegungsplan dauerhaft löchrig.
    """
    s = db.spielstaetten.get(spielstaette_id)
    if s is None:
        raise HTTPException(422, "Spielstätte nicht gefunden")
    if s.platzhalter == PLATZHALTER_UNBEKANNT:
        raise HTTPException(
            422,
            'Bitte eine Spielstätte wählen (oder ausdrücklich „Kein Vereinsgelände“)',
        )


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


def _eigenes_rsvp_mitglied(db: DB, user, t) -> int:
    """mitglied_id für die eigene Zu-/Absage: aktives Kader-Mitglied am
    Termin-Datum oder Gast (eigenes Mitglied mit bestehender Antwort)."""
    mitglied_id = db.termine.get_kader_mitglied_id(user.id, t.mannschaft_id, t.beginn[:10])
    if mitglied_id is not None:
        return mitglied_id
    mitglied = db.get_mitglied_by_user_id(user.id)
    if mitglied is not None and db.termin_zusagen.has_active_zusage(t.id, user.id):
        return mitglied.id
    raise HTTPException(403, "Nur Kader-Mitglieder oder eingetragene Gäste können zu-/absagen")


def _require_nicht_abgesagt(t) -> None:
    """Abgesagte Termine frieren die Zu-/Absagen ein (auch Zurücknehmen) –
    erst Reaktivieren macht sie wieder änderbar."""
    if t.status == 'abgesagt':
        raise HTTPException(422, "Termin ist abgesagt – Zu-/Absagen sind gesperrt")


# --------------------------------------------------------------------- Zusagen
def _enrich_zusagen(db: DB, user, termine: list[dict]) -> list[dict]:
    """Reichert Termin-Dicts (asdict) um RSVP-Infos an: `zusagen` (Zähler je
    Antwort), `meine_antwort` (eigene aktive Antwort | None) und `kann_zusagen`
    (aktives Kader-Mitglied am Termin-Datum ODER Gast mit bestehender Antwort)."""
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
        t['kann_zusagen'] = kader_cache[key] or t['id'] in meine
    _enrich_abweichungen(db, termine)
    return termine


def _extern_diff(t: dict) -> list[dict]:
    """Felder, in denen der Termin heute vom zuletzt importierten DFBnet-Stand
    abweicht — unabhängig davon, ob je jemand danach gefragt wurde.

    Deckt die stillen Fälle ab, für die es keine offene Frage (mehr) gibt: eine
    verworfene Abweichung, und die Änderung, die das Team ohne Gegenstück im
    Export gemacht hat. Der Import lässt beides bewusst stehen — sichtbar bleiben
    sollte es trotzdem, denn das DFBnet ist die offizielle Ansetzung und hinkt
    womöglich nur hinterher. Wer das beurteilen kann, ist der Betreuer.
    """
    stand = t.get('extern_stand') or {}
    return [{'feld': f, 'dfbnet': stand.get(f)}
            for f in dfbnet.VERGLEICHSFELDER
            if f in stand and t.get(f) != stand.get(f)]


def _enrich_abweichungen(db: DB, termine: list[dict]) -> None:
    """`abweichungen_offen` und `extern_diff` je Termin – Grundlage der Hinweise
    an der Terminkarte (#95).

    Beides hängt an keiner Berechtigung: Entscheiden darf nur, wer die Termine der
    Mannschaft verwaltet, aber weder der Zähler noch der Vergleich verraten etwas,
    was der Kader nicht ohnehin am Termin sähe.
    """
    offen = db.termin_abweichungen.counts_offen([t['id'] for t in termine])
    for t in termine:
        t['abweichungen_offen'] = offen.get(t['id'], 0)
        t['extern_diff'] = _extern_diff(t)


# ------------------------------------------------------------------ Mannschaften
@router.get("/mannschaften")
def list_meine_mannschaften(user: CurrentUser, db: DB):
    """Mannschaften, deren Termine der User sehen/verwalten darf – dient dem
    Frontend auch als ACL-Probe (leere Liste => Nav-Punkt ausblenden).

    `eigen` trennt die eigenen Kader-Mannschaften von denen, die nur über
    `termine.verwalten`/Admin dazukommen. Das Frontend blendet standardmäßig nur
    die eigenen ein: Wer alle Termine verwalten darf, will trotzdem nicht bei
    jedem Aufruf 30 Mannschafts-Tabs sehen.
    """
    if not _darf_alle_verwalten(user):
        return [m | {"eigen": True} for m in db.termine.list_mannschaften_for_user(user.id)]
    eigene = {m['id'] for m in db.termine.list_mannschaften_for_user(user.id)}
    return [m | {"eigen": m['id'] in eigene} for m in db.termine.list_all_mannschaften()]


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
    _require_spielstaette(db, data.spielstaette_id)
    t = db.termine.create(
        mannschaft_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username, spielstaette_id=data.spielstaette_id,
    )
    if data.benachrichtigen:
        terminmeldung.notify_termin(db, t, terminmeldung.AKTION_NEU, user.id)
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


# ------------------------------------------------------------------ Erinnerungen
# Vor den Einzel-Termin-Routen: `/{termin_id}` würde „erinnerung-einstellungen"
# sonst als Termin-Nummer lesen.

# Obergrenze des Vorlaufs. Vier Wochen sind großzügig – wer drei Monate vorher
# erinnert, hat sich vertippt; abschalten geht über die 0 bzw. den Schalter.
VORLAUF_MAX_TAGE = 28


class ErinnerungEinstellungenWrite(BaseModel):
    aktiv: bool = True
    erste_stufe_tage: int = Field(3, ge=0, le=VORLAUF_MAX_TAGE)
    zweite_stufe_tage: int = Field(1, ge=0, le=VORLAUF_MAX_TAGE)
    # Am Termintag selbst – nur zu Spielen und nur vor dem Anpfiff (kein Vorlauf,
    # daher ein Schalter und keine Tageszahl).
    spieltag_aktiv: bool = True


@router.get("/erinnerung-einstellungen")
def erinnerung_einstellungen_lesen(user: CurrentUser, db: DB):
    """Vorlauf der Termin-Erinnerungen. Am globalen Recht, nicht an der Kader-ACL:
    Die Zeile gilt für den ganzen Verein, nicht für eine Mannschaft."""
    _require_alle_verwalten(user)
    return asdict(db.termin_erinnerung_einstellungen.get())


@router.put("/erinnerung-einstellungen")
def erinnerung_einstellungen_speichern(data: ErinnerungEinstellungenWrite,
                                       user: CurrentUser, db: DB):
    """Vorlauf speichern. Stufe 0 heißt: diese Stufe nicht erinnern – der obere
    Schalter schaltet den ganzen Lauf ab, `spieltag_aktiv` nur die Stufe am
    Termintag."""
    _require_alle_verwalten(user)
    einstellungen = TerminErinnerungEinstellungen(**data.model_dump())
    return asdict(db.termin_erinnerung_einstellungen.update(
        einstellungen, updated_by=user.username))


# --------------------------------------------------------------- Einzel-Termine
@router.put("/{termin_id}")
def update_termin(termin_id: int, data: TerminUpdate, user: CurrentUser, db: DB):
    t = db.termine.get(termin_id)
    if t is None:
        raise HTTPException(404, "Termin nicht gefunden")
    _require_verwalten(db, user, t.mannschaft_id)
    _validate_termin(data)
    _require_spielstaette(db, data.spielstaette_id)
    ok = db.termine.update(
        termin_id, data.typ, data.beginn, data.ende, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.gegner, data.heim_auswaerts,
        data.beschreibung, user.username, data.expected_version,
        spielstaette_id=data.spielstaette_id,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    neu = db.termine.get(termin_id)
    if data.benachrichtigen:
        aenderungen = terminmeldung.diff_termin(t, neu)
        if aenderungen:   # No-Op-Speichern erzeugt keine Nachricht
            terminmeldung.notify_termin(db, neu, terminmeldung.AKTION_GEAENDERT,
                                        user.id, aenderungen)
    return asdict(neu)


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
    neu = db.termine.get(termin_id)
    if data.benachrichtigen:
        aktion = (terminmeldung.AKTION_ABGESAGT if neuer_status == 'abgesagt'
                  else terminmeldung.AKTION_REAKTIVIERT)
        terminmeldung.notify_termin(db, neu, aktion, user.id)
    return asdict(neu)


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
    """Eigene Zu-/Absage. Verlangt aktives Kader-Mitglied am Termin-Datum ODER
    Gast-Status (bestehende eigene Antwort zu diesem Termin). Bei 'ab'/'vielleicht'
    ist ein Kommentar Pflicht (Begründung, im Kader-Dialog für die ganze Mannschaft
    sichtbar) – bewusst NUR hier, nicht im On-behalf-Endpunkt (Verwalter tragen
    z. B. telefonische Absagen formlos ein)."""
    t = _lade_termin(db, termin_id)
    _require_lesen_termin(db, user, t)
    _require_nicht_abgesagt(t)
    _validate_antwort(data.antwort)
    kommentar = _clean(data.kommentar)
    if data.antwort in ('vielleicht', 'ab') and not kommentar:
        raise HTTPException(422, "Bei Absage/Vielleicht ist ein kurzer Kommentar erforderlich")
    mitglied_id = _eigenes_rsvp_mitglied(db, user, t)
    z = db.termin_zusagen.set_antwort(termin_id, mitglied_id, data.antwort,
                                      kommentar, user.username)
    return asdict(z)


@router.put("/{termin_id}/zusage/{mitglied_id}")
def set_fremde_zusage(termin_id: int, mitglied_id: int, data: ZusageSet,
                      user: CurrentUser, db: DB):
    """Zu-/Absage für ein anderes Mitglied setzen (nur Verwalter). Erlaubt für
    Kader-Mitglieder sowie – als Gast-Eintrag – für Mitglieder der Abteilung bzw.
    mit `termine.gaeste_vereinsweit` für jedes Mitglied."""
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    _validate_antwort(data.antwort)
    tag = t.beginn[:10]
    _require_gast_erlaubt(db, user, t, mitglied_id, tag)
    z = db.termin_zusagen.set_antwort(termin_id, mitglied_id, data.antwort,
                                      _clean(data.kommentar), user.username)
    return asdict(z)


@router.delete("/{termin_id}/zusage", status_code=status.HTTP_204_NO_CONTENT)
def remove_eigene_zusage(termin_id: int, user: CurrentUser, db: DB):
    """Eigene Zu-/Absage zurücknehmen (Soft-Delete). Für Gäste beendet das den
    Gast-Status – der Termin verschwindet aus „Meine Termine"."""
    t = _lade_termin(db, termin_id)
    _require_lesen_termin(db, user, t)
    _require_nicht_abgesagt(t)
    db.termin_zusagen.remove_antwort(termin_id, _eigenes_rsvp_mitglied(db, user, t),
                                     user.username)


@router.delete("/{termin_id}/zusage/{mitglied_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_fremde_zusage(termin_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    """Zu-/Absage eines anderen Kader-Mitglieds zurücknehmen (nur Verwalter)."""
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    db.termin_zusagen.remove_antwort(termin_id, mitglied_id, user.username)


@router.get("/{termin_id}/kader")
def kader_mit_zusagen(termin_id: int, user: CurrentUser, db: DB):
    """Aktiver Kader der Termin-Mannschaft (Stichtag = Termin-Datum) inkl. Antworten,
    plus Gäste – für den Kader-/Übersichtsdialog. Verlangt Lese-Zugriff
    (Kader oder Gast)."""
    t = _lade_termin(db, termin_id)
    zugriff = _require_lesen_termin(db, user, t)
    return {
        "darf_verwalten": zugriff == 'verwalten',
        "kader": db.termin_zusagen.list_kader_with_zusage(termin_id),
        "gaeste": db.termin_zusagen.list_gaeste_with_zusage(termin_id),
    }


@router.get("/{termin_id}/gast-kandidaten")
def gast_kandidaten(termin_id: int, user: CurrentUser, db: DB):
    """Kandidaten fürs Eintragen/Einladen durch Verwalter: Mitglieder außerhalb des
    eigenen Kaders (Stichtag = Termin-Datum), je Person mit Mannschaften und
    aktiven Funktionen als Label.

    Ohne `termine.gaeste_vereinsweit` auf die Abteilung der Mannschaft begrenzt;
    mit dem Recht der ganze Verein. Das Flag kommt mit zurück, damit die Oberfläche
    sagen kann, worin gerade gesucht wird.
    """
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    vereinsweit = _darf_vereinsweit_einladen(user)
    return {
        "vereinsweit": vereinsweit,
        "kandidaten": db.termine.list_gast_kandidaten(
            t.mannschaft_id, t.beginn[:10], vereinsweit=vereinsweit),
    }


@router.post("/{termin_id}/einladungen")
def lade_gaeste_ein(termin_id: int, data: EinladungCreate, user: CurrentUser, db: DB):
    """Mitglieder zu einem Termin einladen – ohne für sie zu antworten.

    Der Unterschied zum Eintragen (`PUT /zusage/{mitglied_id}`): Dort sagt der
    Verwalter FÜR jemanden zu, hier entsteht nur die Einladung (Zeile mit
    `antwort IS NULL`), und der Eingeladene antwortet selbst. Wer schon geantwortet
    hat, bleibt unangetastet.

    Ein Schnappschuss: Eingeladen wird, wer JETZT ausgewählt ist. Wechselt später
    jemand die Funktion, ändert das an dieser Einladungsliste nichts – für die
    einmalige Runde ist genau das gewollt.
    """
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    _require_nicht_abgesagt(t)
    tag = t.beginn[:10]
    neu = []
    for mitglied_id in dict.fromkeys(data.mitglied_ids):
        _require_gast_erlaubt(db, user, t, mitglied_id, tag)
        if db.termin_zusagen.lade_ein(termin_id, mitglied_id, user.username):
            neu.append(mitglied_id)
    if neu and data.benachrichtigen:
        terminmeldung.notify_einladung(db, t, neu, user.id)
    return {"eingeladen": len(neu), "schon_dabei": len(set(data.mitglied_ids)) - len(neu)}


# ------------------------------------------- Abweichungen aus dem Spielplan (#95)
@router.get("/{termin_id}/abweichungen")
def list_abweichungen(termin_id: int, user: CurrentUser, db: DB):
    """Offene und bereits entschiedene Abweichungen eines Termins.

    Verlangt Verwalten-Zugriff: Es ist die Arbeitsliste des Betreuers, nicht eine
    Information für den Kader – der sieht nur den fertigen Termin.
    """
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    return [asdict(a) for a in db.termin_abweichungen.list_for_termin(termin_id)]


@router.post("/{termin_id}/dfbnet-uebernehmen")
def uebernimm_dfbnet_stand(termin_id: int, data: DfbnetUebernahme,
                           user: CurrentUser, db: DB):
    """Den Termin auf den zuletzt importierten DFBnet-Stand ziehen.

    Für die stillen Abweichungen, zu denen der Import bewusst nicht (mehr) fragt:
    eine verworfene Frage oder eine Änderung des Teams ohne Gegenstück im Export.
    Der Weg über die offene Abweichung bleibt davon unberührt — hier gibt es keine
    Zeile zu entscheiden, nur den Ist-Vergleich aus `extern_stand`.

    Der Ort wandert nur mit, wenn der Schnappschuss die zugehörige Spielstätte
    kennt: Ein Ort-Text ohne passenden Platz ließe die Belegung falsch aussehen.
    Ältere Schnappschüsse (vor dieser Änderung) haben sie nicht — dann bleibt der
    Ort stehen und die Antwort sagt es.
    """
    t = _lade_termin(db, termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    if t.version != data.expected_version:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")

    stand = t.extern_stand or {}
    diff = _extern_diff(asdict(t))
    if not diff:
        raise HTTPException(422, "Termin entspricht bereits dem DFBnet-Stand")

    platz_id = stand.get('spielstaette_id')
    werte = {d['feld']: d['dfbnet'] for d in diff
             if d['feld'] != 'ort' or platz_id is not None}
    ausgelassen = [d['feld'] for d in diff if d['feld'] not in werte]
    if not werte:
        raise HTTPException(
            422, "Zum Ort fehlt die Spielstätte im letzten Importstand – bitte den "
                 "Platz im Termin von Hand setzen")

    vorher = t
    if not db.termine.update_aus_import(
            termin_id, werte=werte, extern_stand=stand,
            spielstaette_id=platz_id if 'ort' in werte else None,
            updated_by=user.username, expected_version=t.version):
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")

    neu = db.termine.get(termin_id)
    if data.benachrichtigen:
        aenderungen = terminmeldung.diff_termin(vorher, neu)
        if aenderungen:
            terminmeldung.notify_termin(db, neu, terminmeldung.AKTION_GEAENDERT,
                                        user.id, aenderungen)
    return {"termin": asdict(neu), "uebernommen": sorted(werte),
            "ausgelassen": ausgelassen}


@router.post("/abweichungen/{abweichung_id}/entscheiden")
def entscheide_abweichung(abweichung_id: int, data: AbweichungEntscheidung,
                          user: CurrentUser, db: DB):
    """Eine offene Abweichung übernehmen oder verwerfen.

    Beide Wege schreiben den Import-Schnappschuss fort — die Frage wird dadurch
    beim nächsten Lauf nicht erneut gestellt. „Übernehmen" bei einem entfallenen
    Spiel sagt den Termin ab; gelöscht wird nie automatisch.
    """
    a = db.termin_abweichungen.get(abweichung_id)
    if a is None:
        raise HTTPException(404, "Abweichung nicht gefunden")
    t = _lade_termin(db, a.termin_id)
    _require_verwalten(db, user, t.mannschaft_id)
    if data.entscheidung not in VALID_ENTSCHEIDUNGEN:
        raise HTTPException(
            422, f"Ungültige Entscheidung (erlaubt: {', '.join(VALID_ENTSCHEIDUNGEN)})")
    if a.status != STATUS_OFFEN:
        raise HTTPException(422, "Abweichung ist bereits entschieden")
    if a.version != data.expected_version:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")

    def _melden(neu, vorher):
        if a.feld == FELD_ENTFALLEN:
            terminmeldung.notify_termin(db, neu, terminmeldung.AKTION_ABGESAGT, user.id)
            return
        aenderungen = terminmeldung.diff_termin(vorher, neu)
        if aenderungen:
            terminmeldung.notify_termin(db, neu, terminmeldung.AKTION_GEAENDERT,
                                        user.id, aenderungen)

    ok = dfbnet.entscheiden(
        db, a, data.entscheidung, actor=user.username,
        notify=_melden if data.benachrichtigen else None)
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return {
        "abweichung": asdict(db.termin_abweichungen.get(abweichung_id)),
        "termin": asdict(db.termine.get(a.termin_id)),
        "uebernommen": data.entscheidung == STATUS_UEBERNOMMEN,
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
    _require_spielstaette(db, data.spielstaette_id)
    _parse_datum(data.start_datum, "start_datum")
    if data.ende_datum and data.ende_datum < data.start_datum:
        raise HTTPException(422, "ende_datum darf nicht vor start_datum liegen")
    s = db.termin_serien.create(
        mannschaft_id, data.typ, data.beginn_zeit, data.ende_zeit, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.beschreibung,
        data.start_datum, data.ende_datum, user.username,
        spielstaette_id=data.spielstaette_id,
    )
    db.termin_serien.materialize_due([mannschaft_id])   # Instanzen sofort erzeugen
    if data.benachrichtigen:
        terminmeldung.notify_serie(db, s, user.id)
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
    _require_spielstaette(db, data.spielstaette_id)
    if data.ende_datum and data.ende_datum < s.start_datum:
        raise HTTPException(422, "ende_datum darf nicht vor start_datum liegen")
    ok = db.termin_serien.update(
        serie_id, data.typ, data.beginn_zeit, data.ende_zeit, data.ort,
        data.treffpunkt, data.treffpunkt_zeit, data.beschreibung, data.ende_datum,
        user.username, data.expected_version,
        spielstaette_id=data.spielstaette_id,
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
