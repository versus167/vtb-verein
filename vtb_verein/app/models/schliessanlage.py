"""
Datenmodelle für die Zutrittskontrolle / das Schließsystem (TT-Lock), Schema v57.

Die App ist Orchestrierungsschicht über der TTLock-Cloud (Quelle der Wahrheit):

- TTLockKonto:      Single-Row-Laufzeitstatus (Tokens/Sync) des einen Vereinskontos.
- TuerSchloss:      gespiegeltes Schloss-Inventar inkl. Status (Akku, letztes Event).
- SchluesselChip:   physischer Chip ↔ Mitglied (ausgegeben) ODER Standort (Pool-Chip).
- TuerBerechtigung: Chip an einem Schloss = eine TTLock-IC-Card (pro Schloss eigene cardId).
- TuerZutrittLog:   append-only Zutrittslog (dedupe über ttlock_record_id = recordId).

`record_type` ist der TTLock-Code der Öffnungs-/Verriegelungsmethode; `record_type_label`
mappt ihn auf einen lesbaren Text (vollständiger Schlüssel aus der TTLock-Doc, 2026-06).
"""
from dataclasses import dataclass
from typing import Optional


# recordType → lesbare Methode. Vollständig aus der TTLock-Doc
# (euopen.ttlock.com/doc/api/v3/lockRecord/list). Unbekannte Codes → '?<n>'.
RECORD_TYPES: dict[int, str] = {
    1: 'App',
    2: 'Parklücke berührt',
    3: 'Gateway (remote)',
    4: 'Passcode',
    5: 'Parksperre hoch',
    6: 'Parksperre runter',
    7: 'IC-Karte',
    8: 'Fingerprint',
    9: 'Armband',
    10: 'mech. Schlüssel',
    11: 'Bluetooth-Verriegeln',
    12: 'Gateway (remote)',
    29: 'Unerwartet entriegelt',
    30: 'Türmagnet zu',
    31: 'Türmagnet auf',
    32: 'Von innen geöffnet',
    33: 'Verriegelt (Fingerprint)',
    34: 'Verriegelt (Passcode)',
    35: 'Verriegelt (IC-Karte)',
    36: 'Verriegelt (mech. Schlüssel)',
    37: 'Fernbedienung',
    44: 'Sabotage-Alarm',
    45: 'Auto-Lock',
    46: 'Entriegeln (Unlock-Key)',
    47: 'Verriegeln (Lock-Key)',
    48: 'Mehrf. Falsch-Passcode',
}

# recordType-Codes, die ein Öffnen per IC-Karte sind (Kartennummer → Chip auflösbar).
IC_CARD_RECORD_TYPES = frozenset({7, 35})

# Sicherheitsrelevante recordType-Codes → Benachrichtigung an Admins (Phase 4).
# 44 = Sabotage-Alarm, 48 = mehrfach falscher Passcode.
ALARM_RECORD_TYPES = frozenset({44, 48})

# Credential-Typen am Schloss (read-only Inventar, 1:1 aus der Cloud gespiegelt).
CRED_FINGERPRINT = 'fingerprint'
CRED_PASSCODE = 'passcode'
CRED_EKEY = 'ekey'
CRED_IC = 'ic'
CREDENTIAL_TYPEN = (CRED_FINGERPRINT, CRED_PASSCODE, CRED_EKEY, CRED_IC)

CREDENTIAL_TYP_LABELS: dict[str, str] = {
    CRED_FINGERPRINT: 'Fingerprint',
    CRED_PASSCODE: 'Passcode',
    CRED_EKEY: 'App-/eKey',
    CRED_IC: 'IC-Karte',
}


def credential_typ_label(typ: Optional[str]) -> str:
    """Lesbarer Text zu einem Credential-Typ; Unbekanntes unverändert zurück."""
    return CREDENTIAL_TYP_LABELS.get(typ or '', typ or '-')

# Chip-Status
CHIP_AKTIV = 'aktiv'
CHIP_GESPERRT = 'gesperrt'
CHIP_VERLOREN = 'verloren'

# Berechtigungs-Sync-Status (Chip ↔ Schloss-Card in der Cloud)
SYNC_PENDING = 'pending'
SYNC_AKTIV = 'aktiv'
SYNC_FEHLER = 'fehler'
SYNC_GESPERRT = 'gesperrt'


def record_type_label(record_type: Optional[int]) -> str:
    """Lesbarer Text zu einem recordType; unbekannte Codes als '?<n>'."""
    if record_type is None:
        return '-'
    return RECORD_TYPES.get(record_type, f'?{record_type}')


@dataclass
class TTLockKonto:
    """Laufzeitstatus des einen Vereins-TTLock-Kontos (Secrets liegen NUR in der Env)."""
    id: Optional[int] = None
    endpoint: str = 'https://euapi.ttlock.com'
    ttlock_uid: Optional[int] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[str] = None
    letzter_sync_at: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class TuerSchloss:
    """Gespiegeltes Schloss/Tür-Inventar (aus v3/lock/list)."""
    id: Optional[int] = None
    ttlock_lock_id: int = 0
    name: str = ""
    standort: Optional[str] = None
    abteilung_id: Optional[int] = None            # NULL = vereinsweit (Scope)
    ttlock_gateway_id: Optional[int] = None
    gateway_online: Optional[bool] = None         # aus v3/gateway/list (isOnline)
    lock_mac: Optional[str] = None
    akku_prozent: Optional[int] = None
    akku_stand_at: Optional[str] = None
    aktiv: bool = True
    notiz: Optional[str] = None
    letzter_log_serverdate: Optional[int] = None  # Sync-Cursor (ms)
    letztes_event_at: Optional[str] = None        # Status-Snapshot (letzter Schließvorgang)
    letztes_event_type: Optional[int] = None
    # per JOIN befüllt (Anzeige)
    abteilung_name: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class SchluesselChip:
    """Physischer Chip ↔ Mitglied (ausgegeben) ODER Standort (Pool-Chip)."""
    id: Optional[int] = None
    kartennummer: str = ""
    bezeichnung: Optional[str] = None
    mitglied_id: Optional[int] = None             # Inhaber, falls personalisiert ausgegeben
    aufbewahrungsort: Optional[str] = None        # Standard-Standort, falls nicht personalisiert
    status: str = CHIP_AKTIV
    # per JOIN befüllt (Anzeige)
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    mitgliedsnummer: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class TuerBerechtigung:
    """Chip an einem Schloss = eine TTLock-IC-Card (pro Schloss eigene cardId)."""
    id: Optional[int] = None
    chip_id: int = 0
    schloss_id: int = 0
    ttlock_card_id: Optional[int] = None          # cardId (pro Schloss), NULL solange pending
    gueltig_von: Optional[str] = None             # NULL = unbefristet
    gueltig_bis: Optional[str] = None
    sync_status: str = SYNC_PENDING
    sync_fehler: Optional[str] = None
    erteilt_von: Optional[int] = None
    # per JOIN befüllt (Anzeige)
    schloss_name: Optional[str] = None
    chip_bezeichnung: Optional[str] = None
    kartennummer: Optional[str] = None
    mitglied_id: Optional[int] = None
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class TuerAppBerechtigung:
    """Kurzzeitige App-Betätigungs-Berechtigung: User darf Schloss befristet per App
    öffnen – ohne Chip (Self-Service-Sonderfall, getrennt von TuerBerechtigung)."""
    id: Optional[int] = None
    user_id: int = 0
    schloss_id: int = 0
    gueltig_von: Optional[str] = None             # NULL = ab sofort
    gueltig_bis: Optional[str] = None             # NULL = unbefristet
    grund: Optional[str] = None
    erteilt_von: Optional[int] = None
    # per JOIN befüllt (Anzeige)
    schloss_name: Optional[str] = None
    user_username: Optional[str] = None
    erteilt_von_username: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class TuerCredential:
    """Read-only gespiegeltes Credential am Schloss (Fingerprint/Passcode/eKey/IC-Karte).

    Reiner Cloud-Mirror (kein Anlernen/Löschen über die App): je Schloss + Typ wird die
    TTLock-Liste 1:1 gespiegelt, damit auch Credential-Typen sichtbar werden, die NICHT
    über unsere App liefen (Fingerprints/Funk-Keys = bisheriger blinder Fleck). Kein
    History/Soft-Delete – pro Schloss+Typ wird die Cloud-Liste autoritativ ersetzt."""
    id: Optional[int] = None
    schloss_id: int = 0
    typ: str = CRED_FINGERPRINT                    # fingerprint | passcode | ekey | ic
    ttlock_credential_id: Optional[int] = None     # fingerprintId/keyboardPwdId/keyId/cardId
    name: Optional[str] = None                     # *Name aus der Cloud
    detail: Optional[str] = None                   # eKey-User / Kartennummer (typabhängig)
    gueltig_von: Optional[str] = None              # aus startDate (ms) – NULL = unbefristet
    gueltig_bis: Optional[str] = None              # aus endDate (ms)
    gesehen_am: Optional[str] = None               # letzter Sync, der das Credential bestätigte
    raw: Optional[dict] = None
    created_at: Optional[str] = None
    # per JOIN befüllt (Anzeige)
    schloss_name: Optional[str] = None


@dataclass
class TuerZutrittLog:
    """Append-only Zutrittslog (aus v3/lockRecord/list, dedupe über ttlock_record_id)."""
    id: Optional[int] = None
    ttlock_record_id: int = 0
    schloss_id: int = 0
    record_type: Optional[int] = None
    record_type_from_lock: Optional[int] = None
    methode: Optional[str] = None                 # record_type_label(record_type)
    erfolg: Optional[bool] = None
    credential: Optional[str] = None              # keyboardPwd (Kartennummer/Passcode)
    key_name: Optional[str] = None
    ttlock_username: Optional[str] = None
    chip_id: Optional[int] = None                 # aufgelöst, falls Kartennummer matcht
    mitglied_id: Optional[int] = None             # aufgelöst über Chip
    lock_date: Optional[str] = None               # Ereigniszeit am Schloss
    server_date: Optional[int] = None             # serverDate (ms) – Cursor-Basis
    raw: Optional[dict] = None
    created_at: Optional[str] = None
    # per JOIN befüllt (Anzeige)
    schloss_name: Optional[str] = None
    chip_bezeichnung: Optional[str] = None
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
