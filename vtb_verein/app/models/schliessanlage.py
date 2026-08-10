"""
Datenmodelle für die Zutrittskontrolle / das Schließsystem (TT-Lock), Schema v57.

Die App ist Orchestrierungsschicht über der TTLock-Cloud (Quelle der Wahrheit):

- TTLockKonto:      Single-Row-Laufzeitstatus (Tokens/Sync) des einen Vereinskontos.
- TuerSchloss:      gespiegeltes Schloss-Inventar inkl. Status (Akku, letztes Event).
- SchluesselChip:   physischer Chip ↔ Mitglied (ausgegeben) ODER Standort (Pool-Chip).
- TuerBerechtigung: Chip an einem Schloss = eine TTLock-IC-Card (pro Schloss eigene cardId).
- TuerZutrittLog:   append-only Zutrittslog (dedupe über ttlock_record_id = recordId).

Ausnahme: ein Schloss mit `quelle='extern'` hängt NICHT an der Cloud (eigene Anlage,
gleiche Chips). Dort gibt es keine lockId, keine recordId und kein Fernöffnen – sein
Log kommt per CSV-Import und wird über `SchluesselChip.externe_kennung` auf Chip →
Mitglied aufgelöst (s. `services/zutritt_import_service.py`).

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

# recordType-Codes, die ein ÖFFNEN sind – die Grundgesamtheit der Auswertung (#161).
# Bewusst eine Positivliste: Verriegeln (11, 33–36, 47), Türmagnet (30/31), Parksperre
# (2, 5, 6), Auto-Lock (45) und Alarme (44/48) sind keine Öffnungen und würden die
# Rangliste sonst verfälschen. Unbekannte Codes zählen nicht mit; Zeilen aus einer
# Fremdanlage ohne erkannten Typ (record_type IS NULL, quelle='extern') schon – dort
# protokolliert die Anlage ausschließlich Öffnungen.
OEFFNUNG_RECORD_TYPES = frozenset({1, 3, 4, 7, 8, 9, 10, 12, 29, 32, 37, 46})

# recordType-Codes einer Gateway-Fernöffnung (v3/lock/unlock). Öffnungen über UNSERE App
# laufen so und erscheinen in der Cloud nur unter dem TTLock-Sammelkonto – der auslösende
# VTB-User lässt sich per Korrelation mit dem access_log ('schliessanlage_unlock')
# auflösen (Phase-5-Teil B). 3/12 = „Gateway (remote)".
GATEWAY_REMOTE_RECORD_TYPES = frozenset({3, 12})

# Herkunft eines Schlosses bzw. einer Log-Zeile. 'ttlock' = an der Cloud (Inventar/Logs
# kommen aus dem Sync); 'extern' = eigenständige Fremdanlage, die nur dieselben Chips
# akzeptiert (Tor-Einfahrt) – ihr Log kommt per CSV-Import, Fernöffnen gibt es dort nicht.
QUELLE_TTLOCK = 'ttlock'
QUELLE_EXTERN = 'extern'

# 'Unlock Type' der Fremdanlage → TTLock-recordType. Der Import führt die fremden
# Bezeichnungen auf dieselben Codes zurück, damit Auswertung und Anzeige nicht je
# Herkunft zwei Vokabulare kennen müssen; der Originaltext bleibt in `raw` erhalten.
_EXTERN_UNLOCK_TYPES: tuple[tuple[str, int], ...] = (
    ('karte', 7),          # 'Karte entsperren'
    ('card', 7),
    ('finger', 8),
    ('passwort', 4),
    ('passcode', 4),
    ('code', 4),
    ('app', 1),
    ('schlüssel', 10),
    ('key', 10),
)


def extern_record_type(unlock_type: Optional[str]) -> Optional[int]:
    """'Unlock Type' aus dem Fremd-Export auf einen recordType abbilden; None,
    wenn die Bezeichnung unbekannt ist (dann trägt nur `methode` den Originaltext)."""
    text = (unlock_type or '').strip().lower()
    if not text:
        return None
    for stichwort, code in _EXTERN_UNLOCK_TYPES:
        if stichwort in text:
            return code
    return None


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
    """Gespiegeltes Schloss/Tür-Inventar (aus v3/lock/list) oder externes Schloss."""
    id: Optional[int] = None
    ttlock_lock_id: Optional[int] = None          # NULL bei quelle='extern'
    quelle: str = QUELLE_TTLOCK
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
    # per Subquery befüllt: seit wann gilt der aktuelle gateway_online-Status (#82)
    gateway_online_seit: Optional[str] = None
    # per Subquery befüllt: wer den letzten Vorgang ausgelöst hat (Mitglied > Chip >
    # Cloud-Credential-Name > TTLock-Konto) — Anzeige "vor 12 min · IC-Karte – Max M."
    letztes_event_wer: Optional[str] = None
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
    # Kontoname desselben Chips in einer Fremdanlage ('Unlock Account' im Tor-Export) –
    # nur darüber lässt sich deren Log auf Chip → Mitglied auflösen.
    externe_kennung: Optional[str] = None
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
    """Append-only Zutrittslog.

    Zwei Herkünfte, eine Tabelle: TTLock-Records (aus v3/lockRecord/list, dedupe über
    `ttlock_record_id`) und importierte Zeilen einer Fremdanlage (`quelle='extern'`,
    dedupe über Schloss + `lock_date` + `extern_konto`). Alles darunter – Auswertung,
    Anzeige, Prune – behandelt beide gleich."""
    id: Optional[int] = None
    ttlock_record_id: Optional[int] = None        # NULL bei quelle='extern'
    schloss_id: int = 0
    quelle: str = QUELLE_TTLOCK
    extern_konto: Optional[str] = None            # 'Unlock Account' der Fremdanlage
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


@dataclass
class TuerSchlossStatusLog:
    """Append-only Konnektivitäts-Log je Schloss (#82): ein Eintrag je online↔offline-
    Wechsel. `online` ist tri-state (TRUE/FALSE/NULL=unbekannt); `geaendert_am` = seit
    wann dieser Status gilt."""
    id: Optional[int] = None
    schloss_id: int = 0
    online: Optional[bool] = None
    geaendert_am: Optional[str] = None
    created_at: Optional[str] = None
