"""
API-Endpunkte für die Zutrittskontrolle / Schließanlage (TT-Lock), Phase 1.

Master-Detail:
- Schlösser: Liste mit Status (Akku/Online/letzter Schließvorgang); Detail mit
  Zutrittslogs (hinter `schliessanlage.protokoll`) + zugeteilten Chips.
- Chips: Liste (Inhaber/Standort); Detail mit Berechtigungen + Nutzungs-Log
  (hinter `schliessanlage.protokoll`).
- Sync: Inventar + Logs aus der Cloud ziehen (on-demand-Button), `schliessanlage.verwalten`.

Bewegungsdaten (Logs) sind DSGVO-sensibel → eigenes Recht `schliessanlage.protokoll`.
Chip-/Schloss-Stammdatenpflege ist reine DB-Arbeit (kein Cloud-Write in Phase 1).
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.services.zutritt_service import ZutrittNichtKonfiguriertError, notify_alarme
from app.services.ttlock_client import TTLockError
from ..core.deps import CurrentUser, DB
from ..core.scope import visible_schloss_ids, darf_schloss
from .auth import _client_ip

router = APIRouter(prefix="/schliessanlage", tags=["schliessanlage"])


def _require(user, perm: str, was: str) -> None:
    if not user.has_permission(perm):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Keine Berechtigung: {was}")


def _darf_oeffnen(user, db, schloss) -> bool:
    """Öffnen darf, wer das Betätigungsrecht für genau dieses Schloss hat (global ODER
    abteilungsgebunden, Phase-3-Scope) ODER eine gültige Berechtigung dafür besitzt
    (Self-Service: Mitglied → Chip → Berechtigung bzw. befristete App-Berechtigung)."""
    return (darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_OEFFNEN)
            or db.tuer_berechtigungen.user_has_valid_for_schloss(user.id, schloss.id)
            or db.tuer_app_berechtigungen.user_has_valid_for_schloss(user.id, schloss.id))


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
    mitglied_id: Optional[int] = None
    aufbewahrungsort: Optional[str] = None
    status: str = "aktiv"


class ChipUpdateIn(BaseModel):
    bezeichnung: Optional[str] = None
    mitglied_id: Optional[int] = None
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
    }


@router.get("/users")
def user_lookup(user: CurrentUser, db: DB):
    """Schlanke User-Liste (id + username) für den Berechtigungs-Picker.
    Eigener Endpoint (statt /api/users, das personen.read verlangt) – hier reicht
    schliessanlage.verwalten."""
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.services.user_service import UserService
    return [
        {"id": u.id, "username": u.username, "active": u.active}
        for u in UserService(db).list_all()
        if u.active
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
    letzte eigene Zutritte des eingeloggten Users – über das verknüpfte Mitglied. Kein
    schliessanlage-Recht nötig (nur eigene Daten); Bewegungsdaten betreffen nur ihn selbst."""
    app_ber = db.tuer_app_berechtigungen.list_for_user(user.id)
    mitglied = db.get_mitglied_by_user_id(user.id)
    if not mitglied:
        return {"verknuepft": False, "chips": [], "berechtigungen": [],
                "app_berechtigungen": app_ber, "zutritte": []}
    chips = db.schluessel_chips.list_for_mitglied(mitglied.id)
    berechtigungen = []
    for c in chips:
        berechtigungen.extend(db.tuer_berechtigungen.list_for_chip(c.id))
    return {
        "verknuepft": True,
        "chips": chips,
        "berechtigungen": berechtigungen,
        "app_berechtigungen": app_ber,
        "zutritte": db.tuer_zutritt_logs.list_for_mitglied(mitglied.id, limit=50),
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
    try:
        db.access_log_repository.log(
            "schliessanlage_sync", category="schliessanlage",
            user_id=user.id, username=user.username, ip=_client_ip(request),
            detail=f"{ergebnis}",
        )
    except Exception:
        pass
    return ergebnis


# --- Schlösser ---------------------------------------------------------------
@router.get("/schloesser")
def schloesser_liste(user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_READ, "Schließanlage lesen")
    schloesser = db.tuer_schloesser.list_all()
    visible = visible_schloss_ids(user, db)          # Abteilungs-Scope (Phase 3)
    if visible is not None:
        schloesser = [s for s in schloesser if s.id in visible]
    return schloesser


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
        "logs": db.tuer_zutritt_logs.list_for_schloss(schloss_id) if darf_protokoll else [],
        "darf_protokoll": darf_protokoll,
        "darf_verwalten": darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_VERWALTEN),
        "darf_oeffnen": _darf_oeffnen(user, db, schloss),
        # Verriegeln ist reines Betätigungsrecht (kein Self-Service über Chip/App-Grant).
        "darf_verriegeln": darf_schloss(user, schloss, Permission.SCHLIESSANLAGE_OEFFNEN),
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
        "logs": logs,
        "darf_protokoll": darf_protokoll,
    }


@router.post("/chips", status_code=status.HTTP_201_CREATED)
def chip_anlegen(data: ChipIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    from app.models.schliessanlage import SchluesselChip
    chip = SchluesselChip(
        kartennummer=data.kartennummer, bezeichnung=data.bezeichnung,
        mitglied_id=data.mitglied_id, aufbewahrungsort=data.aufbewahrungsort,
        status=data.status,
    )
    return db.schluessel_chips.create(chip, user.username)


@router.put("/chips/{chip_id}")
def chip_update(chip_id: int, data: ChipUpdateIn, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    chip = db.schluessel_chips.get(chip_id)
    if not chip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
    chip.bezeichnung = data.bezeichnung
    chip.mitglied_id = data.mitglied_id
    chip.aufbewahrungsort = data.aufbewahrungsort
    chip.status = data.status
    chip.version = data.version
    updated = db.schluessel_chips.update(chip, user.username)
    if not updated:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Konflikt (zwischenzeitlich geändert) – bitte neu laden")
    return updated


@router.delete("/chips/{chip_id}", status_code=status.HTTP_204_NO_CONTENT)
def chip_loeschen(chip_id: int, user: CurrentUser, db: DB):
    _require(user, Permission.SCHLIESSANLAGE_VERWALTEN, "Schließanlage verwalten")
    if not db.schluessel_chips.soft_delete(chip_id, user.username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chip nicht gefunden")
