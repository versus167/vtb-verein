"""
API-Endpunkte für die Zutrittskontrolle / Schließanlage (TT-Lock), Phase 1.

Master-Detail:
- Schlösser: Liste mit Status (Akku/Online/letzter Schließvorgang); Detail mit
  Zutrittslogs (hinter `schliessanlage.protokoll`) + zugeteilten Chips.
- Chips: Liste (Inhaber/Standort); Detail mit Berechtigungen + Nutzungs-Log
  (hinter `schliessanlage.protokoll`).
- Sync: Inventar + Logs aus der Cloud ziehen (on-demand-Button), `schliessanlage.verwalten`.

- Import: Zutrittslog einer Fremdanlage (Schloss ohne TTLock-Anschluss) als CSV
  einlesen – `schliessanlage.verwalten` UND `schliessanlage.protokoll`, beides
  vereinsweit (der Import-Bericht ist selbst eine Nutzungsauswertung).
- Auswertung: aggregierte Nutzungsstatistik über die sichtbaren Schlösser, hinter
  `schliessanlage.protokoll` – dieselben Bewegungsdaten wie das Log, nur verdichtet.

Bewegungsdaten (Logs) sind DSGVO-sensibel → eigenes Recht `schliessanlage.protokoll`.
Chip-/Schloss-Stammdatenpflege ist reine DB-Arbeit (kein Cloud-Write in Phase 1).
"""
import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from app.services.anhang_service import DateiZuGrossError

from app.models.permission import Permission
from app.services.zutritt_service import ZutrittNichtKonfiguriertError, notify_alarme
from app.services.zutritt_import_service import ImportFehler, run_import
from app.services import zutritt_auswertung_service
from app.services import zutritt_abgleich_service
from app.services.ttlock_client import TTLockError
from ..core.config import settings
from ..core.deps import CurrentUser, DB
from ..core.scope import visible_schloss_ids, darf_schloss
from .auth import _client_ip
from .uploads import lese_upload

router = APIRouter(prefix="/schliessanlage", tags=["schliessanlage"])

logger = logging.getLogger(__name__)


async def _lese_import(file: UploadFile) -> bytes:
    """Import-Datei begrenzt einlesen (s. lese_upload) und die Grenze als 422 melden.

    Eigene, großzügigere Grenze als bei den Anhängen: Ein Jahresexport des
    Zutrittslogs oder eine Mitgliederliste ist größer als ein Belegfoto. Sie soll
    den Alltag nicht begrenzen, sondern verhindern, dass ein einzelner Upload den
    Prozess über sein Speicherlimit drückt.
    """
    try:
        return await lese_upload(file, settings.MAX_IMPORT_MB * 1024 * 1024)
    except DateiZuGrossError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _require(user, perm: str, was: str) -> None:
    if not user.has_permission(perm):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Keine Berechtigung: {was}")


def _darf_oeffnen(user, db, schloss) -> bool:
    """Öffnen darf, wer das Betätigungsrecht für genau dieses Schloss hat (global ODER
    abteilungsgebunden, Phase-3-Scope) ODER eine gültige Berechtigung dafür besitzt
    (Self-Service: Mitglied → Chip → Berechtigung bzw. befristete App-Berechtigung).
    Externe Schlösser lassen sich gar nicht fernsteuern – dort ist nichts zu erlauben."""
    if not schloss.ttlock_lock_id:
        return False
    return (darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_OEFFNEN)
            or db.tuer_berechtigungen.user_has_valid_for_schloss(user.id, schloss.id)
            or db.tuer_app_berechtigungen.user_has_valid_for_schloss(user.id, schloss.id))


def _konto_nachziehen(db, chip) -> int:
    """Bereits importierte Fremd-Log-Zeilen diesem Chip zuordnen.

    Die Zuordnung entsteht meist erst NACH dem ersten Import – der Bericht zeigt ja
    gerade die unbekannten Konten. Ohne diesen Schritt blieben die Zeilen für immer
    anonym, obwohl die Kennung inzwischen gepflegt ist.

    Geprüft wird über dieselbe Auflösung, die auch der Import nutzt: nur wenn ein
    Kandidatenname tatsächlich auf DIESEN Chip zeigt, werden Zeilen übernommen –
    sonst schnappte eine gleichlautende Bezeichnung Zeilen weg, die per gepflegter
    `externe_kennung` einem anderen Chip gehören.
    """
    gesamt = 0
    for kandidat in (chip.externe_kennung, chip.bezeichnung, chip.kartennummer):
        if not (kandidat or "").strip():
            continue
        treffer = db.schluessel_chips.find_active_by_externes_konto(kandidat)
        if treffer and treffer.id == chip.id:
            gesamt += db.tuer_zutritt_logs.resolve_extern_konto(
                kandidat, chip_id=chip.id, mitglied_id=chip.mitglied_id,
                user_id=chip.user_id)
    return gesamt


def _inhaber_pruefen(db, mitglied_id: Optional[int],
                     user_id: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    """Inhaber eines Chips normalisieren: (mitglied_id, user_id) – höchstens eines gesetzt.

    Ein Chip gehört einem Mitglied ODER einem Benutzer ohne Mitgliedsdatensatz
    (Platzwart, Hausmeister, Betreuer eines Gastvereins) – oder niemandem, dann ist er
    ein Pool-Chip mit Standort. Zwei Inhaber gleichzeitig gäbe es an der Tür nicht.

    Ist der gewählte Benutzer mit einem Mitglied verknüpft, wird auf dieses Mitglied
    umgeschrieben statt abzulehnen: dieselbe Person, aber am Mitglied hängen
    Log-Auflösung (`tuer_zutritt_log.mitglied_id`) und Mitglieder-Ansicht. Sonst
    entstünde je nach Auswahl eine andere Wahrheit über denselben Menschen.
    """
    if mitglied_id and user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Chip gehört entweder einem Mitglied oder einem "
                                   "Benutzer – nicht beiden.")
    if not user_id:
        return mitglied_id, None
    if not db.get_user_by_id(user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Benutzer nicht gefunden")
    mitglied = db.get_mitglied_by_user_id(user_id)
    return (mitglied.id, None) if mitglied else (None, user_id)


def _require_berechtigung_verwalten(user, db, berechtigung_id: int) -> None:
    """404, wenn die (Chip↔Schloss-)Berechtigung fehlt; 403, wenn der User das zugehörige
    Schloss nicht verwalten darf (Phase-3-Scope)."""
    ber = db.tuer_berechtigungen.get(berechtigung_id)
    if not ber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Berechtigung nicht gefunden")
    if not darf_schloss(user, db.tuer_schloesser.get(ber.schloss_id),
                        Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verwalten")


class SchlossUpdateIn(BaseModel):
    name: str
    standort: Optional[str] = None
    abteilung_id: Optional[int] = None
    notiz: Optional[str] = None
    aktiv: bool = True
    version: int


class ChipIn(BaseModel):
    kartennummer: str
    bezeichnung: Optional[str] = None
    externe_kennung: Optional[str] = None
    mitglied_id: Optional[int] = None
    user_id: Optional[int] = None
    aufbewahrungsort: Optional[str] = None
    status: str = "aktiv"


class ChipUpdateIn(BaseModel):
    bezeichnung: Optional[str] = None
    externe_kennung: Optional[str] = None
    mitglied_id: Optional[int] = None
    user_id: Optional[int] = None
    aufbewahrungsort: Optional[str] = None
    status: str = "aktiv"
    version: int


class AppBerechtigungIn(BaseModel):
    user_id: int
    gueltig_von: Optional[str] = None
    gueltig_bis: Optional[str] = None
    grund: Optional[str] = None


class BerechtigungIn(BaseModel):
    chip_id: int
    schloss_id: int
    gueltig_von: Optional[str] = None
    gueltig_bis: Optional[str] = None


class BerechtigungUpdateIn(BaseModel):
    gueltig_von: Optional[str] = None
    gueltig_bis: Optional[str] = None


class GruppeIn(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    schloss_ids: list[int] = []


class GruppeUpdateIn(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    expected_version: int


class GruppeSchloesserIn(BaseModel):
    schloss_ids: list[int]


class GruppeChipIn(BaseModel):
    chip_id: int


# --- Status / Sync ----------------------------------------------------------
@router.get("/status")
def status_info(user: CurrentUser, db: DB):
    """Konto-/Sync-Status für die Seite (konfiguriert? letzter Sync?)."""
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    konto = db.ttlock_konto.get()
    # Seiten-Chrome: 'darf_*' sind lenient (Recht irgendwo vorhanden) und steuern nur die
    # Sichtbarkeit von Buttons. Die echte Durchsetzung passiert je Schloss server-seitig
    # (Phase-3-Scope). Der account-weite Sync verlangt das **vereinsweite** Verwalten-Recht.
    return {
        "konfiguriert": db.zutritt.is_configured(),
        "letzter_sync_at": konto.letzter_sync_at if konto else None,
        "darf_verwalten": user.has_permission(Permission.SCHLIESSANLAGE_VERWALTEN),
        "darf_protokoll": user.has_permission(Permission.SCHLIESSANLAGE_PROTOKOLL),
        "darf_oeffnen": user.has_permission(Permission.SCHLIESSANLAGE_OEFFNEN),
        "darf_sync": user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN),
        # Eigenes Flag statt „darf_sync UND darf_protokoll" im Frontend: die Regel des
        # Imports (beides vereinsweit, s. log_import) gehört an eine Stelle – hierher.
        "darf_import": (user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN)
                        and user.has_permission_global(Permission.SCHLIESSANLAGE_PROTOKOLL)),
    }


@router.get("/users")
def user_lookup(user: CurrentUser, db: DB):
    """Schlanke User-Liste (id + username) für den Berechtigungs- und Chip-Picker.
    Eigener Endpoint (statt /api/users, das personen.read verlangt) – hier reicht
    schliessanlage.verwalten.

    `mitglied_id` sagt, ob hinter dem Konto ein Mitgliedsdatensatz steht: Solche
    Benutzer gehören in den Chip-Picker nicht noch einmal als „Benutzer" – sie stehen
    schon in der Mitgliederliste, und dort landet die Zuordnung ohnehin.

    Bewusst OHNE Aktiv-Filter: Ein Schlüsselträger ohne App-Konto (Platzwart,
    Hausmeister, Betreuer eines Gastvereins) ist genau ein inaktives Konto ohne
    E-Mail – wer einen Chip zuordnen will, braucht ihn hier. Wo ein Konto stattdessen
    jemanden bezeichnen muss, der sich anmeldet (befristete App-Öffnung), filtert
    der Aufrufer über `active`."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.services.user_service import UserService
    mitglied_je_user = {m.user_id: m.id for m in db.list_mitglieder() if m.user_id}
    return [
        {"id": u.id, "username": u.username, "active": u.active,
         "mitglied_id": mitglied_je_user.get(u.id)}
        for u in UserService(db).list_all()
    ]


@router.get("/mitglieder")
def mitglied_lookup(user: CurrentUser, db: DB):
    """Schlanke Mitglieder-Liste (id + Name + Nr) für den Chip-Zuordnungs-Picker.
    Eigener Endpoint (statt /api/mitglieder, das personen.read verlangt) – hier reicht
    schliessanlage.verwalten."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    return [
        {"id": m.id, "vorname": m.vorname, "nachname": m.nachname,
         "mitgliedsnummer": m.mitgliedsnummer}
        for m in sorted(
            db.list_mitglieder(),
            key=lambda m: ((m.nachname or "").lower(), (m.vorname or "").lower()),
        )
    ]


@router.get("/mein-zugang")
def mein_zugang(user: CurrentUser, db: DB):
    """Self-Service (Phase 4): eigene Chips, Türen, befristete App-Berechtigungen und
    letzte eigene Zutritte des eingeloggten Users. Kein schliessanlage-Recht nötig (nur
    eigene Daten); Bewegungsdaten betreffen nur ihn selbst.

    Chips erreichen einen über zwei Wege: das verknüpfte Mitglied oder – ohne
    Mitgliedsdatensatz – direkt das Benutzerkonto. `verknuepft` meint weiterhin die
    Mitgliedsverknüpfung, sagt aber nichts mehr darüber, ob es hier etwas zu sehen gibt.

    Die Zutritte kommen ausschließlich über die in der Log-Zeile festgehaltene Person
    (`mitglied_id`/`user_id`), nie über die heutigen Chips: ein weitergegebener Chip
    würde sonst die Bewegungsdaten seines Vorbesitzers an den neuen Inhaber ausliefern
    – und zwar an dieser Stelle ohne jedes Protokoll-Recht.
    """
    app_ber = db.tuer_app_berechtigungen.list_for_user(user.id)
    mitglied = db.get_mitglied_by_user_id(user.id)
    chips = db.schluessel_chips.list_for_user(user.id)
    if mitglied:
        chips = db.schluessel_chips.list_for_mitglied(mitglied.id) + chips
    berechtigungen = []
    for c in chips:
        berechtigungen.extend(db.tuer_berechtigungen.list_for_chip(c.id))
    return {
        "verknuepft": mitglied is not None,
        "chips": chips,
        "berechtigungen": berechtigungen,
        "app_berechtigungen": app_ber,
        "zutritte": db.tuer_zutritt_logs.list_selbstauskunft(
            mitglied_id=mitglied.id if mitglied else None,
            user_id=user.id, limit=50),
    }


@router.post("/sync")
def sync(request: Request, user: CurrentUser, db: DB,
         backfill_days: int = 30, logs_only: bool = False):
    """On-demand-Sync (Inventar + Logs) – derselbe Pfad wie der Cron-Command. Account-weit,
    daher vereinsweites Verwalten-Recht (nicht nur abteilungsgebunden)."""
    if not user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung: Schließanlage synchronisieren (vereinsweit)")
    try:
        ergebnis = {}
        if not logs_only:
            ergebnis.update(db.zutritt.inventar_sync())
            ergebnis.update(db.zutritt.ic_cards_sync())
            ergebnis.update(db.zutritt.credentials_sync())
        ergebnis.update(db.zutritt.logs_sync(backfill_days=backfill_days))
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    # Sicherheitsrelevante Ereignisse → Admins benachrichtigen (Fehler nicht propagieren).
    try:
        benachrichtigt = notify_alarme(db, ergebnis.get("alarme", []))
        if benachrichtigt:
            ergebnis["alarme_benachrichtigt"] = benachrichtigt
    except Exception:
        pass
    # Jetzt ist das Ist frisch – der Soll-Ist-Abgleich ist genau hier aussagekräftig.
    # Ein gesperrter Chip, der weiter öffnet, geht als Meldung raus (nur wenn neu).
    if not logs_only:
        try:
            gemeldet = zutritt_abgleich_service.melde_sperrluecken(db)
            if gemeldet:
                ergebnis["sperrluecken_gemeldet"] = gemeldet
        except Exception:
            logger.exception("Sperr-Lücken-Abgleich nach dem Sync fehlgeschlagen.")
    try:
        db.access_log_repository.log(
            "schliessanlage_sync", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{ergebnis}",
        )
    except Exception:
        pass
    return ergebnis


@router.get("/abgleich")
def abgleich(user: CurrentUser, db: DB):
    """Soll-Ist-Abgleich der IC-Karten: Was steht bei uns, was liegt am Schloss?

    Reine DB-Arbeit auf dem Stand des letzten Syncs (`stand`) – kein Cloud-Aufruf,
    deshalb beliebig oft abrufbar. Verwalten-Recht, weil die Befunde beschreiben, wer
    wo (nicht) hereinkommt; der Abteilungs-Scope schneidet fremde Schlösser weg.
    """
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    return zutritt_abgleich_service.abgleich(
        db, schloss_ids=visible_schloss_ids(user, db, Permission.SCHLIESSANLAGE_VERWALTEN))


@router.post("/import")
async def log_import(request: Request, user: CurrentUser, db: DB,
                     file: UploadFile = File(...), commit: bool = Form(False)):
    """Zutrittslog einer Fremdanlage (Schloss ohne TTLock-Anschluss) als CSV einlesen.

    Ohne `commit` reine Vorschau – sie zeigt exakt das, was der Lauf tun würde,
    inklusive der Konten, die (noch) auf keinen Chip zeigen. Der Lauf legt ein
    unbekanntes Schloss automatisch als externes Schloss an und ist idempotent
    (Dedupe über Schloss + Zeitpunkt + Konto), derselbe Export darf also erneut rein.

    Verlangt BEIDE Rechte, jedes aus eigenem Grund:
    - `schliessanlage.verwalten` **vereinsweit**, weil der Import ein Schloss anlegen
      kann und Bewegungsdaten schreibt – keine abteilungsgebundene Entscheidung.
    - `schliessanlage.protokoll`, ebenfalls vereinsweit, weil der Bericht selbst
      Bewegungsdaten IST: er nennt je Konto Person und Anzahl und je Schloss den
      Zeitraum – über alle Schlösser der Datei, nicht nur über die eigene Abteilung.
      Anders als bei `/sync` (nur Zählwerte und Alarme) käme man hier sonst am
      Protokollrecht vorbei an genau die Auswertung, die es schützt. Wer die Nutzung
      nicht sehen darf, importiert sie auch nicht – ein entpersonalisierter Bericht
      wäre wertlos, denn sein Kern ist gerade die Liste der Konten ohne Chip.
    """
    if not user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung: Zutrittslog importieren (vereinsweit)")
    if not user.has_permission_global(Permission.SCHLIESSANLAGE_PROTOKOLL):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung: Der Import-Bericht zeigt die Nutzung – dafür ist "
                   "das Zutrittsprotokoll-Recht (vereinsweit) nötig")
    daten = await _lese_import(file)
    if not daten:
        raise HTTPException(status_code=422, detail="Leere Datei")
    try:
        bericht = run_import(db, daten, commit=commit, actor=user.username)
    except ImportFehler as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Import fehlgeschlagen: {e}")
    if commit:
        try:
            db.access_log_repository.log(
                "schliessanlage_log_import", category="schliessanlage",
                user_id=user.id, username=user.username, ip=_client_ip(request),
                detail=f"Fremd-Log importiert ({file.filename}): {bericht.zusammenfassung}",
            )
        except Exception:
            pass
    return {**asdict(bericht), "zusammenfassung": bericht.zusammenfassung}


# --- Schlösser ---------------------------------------------------------------
@router.get("/schloesser")
def schloesser_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    schloesser = db.tuer_schloesser.list_all()
    visible = visible_schloss_ids(user, db)          # Abteilungs-Scope (Phase 3)
    if visible is not None:
        schloesser = [s for s in schloesser if s.id in visible]
    return schloesser


@router.get("/logs")
def gesamt_log(user: CurrentUser, db: DB, limit: int = 100):
    """Gesamt-Zutrittslog über alle (sichtbaren) Schlösser, neueste zuerst.
    Bewegungsdaten sind DSGVO-sensibel → eigenes Recht `schliessanlage.protokoll`;
    der Abteilungs-Scope greift wie bei den Einzel-Logs."""
    _require(user, Permission.SCHLIESSANLAGE_PROTOKOLL, "Zutrittsprotokoll einsehen")
    limit = max(1, min(limit, 500))
    visible = visible_schloss_ids(user, db, Permission.SCHLIESSANLAGE_PROTOKOLL)
    return db.tuer_zutritt_logs.list_neueste(
        limit=limit, schloss_ids=None if visible is None else list(visible))


@router.get("/auswertung")
def auswertung(user: CurrentUser, db: DB, tage: int = 90):
    """Nutzungsstatistik über die sichtbaren Schlösser (#161).

    Verdichtete Bewegungsdaten – also dieselbe DSGVO-Klasse wie das Log und hinter
    demselben Recht; der Abteilungs-Scope greift identisch. `tage` = Länge des
    Zeitraums, 0 bedeutet „seit jeher"; andere Werte werden auf die Auswahl der
    Oberfläche gerundet, damit die Aggregation kalkulierbar bleibt.
    """
    _require(user, Permission.SCHLIESSANLAGE_PROTOKOLL, "Zutrittsprotokoll einsehen")
    if tage not in zutritt_auswertung_service.ZEITRAEUME:
        tage = 90
    visible = visible_schloss_ids(user, db, Permission.SCHLIESSANLAGE_PROTOKOLL)
    return zutritt_auswertung_service.bericht(db, tage=tage, schloss_ids=visible)


@router.get("/schloesser/{schloss_id}")
def schloss_detail(schloss_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung für dieses Schloss")
    # Aktions-/Protokollrechte gelten je Schloss (Scope), nicht pauschal für die Seite.
    darf_protokoll = darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_PROTOKOLL)
    return {
        "schloss": schloss,
        "berechtigungen": db.tuer_berechtigungen.list_for_schloss(schloss_id),
        "app_berechtigungen": db.tuer_app_berechtigungen.list_for_schloss(schloss_id),
        # Read-only Credential-Inventar (Fingerprints/Passcodes/eKeys/IC) – auf Read-Ebene,
        # analog zur Chip-/Berechtigungsliste (kein personenbezogenes Bewegungsdatum).
        "credentials": db.tuer_credentials.list_for_schloss(schloss_id),
        # Der Zutrittslog (Bewegungsdaten) wird NICHT mehr hier mitgeladen, sondern separat
        # über GET …/{id}/logs (Lazy-Dialog auf der Schloss-Kachel) – hält das Detail schlank.
        "darf_protokoll": darf_protokoll,
        "darf_verwalten": darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN),
        "darf_oeffnen": _darf_oeffnen(user, db, schloss),
        # Verriegeln ist reines Betätigungsrecht (kein Self-Service über Chip/App-Grant);
        # an einem externen Schloss gibt es beides nicht.
        "darf_verriegeln": bool(schloss.ttlock_lock_id)
        and darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_OEFFNEN),
    }


@router.get("/schloesser/{schloss_id}/logs")
def schloss_logs(schloss_id: int, user: CurrentUser, db: DB):
    """Zutrittslog eines Schlosses – separater Lazy-Abruf für den Log-Dialog auf der Kachel
    (statt im Detail mitzuladen). Bewegungsdaten hinter dem eigenen Protokoll-Recht je
    Schloss (Scope), exakt wie in schloss_detail."""
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_READ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung für dieses Schloss")
    darf_protokoll = darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_PROTOKOLL)
    return {
        "darf_protokoll": darf_protokoll,
        "logs": db.tuer_zutritt_logs.list_for_schloss(schloss_id) if darf_protokoll else [],
        # Konnektivitäts-Events (online↔offline, #82) sind keine Bewegungs-/Personendaten →
        # bereits mit READ sichtbar, verschränkt mit den Öffnungen im selben Log-Dialog.
        "status_events": db.tuer_schloss_status_logs.list_for_schloss(schloss_id),
    }


@router.put("/schloesser/{schloss_id}")
def schloss_update(schloss_id: int, data: SchlossUpdateIn, user: CurrentUser, db: DB):
    """Stammdaten (Name/Standort/Abteilung/Notiz/aktiv) – reine DB-Pflege."""
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verwalten")
    # Das Umhängen der Abteilung (= des Scopes selbst) ist eine vereinsweite Governance-
    # Aktion: nur mit globalem Verwalten-Recht, sonst könnte ein abteilungsgebundener
    # Verwalter ein Schloss aus seinem Scope heraus- oder vereinsweit schieben.
    if data.abteilung_id != schloss.abteilung_id \
            and not user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Abteilungs-Zuordnung darf nur vereinsweit verwaltet werden")
    schloss.name = data.name
    schloss.standort = data.standort
    schloss.abteilung_id = data.abteilung_id
    schloss.notiz = data.notiz
    schloss.aktiv = data.aktiv
    schloss.version = data.version
    updated = db.tuer_schloesser.update_stammdaten(schloss, user.username)
    if not updated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Konflikt (zwischenzeitlich geändert) – bitte neu laden")
    return updated


@router.post("/schloesser/{schloss_id}/oeffnen")
def schloss_oeffnen(schloss_id: int, request: Request, user: CurrentUser, db: DB):
    """Schloss per Gateway fernöffnen. Recht: schliessanlage.oeffnen ODER gültige
    Berechtigung für genau dieses Schloss (Self-Service)."""
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not _darf_oeffnen(user, db, schloss):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu öffnen")
    try:
        ergebnis = db.zutritt.oeffnen(schloss_id)
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    try:
        db.access_log_repository.log(
            "schliessanlage_unlock", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            # Format-Kopplung: die Zutrittslog-Auflösung (#66) korreliert TTLock-Records
            # per LIKE 'Schloss {id} (%' mit diesem detail – Präfix nicht ändern.
            detail=f"Schloss {schloss_id} ({ergebnis.get('schloss')}) ferngeöffnet",
        )
    except Exception:
        pass
    return ergebnis


@router.post("/schloesser/{schloss_id}/verriegeln")
def schloss_verriegeln(schloss_id: int, request: Request, user: CurrentUser, db: DB):
    """Schloss per Gateway fernverriegeln (modellabhängig). Betätigungsrecht je Schloss
    (Scope) – kein Self-Service-Verriegeln."""
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_OEFFNEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verriegeln")
    try:
        ergebnis = db.zutritt.verriegeln(schloss_id)
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    try:
        db.access_log_repository.log(
            "schliessanlage_lock", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"Schloss {schloss_id} ({ergebnis.get('schloss')}) fernverriegelt",
        )
    except Exception:
        pass
    return ergebnis


# --- Kurzzeitige App-Betätigungs-Berechtigung -------------------------------
@router.post("/schloesser/{schloss_id}/app-berechtigungen", status_code=status.HTTP_201_CREATED)
def app_berechtigung_vergeben(schloss_id: int, data: AppBerechtigungIn, request: Request,
                              user: CurrentUser, db: DB):
    """Einem User befristet das App-Öffnen dieses Schlosses erlauben (ohne Chip)."""
    schloss = db.tuer_schloesser.get(schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verwalten")
    # App-Öffnen setzt ein Konto voraus, mit dem sich jemand anmelden kann. Seit die
    # User-Liste auch Konten ohne Zugang enthält (Schlüsselträger), ist ein Griff
    # daneben möglich – die Berechtigung wäre stillschweigend wirkungslos.
    ziel = db.get_user_by_id(data.user_id)
    if ziel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if not ziel.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Dieses Konto hat keinen App-Zugang – App-Öffnen "
                                   "wäre wirkungslos.")
    from app.models.schliessanlage import TuerAppBerechtigung
    erteilt = db.tuer_app_berechtigungen.create(
        TuerAppBerechtigung(
            user_id=data.user_id, schloss_id=schloss_id,
            gueltig_von=data.gueltig_von or None, gueltig_bis=data.gueltig_bis or None,
            grund=data.grund or None, erteilt_von=user.id,
        ),
        created_by=user.username,
    )
    try:
        db.access_log_repository.log(
            "schliessanlage_app_grant", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"App-Öffnen für User {data.user_id} an Schloss {schloss_id} "
                   f"({data.gueltig_von or 'sofort'}–{data.gueltig_bis or 'unbefristet'})",
        )
    except Exception:
        pass
    return erteilt


@router.delete("/app-berechtigungen/{berechtigung_id}", status_code=status.HTTP_204_NO_CONTENT)
def app_berechtigung_entziehen(berechtigung_id: int, request: Request,
                               user: CurrentUser, db: DB):
    """App-Betätigungs-Berechtigung vorzeitig entziehen (Soft-Delete)."""
    ber = db.tuer_app_berechtigungen.get(berechtigung_id)
    if not ber:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nicht gefunden")
    if not darf_schloss(user, db.tuer_schloesser.get(ber.schloss_id),
                        Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verwalten")
    db.tuer_app_berechtigungen.soft_delete(berechtigung_id, user.username)
    try:
        db.access_log_repository.log(
            "schliessanlage_app_revoke", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"App-Berechtigung {berechtigung_id} entzogen",
        )
    except Exception:
        pass


# --- Berechtigungen (Chip ↔ Schloss = IC-Card, Phase 2) ---------------------
@router.post("/berechtigungen", status_code=status.HTTP_201_CREATED)
def berechtigung_anlernen(data: BerechtigungIn, request: Request, user: CurrentUser, db: DB):
    """Chip an einem Schloss anlernen (IC-Karte per Gateway aufspielen)."""
    schloss = db.tuer_schloesser.get(data.schloss_id)
    if not schloss:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schloss nicht gefunden")
    if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, dieses Schloss zu verwalten")
    try:
        ber = db.zutritt.chip_anlernen(
            chip_id=data.chip_id, schloss_id=data.schloss_id,
            gueltig_von=data.gueltig_von or None, gueltig_bis=data.gueltig_bis or None,
            erteilt_von=user.id, actor=user.username,
        )
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TTLockError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"TTLock-Cloud: {e}")
    try:
        db.access_log_repository.log(
            "schliessanlage_chip_anlernen", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"Chip {data.chip_id} an Schloss {data.schloss_id} angelernt",
        )
    except Exception:
        pass
    return ber


@router.put("/berechtigungen/{berechtigung_id}")
def berechtigung_aendern(berechtigung_id: int, data: BerechtigungUpdateIn,
                         request: Request, user: CurrentUser, db: DB):
    """Gültigkeitszeitraum einer angelernten Berechtigung ändern (per Gateway)."""
    _require_berechtigung_verwalten(user, db, berechtigung_id)
    try:
        ber = db.zutritt.berechtigung_aendern(
            berechtigung_id=berechtigung_id,
            gueltig_von=data.gueltig_von or None, gueltig_bis=data.gueltig_bis or None,
            actor=user.username,
        )
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TTLockError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"TTLock-Cloud: {e}")
    try:
        db.access_log_repository.log(
            "schliessanlage_berechtigung_aendern", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"Berechtigung {berechtigung_id} Gültigkeit geändert",
        )
    except Exception:
        pass
    return ber


@router.delete("/berechtigungen/{berechtigung_id}", status_code=status.HTTP_204_NO_CONTENT)
def berechtigung_entziehen(berechtigung_id: int, request: Request, user: CurrentUser, db: DB):
    """Berechtigung entziehen (IC-Karte per Gateway vom Schloss entfernen + Soft-Delete)."""
    _require_berechtigung_verwalten(user, db, berechtigung_id)
    try:
        db.zutritt.berechtigung_entziehen(berechtigung_id=berechtigung_id, actor=user.username)
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TTLockError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"TTLock-Cloud: {e}")
    try:
        db.access_log_repository.log(
            "schliessanlage_berechtigung_entziehen", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"Berechtigung {berechtigung_id} entzogen",
        )
    except Exception:
        pass


# --- Rechtegruppen (#169) ----------------------------------------------------
def _gruppe_oder_404(db, gruppe_id: int):
    gruppe = db.chip_gruppen.get(gruppe_id)
    if not gruppe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Rechtegruppe nicht gefunden")
    return gruppe


def _schloesser_pruefen(user, db, schloss_ids) -> None:
    """Jede betroffene Tür einzeln gegen den Abteilungs-Scope prüfen.

    Eine Gruppe darf Türen mehrerer Abteilungen bündeln; wer sie pflegt, muss sie
    aber alle verwalten dürfen – sonst öffnete eine Gruppe den Weg, sich über die
    eigene Abteilung hinaus Rechte zu erteilen. Externe Schlösser hängen nicht an
    der Cloud und lassen sich gar nicht anlernen (siehe `chip_anlernen`); sie
    gehören deshalb nicht in eine Gruppe."""
    for schloss_id in schloss_ids:
        schloss = db.tuer_schloesser.get(schloss_id)
        if not schloss:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Schloss {schloss_id} nicht gefunden")
        if not darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Keine Berechtigung, „{schloss.name}“ zu verwalten")
        if not schloss.ttlock_lock_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"„{schloss.name}“ ist eine Fremdanlage – dort lassen sich "
                       f"Chips nicht per Gruppe anlernen")


def _gruppe_antwort(db, gruppe, ergebnis: Optional[dict] = None) -> dict:
    """Gruppe + (bei Änderungen) was der Abgleich an den Türen bewirkt hat."""
    antwort = {"gruppe": db.chip_gruppen.get(gruppe.id) if gruppe else None,
               "chip_ids": db.chip_gruppen.chip_ids(gruppe.id) if gruppe else []}
    if ergebnis is not None:
        antwort["abgleich"] = ergebnis
    return antwort


def _abgleich_ausfuehren(fn, **kw) -> dict:
    """Ruft eine Abgleich-Operation und bildet ihre Fehler auf HTTP ab."""
    try:
        return fn(**kw)
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TTLockError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"TTLock-Cloud: {e}")


@router.get("/gruppen")
def gruppen_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    return db.chip_gruppen.list_all()


@router.get("/gruppen/{gruppe_id}")
def gruppe_detail(gruppe_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    return _gruppe_antwort(db, _gruppe_oder_404(db, gruppe_id))


@router.post("/gruppen", status_code=status.HTTP_201_CREATED)
def gruppe_anlegen(data: GruppeIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.models.schliessanlage import ChipGruppe
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Die Gruppe braucht einen Namen")
    if db.chip_gruppen.find_by_name(name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Es gibt bereits eine Gruppe „{name}“")
    gruppe = db.chip_gruppen.create(
        ChipGruppe(name=name, beschreibung=(data.beschreibung or None)), user.username)
    if data.schloss_ids:
        _schloesser_pruefen(user, db, data.schloss_ids)
        db.chip_gruppen.set_schloesser(gruppe.id, data.schloss_ids, user.username)
    return _gruppe_antwort(db, gruppe)


@router.put("/gruppen/{gruppe_id}")
def gruppe_aendern(gruppe_id: int, data: GruppeUpdateIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Die Gruppe braucht einen Namen")
    doppelt = db.chip_gruppen.find_by_name(name)
    if doppelt and doppelt.id != gruppe_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Es gibt bereits eine Gruppe „{name}“")
    gruppe.name = name
    gruppe.beschreibung = (data.beschreibung or None)
    gruppe.version = data.expected_version
    if not db.chip_gruppen.update(gruppe, user.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Versionskonflikt – bitte neu laden")
    return _gruppe_antwort(db, gruppe)


@router.put("/gruppen/{gruppe_id}/schloesser")
def gruppe_schloesser_setzen(gruppe_id: int, data: GruppeSchloesserIn,
                             request: Request, user: CurrentUser, db: DB):
    """Türliste der Gruppe setzen – wirkt sofort auf alle Chips der Gruppe."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    # Auch die WEGGENOMMENEN Türen prüfen: Sie zu entziehen ist derselbe Eingriff.
    _schloesser_pruefen(user, db, set(data.schloss_ids) | set(gruppe.schloss_ids or []))
    ergebnis = _abgleich_ausfuehren(
        db.zutritt.gruppe_schloesser_setzen, gruppe_id=gruppe_id,
        schloss_ids=data.schloss_ids, erteilt_von=user.id, actor=user.username)
    _log_gruppe(db, request, user, gruppe_id,
                f"Türen der Gruppe {gruppe_id} gesetzt ({len(data.schloss_ids)} Schlösser)")
    return _gruppe_antwort(db, gruppe, ergebnis)


@router.delete("/gruppen/{gruppe_id}")
def gruppe_loeschen(gruppe_id: int, request: Request, user: CurrentUser, db: DB):
    """Gruppe auflösen: alle Chips heraus (Türen werden entzogen), dann die Gruppe."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    _schloesser_pruefen(user, db, gruppe.schloss_ids or [])
    ergebnis = _abgleich_ausfuehren(db.zutritt.gruppe_loeschen, gruppe_id=gruppe_id,
                                    actor=user.username)
    _log_gruppe(db, request, user, gruppe_id, f"Rechtegruppe {gruppe_id} aufgelöst")
    return ergebnis


@router.post("/gruppen/{gruppe_id}/abgleich")
def gruppe_abgleich(gruppe_id: int, request: Request, user: CurrentUser, db: DB):
    """Nachfassen für alle Chips der Gruppe – für Türen, die beim ersten Versuch
    nicht erreichbar waren."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    _schloesser_pruefen(user, db, gruppe.schloss_ids or [])
    ergebnis = _abgleich_ausfuehren(db.zutritt.gruppe_abgleichen, gruppe_id=gruppe_id,
                                    erteilt_von=user.id, actor=user.username)
    _log_gruppe(db, request, user, gruppe_id, f"Gruppe {gruppe_id} abgeglichen")
    return ergebnis


@router.post("/gruppen/{gruppe_id}/chips", status_code=status.HTTP_201_CREATED)
def gruppe_chip_zuordnen(gruppe_id: int, data: GruppeChipIn, request: Request,
                         user: CurrentUser, db: DB):
    """Chip in die Gruppe aufnehmen; ihre Türen werden ihm sofort erteilt."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    _schloesser_pruefen(user, db, gruppe.schloss_ids or [])
    ergebnis = _abgleich_ausfuehren(
        db.zutritt.gruppe_chip_zuordnen, gruppe_id=gruppe_id, chip_id=data.chip_id,
        erteilt_von=user.id, actor=user.username)
    _log_gruppe(db, request, user, gruppe_id,
                f"Chip {data.chip_id} zu Gruppe {gruppe_id} hinzugefügt")
    return _gruppe_antwort(db, gruppe, ergebnis)


@router.delete("/gruppen/{gruppe_id}/chips/{chip_id}")
def gruppe_chip_entfernen(gruppe_id: int, chip_id: int, request: Request,
                          user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    gruppe = _gruppe_oder_404(db, gruppe_id)
    _schloesser_pruefen(user, db, gruppe.schloss_ids or [])
    ergebnis = _abgleich_ausfuehren(
        db.zutritt.gruppe_chip_entfernen, gruppe_id=gruppe_id, chip_id=chip_id,
        actor=user.username)
    _log_gruppe(db, request, user, gruppe_id,
                f"Chip {chip_id} aus Gruppe {gruppe_id} entfernt")
    return _gruppe_antwort(db, gruppe, ergebnis)


@router.post("/chips/{chip_id}/gruppen-abgleich")
def chip_gruppen_abgleich(chip_id: int, request: Request, user: CurrentUser, db: DB):
    """Nachfassen: die Gruppen-Türen eines Chips erneut abgleichen.

    Für den Fall, dass beim ersten Versuch ein Schloss offline war – der Abgleich
    ist zustandsbasiert, ein zweiter Lauf holt genau das Fehlende nach."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    ergebnis = _abgleich_ausfuehren(db.zutritt.chip_gruppen_abgleichen, chip_id=chip_id,
                                    erteilt_von=user.id, actor=user.username)
    _log_gruppe(db, request, user, None, f"Chip {chip_id}: Gruppen abgeglichen")
    return ergebnis


def _log_gruppe(db, request, user, gruppe_id: Optional[int], detail: str) -> None:
    try:
        db.access_log_repository.log(
            "schliessanlage_gruppe", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=detail,
        )
    except Exception:
        pass


# --- Chips -------------------------------------------------------------------
@router.get("/chips")
def chips_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    return db.schluessel_chips.list_all()


@router.get("/chips/{chip_id}")
def chip_detail(chip_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    chip = db.schluessel_chips.get(chip_id)
    if not chip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
    darf_protokoll = user.has_permission(Permission.SCHLIESSANLAGE_PROTOKOLL)
    berechtigungen = db.tuer_berechtigungen.list_for_chip(chip_id)
    logs = db.tuer_zutritt_logs.list_for_chip(chip_id) if darf_protokoll else []
    # Abteilungs-Scope: ein abteilungsgebundener User darf über einen (club-weiten) Chip
    # keine Schlösser/Bewegungsdaten außerhalb seines Scopes sehen.
    visible = visible_schloss_ids(user, db, Permission.SCHLIESSANLAGE_READ)
    if visible is not None:
        berechtigungen = [b for b in berechtigungen if b.schloss_id in visible]
    visible_prot = visible_schloss_ids(user, db, Permission.SCHLIESSANLAGE_PROTOKOLL)
    if visible_prot is not None:
        logs = [l for l in logs if l.schloss_id in visible_prot]
    return {
        "chip": chip,
        "berechtigungen": berechtigungen,
        "gruppen": db.chip_gruppen.gruppen_fuer_chip(chip_id),
        "logs": logs,
        "darf_protokoll": darf_protokoll,
    }


@router.post("/chips", status_code=status.HTTP_201_CREATED)
def chip_anlegen(data: ChipIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.models.schliessanlage import SchluesselChip
    mitglied_id, user_id = _inhaber_pruefen(db, data.mitglied_id, data.user_id)
    chip = SchluesselChip(
        kartennummer=data.kartennummer, bezeichnung=data.bezeichnung,
        externe_kennung=(data.externe_kennung or None),
        mitglied_id=mitglied_id, user_id=user_id,
        aufbewahrungsort=data.aufbewahrungsort,
        status=data.status,
    )
    angelegt = db.schluessel_chips.create(chip, user.username)
    _konto_nachziehen(db, angelegt)
    return angelegt


@router.put("/chips/{chip_id}")
def chip_update(chip_id: int, data: ChipUpdateIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    chip = db.schluessel_chips.get(chip_id)
    if not chip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
    mitglied_id, inhaber_user_id = _inhaber_pruefen(db, data.mitglied_id, data.user_id)
    # Der Status wirkt an den Schlössern: alles außer 'aktiv' setzt die IC-Karten des
    # Chips auf ein abgelaufenes Gültigkeitsfenster, 'aktiv' stellt sie wieder her.
    # Deshalb zuerst die Cloud — schlägt sie fehl, bleibt der alte Status stehen,
    # statt in der Liste eine Sperre zu behaupten, die es an der Tür nicht gibt.
    if data.status != chip.status:
        try:
            db.zutritt.chip_status_setzen(chip_id=chip_id, status=data.status,
                                          actor=user.username)
        except ZutrittNichtKonfiguriertError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except TTLockError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail=f"TTLock-Cloud: {e}")
        chip = db.schluessel_chips.get(chip_id)      # Version durch den Status-Schreib
        data.version = chip.version
    chip.bezeichnung = data.bezeichnung
    chip.externe_kennung = data.externe_kennung or None
    chip.mitglied_id = mitglied_id
    chip.user_id = inhaber_user_id
    chip.aufbewahrungsort = data.aufbewahrungsort
    chip.status = data.status
    chip.version = data.version
    updated = db.schluessel_chips.update(chip, user.username)
    if not updated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Konflikt (zwischenzeitlich geändert) – bitte neu laden")
    _konto_nachziehen(db, updated)
    return updated


@router.delete("/chips/{chip_id}", status_code=status.HTTP_204_NO_CONTENT)
def chip_loeschen(chip_id: int, user: CurrentUser, db: DB):
    """Chip entfernen — inklusive der IC-Karten an allen Schlössern.

    Ohne diesen Schritt öffnete der Chip weiter jede Tür, an der er angelernt ist,
    nur eben unsichtbar. Ist ein Schloss nicht erreichbar, bricht der Vorgang ab.
    """
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    try:
        db.zutritt.chip_loeschen(chip_id=chip_id, actor=user.username)
    except ZutrittNichtKonfiguriertError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TTLockError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Karte konnte nicht von allen Schlössern entfernt "
                                   f"werden ({e}) – Chip bleibt bestehen")
