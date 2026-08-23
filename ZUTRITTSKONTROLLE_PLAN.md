# Plan: Zutrittskontrolle / Schließsystem (TT-Lock)

> Status (2026-08-18): **Phasen 1–4 umgesetzt und auf `master`** (ursprünglich
> Schema v58): Read-only (Inventar/Logs), Fernöffnen/-verriegeln, Chip-Verwaltung über
> die Cloud (anlernen/ändern/entziehen + IC-Card-Import), Abteilungs-Scoping +
> DSGVO-Hinweis, kurzzeitige App-Betätigungs-Berechtigung, Self-Service-Sicht und
> Alarm-Benachrichtigungen. Seither ausgebaut bis Schema **v96** — die Abschnitte
> weiter unten sind die jeweils aktuelle Beschreibung (externes Schloss v90,
> Chip-Inhaber ohne Mitgliedschaft v91, Verursacher in der Log-Zeile v92,
> Rechtegruppen v93, Konten ohne Zugang v96).
>
> **Erledigt seit dem letzten Kopf:** die Log-Retention. `tuer_zutritt_log`,
> `tuer_schloss_status_log` und das Zugriffsprotokoll laufen über das
> `LOG_REGISTRY` in `app/services/prune_service.py`, Frist je Regel auf der
> Datenbereinigungs-Seite einstellbar. Kein Protokoll wird unbegrenzt aufbewahrt.
>
> **Offen:** Phase 5 (Zutrittslog vollständig auf Mitglieder auflösen) nur teils,
> s. u.; feineres Alarm-Empfänger-Scoping; Auswertungen/Reports.
>
> **Nachtrag v59 (2026-06-30, #62):** read-only **Credential-Übersicht je Schloss**
> (`tuer_credential`: Fingerprint/Passcode/eKey/IC am Schloss, 1:1 aus der Cloud gespiegelt,
> kein Personen-Bezug). Baustein für die **geplante Phase 5: Zutrittslog vollständig auf
> Mitglieder auflösen** (s. u.) – heute löst `logs_sync()` nur die IC-Karte auf ein Mitglied auf.
>
> Phase 2 konkret: IC-Card-Writes über Gateway (`identityCard/add|changePeriod|delete`)
> als signierter POST, `chip_anlernen`/`berechtigung_aendern`/`berechtigung_entziehen` im
> `ZutrittService`, `ic_cards_sync` (am Schloss per BLE angelernte Karten → Chips/
> Berechtigungen spiegeln, idempotent), API `POST/PUT/DELETE /berechtigungen`, Anlern-/
> Ändern-/Entziehen-Dialoge im Schloss- und Chip-Detail. Cloud-Writes wurden mit Fakes
> unit-getestet, **noch nicht** live gegen ein echtes Schloss ausgeführt (braucht
> gerätegenaue Freigabe).
>
> Voraussetzung vom Verein bestätigt: **An allen Standorten sind Gateways vorhanden.**
> Damit ist Fern­verwaltung (Chips anlernen/sperren) **und** automatischer Log-Abruf
> ohne physische Bluetooth-Nähe möglich.

## Kernidee

Die App wird **Orchestrierungs-/Verwaltungsschicht über der TTLock-Cloud-API**
(API-Host `euapi.ttlock.com`; `euopen.ttlock.com` ist nur das Entwickler-Portal),
**nicht** der Schloss-Controller. Die TTLock-Cloud bleibt
**Quelle der Wahrheit** für Schlösser, Karten und Roh-Logs; wir

1. **spiegeln** Inventar (Schlösser, Gateways) und **Zutrittslogs** in unsere DB,
2. **verknüpfen** TTLock-IC-Cards (RFID-Chips) mit **Mitgliedern** und Schlössern,
3. **steuern** Berechtigungen (Chip an Schloss anlernen/sperren, Gültigkeitszeitraum)
   über die API – per Gateway also remote.

Der entscheidende Hebel: TTLock-IC-Cards haben einen **Gültigkeitszeitraum**
(`startDate`/`endDate`, ms). Das mappt 1:1 auf unser `gueltig_von`/`gueltig_bis` →
zeitlich befristeter Zutritt, **Ablauf erzwingt das Schloss selbst** (kein Cronjob nötig,
nur Verlängern/Sperren ist eine API-Aktion).

## Was die TTLock-API liefert (End-to-End verifiziert 2026-06-29)

> Per Wegwerf-PoC `tools/ttlock_poc.py` (read-only) gegen ein echtes Test-Schloss
> bestätigt: Login → Inventar → Gateways → IC-Cards → Zutrittslogs laufen sauber durch.
> **API-Host ist `euapi.ttlock.com` (EU)** – `euopen.ttlock.com` ist nur das
> Dev-Portal und liefert auf `/oauth2/token` ein HTML-404.

- **Auth (OAuth2):** `POST https://euapi.ttlock.com/oauth2/token` mit `clientId`,
  `clientSecret`, `username`, `password = MD5(klartext)` (lowercase hex),
  `grant_type=password` → `access_token`, `refresh_token`, `expires_in` (≈ **90 Tage**,
  7.776.000 s), `uid`. Refresh via `grant_type=refresh_token`. **Jeder** API-Call braucht
  zusätzlich `clientId`, `accessToken` und `date` (13-stelliger ms-Timestamp).
  Zwei getrennte Konten: **Dev-Account** (Portal euopen → clientId/clientSecret) ≠
  **TTLock-App-Konto** (besitzt die Schlösser → `username`/`password`).
- **Inventar:** `v3/lock/list`, `v3/lock/detail`, `v3/gateway/listByLock`.
  `lock/list` liefert u. a. `lockId`, `lockAlias` (Anzeigename), `lockName`
  (Werksname), `lockMac`, `electricQuantity` (**Akku %**) + `…UpdateDate`,
  `hasGateway` (0/1), `passageMode`, `timezoneRawOffset`.
  **Nicht spiegeln** (sicherheitsrelevant/irrelevant): `lockData` (BLE-Schlüsselblob),
  `noKeyPwd` (Admin-Passcode), `featureValue`, `specialValue`.
- **Gateways:** `v3/gateway/listByLock` → `gatewayId`, `gatewayName`, `gatewayMac`,
  `rssi` + `rssiUpdateDate` (Signal/letzter Kontakt). **Achtung:** *kein* `isOnline`-Feld
  hier – den **Online-Status** liefert nur `v3/gateway/list` (account-weit). PoC zeigte
  daher `online=None`; in der echten Sync `gateway/list` für den Online-Status nutzen.
- **IC-Cards (Chips):** `v3/identityCard/list` (→ `cardId`, `cardNumber`, `cardName`,
  `startDate`, `endDate`, `status`, `cardType`, `userId`/`senderUsername`/`nickName`,
  `createDate`), `…/add` (mit `addType=2` = **über Gateway** remote, plus
  `startDate`/`endDate`), `…/changePeriod` (Gültigkeit ändern), `…/delete`, `…/clear`.
- **Zutrittslogs:** `v3/lockRecord/list` (Params `lockId`, `startDate`, `endDate`,
  `pageNo`, `pageSize≤100`) → je Eintrag:
  - **`recordId`** (BIGINT, eindeutig je Record) → **idealer Dedupe-/Idempotenz-Schlüssel**.
  - `recordType` (logische Methode, s. Schlüssel unten) + `recordTypeFromLock`
    (Rohcode der Hardware, z. B. 26 → nur forensisch).
  - `success` (0/1), `lockDate` (Ereigniszeit am Schloss, ms),
    `serverDate` (Server-Empfang, ms) → **Sync-Cursor**.
  - `username` (TTLock-User), `keyName` (Label der Berechtigung),
    `keyboardPwd` (= Passcode bzw. IC-Card-Nummer, oft leer), `hotelUsername`.

### Wichtige Randbedingungen (vor der Umsetzung wissen)

- **API-Account muss Lock-Admin sein:** Die Schlösser müssen unter dem von uns
  genutzten TTLock-Konto initialisiert (oder als **Admin** dorthin übertragen) sein,
  sonst sind nur Lese-Operationen möglich.
- **Neuen Chip anlernen braucht einmal die Kartennummer.** Server-seitig haben wir
  weder Bluetooth noch NFC. Zwei Wege:
  1. **Am Schloss scannen** (TTLock-Admin-App per BLE) → Karte landet in der Cloud →
     wir ziehen sie per `identityCard/list`. *Empfohlen für den Rollout (keine
     Zusatz-Hardware).*
  2. Kartennummer mit separatem RFID-Leser erfassen → per `identityCard/add`
     (`addType=2`, Gateway) auf beliebige Schlösser pushen.
  → **Reines In-App-Anlernen unbekannter Chips ist nicht möglich**; bekannte
     Kartennummern lassen sich dank Gateway aber remote auf jede Tür verteilen.
- **TTLock-`cardId` ist pro Schloss.** Ein physischer Chip an 3 Türen = 3 TTLock-Cards
  = 3 Berechtigungs-Zeilen bei uns. Unser Modell trennt deshalb **Chip** (physisch,
  ↔ Mitglied) von **Berechtigung** (Chip ↔ Schloss, trägt die per-Schloss `cardId`).
- **Logs landen nur bei online-Gateway in der Cloud** (bei uns überall gegeben);
  trotzdem Lücken bei Gateway-/WLAN-Ausfall möglich → Sync ist „best effort".
- **`recordType` ist numerisch** und muss auf lesbare Methoden gemappt werden
  (vollständiger Schlüssel s. u.). Beachte: es gibt **Entriegeln *und* Verriegeln**
  als eigene Codes; für ein reines „Zutritts"-Protokoll ggf. nur die Unlock-/Alarm-Codes
  anzeigen und die Lock-Codes (33–36, 47) ausfiltern.

### recordType-Schlüssel (vollständig, aus der TTLock-Doc, 2026-06)

Quelle: `euopen.ttlock.com/doc/api/v3/lockRecord/list`. 1:1 im PoC hinterlegt
(`tools/ttlock_poc.py`, `RECORD_TYPES`) → später nach `app/models/schliessanlage.py`.

| Code | Bedeutung | Code | Bedeutung |
|---|---|---|---|
| 1 | App entriegeln | 30 | Türmagnet zu |
| 2 | Parklücke berührt | 31 | Türmagnet auf |
| 3 | Gateway (remote) | 32 | Von innen geöffnet |
| 4 | Passcode | 33 | Verriegelt (Fingerprint) |
| 5 | Parksperre hoch | 34 | Verriegelt (Passcode) |
| 6 | Parksperre runter | 35 | Verriegelt (IC-Karte) |
| 7 | IC-Karte | 36 | Verriegelt (mech. Schlüssel) |
| 8 | Fingerprint | 37 | Fernbedienung |
| 9 | Armband | 44 | **Sabotage-Alarm** |
| 10 | mech. Schlüssel | 45 | Auto-Lock |
| 11 | Bluetooth-Verriegeln | 46 | Entriegeln (Unlock-Key) |
| 12 | Gateway (remote) | 47 | Verriegeln (Lock-Key) |
| 29 | Unerwartet entriegelt | 48 | Mehrf. Falsch-Passcode |

> Enum kann je Schloss-/Protokolltyp leicht variieren; unbekannte Codes als `?<n>`
> durchreichen statt hart zu mappen (so macht es der PoC schon).

## Entscheidungen (Vorschlag – mit User abzustimmen)

- **Ein TTLock-Konto** für den ganzen Verein; `clientSecret` + Konto-Passwort kommen
  aus **Env/Secret** (`.env`), **nur Tokens** liegen in der DB. (Kein Klartext-Secret
  in der DB.)
- **Berechtigungen** über das bestehende **Permission-Matrix-System** (neue Keys, s.u.),
  zunächst **global**, **Scoping je Abteilung** als Phase 3 – analog zum Pilot
  Personen-/Mitgliederliste (`schloss.abteilung_id` trägt den Scope).
- **Logs** sind **append-only** in unserer DB (kein History-Mirror nötig, es *ist* schon
  ein Log) und unterliegen einem **Aufbewahrungs-/Löschkonzept** über das vorhandene
  **Prune-System** (`prune_einstellungen`/`prune_service`).
- **Ein TTLock-Konto, fest in `.env`** (keine Mehrkonten-Verwaltung in der UI). `ttlock_konto`
  hält nur Laufzeit-Tokens + Sync-Status, **kein** zweites Konto-Konzept.
- **Log-Sync**: (a) **periodischer Hintergrund-Sync, ein paar Mal am Tag** (Default **alle 6 h
  = 4×/Tag**, per Setting/Env justierbar) **plus** (b) **on-demand**-Button „Jetzt
  synchronisieren" auf der Log-Ansicht. Beides über denselben `logs_sync()`-Pfad mit Cursor.
  API-Budget unkritisch: selbst 20 Schlösser × 4×/Tag × 30 ≈ 2.400 Calls/Monat (Limit 30.000).

## Berechtigungen (neue Keys in `app/models/permission.py`)

```python
# --- Zutrittskontrolle / Schließsystem (TT-Lock) ---
SCHLIESSANLAGE_READ      = 'schliessanlage.read'       # Schlösser/Chips/Berechtigungen + Logs sehen
SCHLIESSANLAGE_VERWALTEN = 'schliessanlage.verwalten'  # Chips ↔ Mitglied, Berechtigungen vergeben/sperren, Inventar pflegen
SCHLIESSANLAGE_PROTOKOLL = 'schliessanlage.protokoll'  # Zutrittsprotokoll (Bewegungsdaten) einsehen – DSGVO-sensibel, eigenes Recht
SCHLIESSANLAGE_OEFFNEN   = 'schliessanlage.oeffnen'    # Schloss per App fernöffnen/-verriegeln (Gateway)
```

Admin bleibt uneingeschränkt (`has_permission` liefert für `role='admin'` True).
`schliessanlage.protokoll` bewusst **getrennt** vom normalen Read, weil Logs
personenbezogene Bewegungsdaten sind. `schliessanlage.oeffnen` ist das **globale**
Betätigungsrecht (Staff/Admin); zusätzlich darf öffnen, wer eine **gültige Berechtigung**
für genau dieses Schloss hat (Self-Service, s. Datenmodell `user_has_valid_for_schloss`).

## Datenmodell (Migration v57)

```sql
-- TTLock-Konto-/Token-Status (eine Zeile; Secrets NICHT hier, nur Laufzeit-Tokens)
CREATE TABLE ttlock_konto (
  id              SERIAL PRIMARY KEY,
  endpoint        TEXT NOT NULL DEFAULT 'https://euapi.ttlock.com',  -- API-Host (NICHT euopen.*)
  ttlock_uid      BIGINT,                 -- uid aus dem Token-Response
  access_token    TEXT,
  refresh_token   TEXT,
  token_expires_at TIMESTAMPTZ,
  letzter_sync_at TIMESTAMPTZ,
  version/created_*/updated_*             -- Standard-Audit (kein Soft-Delete)
);

-- Schloss/Tür-Inventar (gespiegelt aus v3/lock/list)
CREATE TABLE tuer_schloss (
  id               SERIAL PRIMARY KEY,
  ttlock_lock_id   BIGINT NOT NULL UNIQUE, -- lockId der TTLock-Cloud
  name             TEXT NOT NULL,          -- z. B. "Geschäftsstelle Eingang"
  standort         TEXT,
  abteilung_id     INTEGER REFERENCES abteilungen(id),  -- NULL = vereinsweit (Scope)
  ttlock_gateway_id BIGINT,                -- gatewayId aus gateway/listByLock
  lock_mac         TEXT,                   -- lockMac (Diagnose)
  akku_prozent     INTEGER,                -- electricQuantity (für „Akku schwach")
  akku_stand_at    TIMESTAMPTZ,            -- electricQuantityUpdateDate
  aktiv            BOOLEAN NOT NULL DEFAULT true,
  notiz            TEXT,
  letzter_log_serverdate BIGINT,           -- Sync-Cursor (serverDate ms) je Schloss
  letztes_event_at TIMESTAMPTZ,            -- für Status-Liste: Zeit des jüngsten Logs
  letztes_event_type INTEGER,              -- recordType des jüngsten Logs (Status-Anzeige)
  version/created_*/updated_*/deleted_*    -- Standard-Audit + Soft-Delete
);
-- letztes_event_* werden in logs_sync() denormalisiert mitgeführt, damit die
-- Schloss-Liste „Akku + letzter Schließvorgang" ohne Log-Join anzeigen kann.

-- Physischer Chip ↔ Mitglied (unser Konzept, schloss-unabhängig)
CREATE TABLE schluessel_chip (
  id            SERIAL PRIMARY KEY,
  kartennummer  TEXT NOT NULL,             -- physische IC-Card-Nummer
  bezeichnung   TEXT,                      -- z. B. "Chip blau #14"
  mitglied_id   INTEGER REFERENCES mitglied(id),  -- Inhaber, falls personalisiert ausgegeben
  aufbewahrungsort TEXT,                   -- Standard-Standort, falls NICHT personalisiert
                                           -- (z. B. "Schlüsselkasten Geschäftsstelle")
  status        TEXT NOT NULL DEFAULT 'aktiv',    -- aktiv | gesperrt | verloren
  version/created_*/updated_*/deleted_*
);
-- Inhaber XOR Standort: mitglied_id gesetzt = ausgegeben; sonst Pool-Chip mit aufbewahrungsort
-- (seit Schema v91 zusätzlich user_id als zweite mögliche Inhaberschaft, s.u.)
-- partieller Unique-Index auf kartennummer WHERE deleted_at IS NULL

-- Berechtigung: Chip an einem Schloss = eine TTLock-IC-Card
CREATE TABLE tuer_berechtigung (
  id             SERIAL PRIMARY KEY,
  chip_id        INTEGER NOT NULL REFERENCES schluessel_chip(id),
  schloss_id     INTEGER NOT NULL REFERENCES tuer_schloss(id),
  ttlock_card_id BIGINT,                   -- cardId der TTLock-Card (pro Schloss), NULL solange pending
  gueltig_von    TIMESTAMPTZ,              -- NULL = unbefristet
  gueltig_bis    TIMESTAMPTZ,
  sync_status    TEXT NOT NULL DEFAULT 'pending', -- pending | aktiv | fehler | gesperrt
  sync_fehler    TEXT,
  erteilt_von    INTEGER REFERENCES users(id),
  version/created_*/updated_*/deleted_*
);
-- Unique (chip_id, schloss_id) WHERE deleted_at IS NULL

-- Zutrittslog (append-only, gespiegelt aus v3/lockRecord/list)
CREATE TABLE tuer_zutritt_log (
  id               SERIAL PRIMARY KEY,
  ttlock_record_id BIGINT NOT NULL UNIQUE, -- recordId → idempotenter Sync (1 Feld genügt!)
  schloss_id       INTEGER NOT NULL REFERENCES tuer_schloss(id),
  record_type      INTEGER,                -- TTLock recordType (logisch)
  record_type_from_lock INTEGER,           -- recordTypeFromLock (Hardware-Rohcode, forensisch)
  methode          TEXT,                   -- gemappt: 'ic_card' | 'passcode' | 'app' | ...
  erfolg           BOOLEAN,                -- success 0/1
  credential       TEXT,                   -- keyboardPwd (Kartennummer/Passcode)
  key_name         TEXT,                   -- keyName (Label der Berechtigung)
  ttlock_username  TEXT,                   -- username aus dem Record
  chip_id          INTEGER REFERENCES schluessel_chip(id),  -- aufgelöst, falls Kartennummer matcht
  mitglied_id      INTEGER REFERENCES mitglied(id),         -- aufgelöst über Chip
  lock_date        TIMESTAMPTZ,            -- lockDate – Ereigniszeit am Schloss
  server_date      BIGINT,                 -- serverDate (ms) – Cursor-Basis
  raw              JSONB,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Unique (ttlock_record_id) → echter idempotenter Sync; Cursor = MAX(server_date) je Schloss
```

Alle Domänentabellen bekommen `*_history` + Audit-Trigger (Insert/Update) wie üblich –
**außer `tuer_zutritt_log`** (reiner Append-Log, kein History-Mirror; Löschung nur per
Prune/DSGVO). Frischaufbau-Pfad (`_create_tables`), Indizes und Migrationspfad
(`_migrate_v56_to_v57`) synchron halten; `SCHEMA_VERSION = 57`.

## Services

- **`app/services/ttlock_client.py` (neu)** – dünner HTTP-Client:
  Token holen/refreshen (proaktiv vor `token_expires_at`), signierte Requests
  (`clientId`+`accessToken`+`date`), Wrapper für `lock/list`, `gateway/listByLock`,
  `identityCard/{list,add,changePeriod,delete}`, `lockRecord/list`. TTLock-Fehler-
  Envelope (`errcode != 0`) → Exception. **Kein** DB-Zugriff (rein API).
- **`app/services/zutritt_service.py` (neu)** – Domänen-Orchestrierung:
  - `inventar_sync()` – Schlösser/Gateways spiegeln (`lock/list` + `gateway/list` für
    den **Online-Status**, `gateway/listByLock` für die Schloss↔Gateway-Zuordnung; Akku
    aus `electricQuantity`).
  - `chip_anlernen(chip, schloss, von, bis)` – `identityCard/add` (Gateway) →
    `ttlock_card_id` + `sync_status` setzen.
  - `berechtigung_aendern/sperren` – `changePeriod`/`delete`.
  - `logs_sync(schloss, seit_cursor)` – `lockRecord/list` paginiert, dedupe über
    **`ttlock_record_id` (recordId)**, Kartennummer → Chip → Mitglied auflösen, Cursor
    (`MAX(serverDate)`) fortschreiben.
- Secrets (`clientId`/`clientSecret`/Konto-Login) aus `app/config`/Env; nur Tokens via
  `ttlock_konto`-Repo.

## Betroffene Dateien

**Backend**
- `vtb_verein/app/db/database.py` – Migration v56→v57, `SCHEMA_VERSION=57`,
  Fresh-Schema, Audit-Funktionen/Trigger/Indizes (für die 4 Domänentabellen).
- `vtb_verein/app/models/permission.py` – 3 neue Permission-Konstanten.
- `vtb_verein/app/models/schliessanlage.py` – **neu** (`TuerSchloss`, `SchluesselChip`,
  `TuerBerechtigung`, `TuerZutrittLog`, `TTLockKonto`, `recordType`/Methoden-Mapping).
- `vtb_verein/app/db/*_repository.py` – **neu**: `tuer_schloss_repository.py`,
  `schluessel_chip_repository.py`, `tuer_berechtigung_repository.py`,
  `tuer_zutritt_log_repository.py`, `ttlock_konto_repository.py`.
- `vtb_verein/app/services/ttlock_client.py`, `zutritt_service.py` – **neu**.
- `vtb_verein/app/db/datastore.py` – Repos + `ZutrittService` instanziieren/verdrahten.
- `backend/api/schliessanlage.py` – **neu**: Endpunkte für Schlösser, Chips,
  Berechtigungen (vergeben/sperren), Logs (lesen + „Jetzt synchronisieren"), Inventar-
  Sync; Router in `backend/api/__init__.py`/App registrieren.

**Frontend** – neue Karte/Nav **„Schließanlage"** mit **Master-Detail** statt Matrix/
Protokoll-Tabs. Zwei Listen-Tabs, Detail-Drawer/-Seite je Eintrag:

- `frontend/src/pages/SchliessanlagePage.vue` – **neu**, zwei Tabs:
  - **Schlösser** (Liste): je Schloss **Status** – Akku (`akku_prozent`), letzter
    Schließvorgang (`letztes_event_at` + gemappter `letztes_event_type`), Gateway-/Online-
    Status, aktiv. **Detail** je Schloss:
    - **Zutritts-Logs** dieses Schlosses (hinter `schliessanlage.protokoll`),
    - **zugeteilte Chips** (welche Berechtigungen/Chips hängen an dieser Tür, mit
      Gültigkeit + Inhaber/Standort).
  - **Chips** (Liste): je Chip Bezeichnung, Status, **wem ausgegeben** (`mitglied_id`)
    **bzw. Standardstandort** (`aufbewahrungsort`). **Detail** je Chip:
    - **welche Schlösser** der Chip aufsperrt (Berechtigungen, Gültigkeit),
    - **Nutzungs-Log**: wann an welchem Schloss benutzt (Logs gefiltert auf `chip_id`,
      hinter `schliessanlage.protokoll`).
- Inventar-/Log-Sync-Button („Jetzt synchronisieren") + Anzeige `letzter_sync_at`.
- Nav-Eintrag + Route-Guard auf `schliessanlage.read`; alle **Log-/Nutzungs-Ansichten**
  (Bewegungsdaten) zusätzlich hinter `schliessanlage.protokoll`. Inventar-/Chip-Pflege
  hinter `schliessanlage.verwalten`.
- (Phase 4) Self-Service: im Mitglied-/Profil eigene Chips + letzte Zutritte.

**Tests**
- `vtb_verein/tests/test_zutritt_service.py` – Log-Dedupe/Cursor, Kartennummer→Chip→
  Mitglied-Auflösung, Gültigkeits-Mapping (ms↔TIMESTAMPTZ), Fehlerpfade (Fakes für den
  TTLock-Client, analog bestehender Service-Tests).
- `vtb_verein/tests/test_ttlock_client.py` – Request-Signatur (date/accessToken),
  Token-Refresh, `errcode`-Fehler-Envelope (gemockte HTTP-Antworten).

## Phasen

1. ✅ **Fundament & Read-only (umgesetzt):** TTLock-Client + Auth/Token-Refresh,
   Inventar-Sync (Schlösser/Gateways), **Log-Sync + Anzeige**, Cron-Command, API + UI.
   Zusätzlich vorgezogen: **Fernöffnen/-verriegeln per App** (`v3/lock/unlock|lock`,
   Recht `schliessanlage.oeffnen` ODER gültige Berechtigung).
2. ✅ **Chip-Verwaltung (umgesetzt):** Chips ↔ Mitglieder pflegen, Berechtigungen
   vergeben/verlängern/entziehen über Gateway (`identityCard/add|changePeriod|delete`),
   Gültigkeitszeiträume, Kartennummer→Chip-Auflösung in den Logs, plus `ic_cards_sync`
   (am Schloss angelernte Karten spiegeln). **Erst hiermit** trägt der Self-Service-Pfad
   des Fernöffnens echte Daten. Cloud-Writes sind unit-getestet (Fakes), aber noch nicht
   live an einem echten Schloss verifiziert (gerätegenaue Freigabe nötig).
3. **Rechte & DSGVO (teilweise umgesetzt):** Permission-Matrix-Integration ✅ und
   **Abteilungs-Scoping** ✅ (`schloss.abteilung_id`, analog Personen-Pilot):
   `backend/core/scope.py` → `visible_schloss_ids` (Listen-Filter) + `darf_schloss`
   (vereinsweite Schlösser = `abteilung_id IS NULL` verlangen das vereinsweite Recht;
   abteilungsgebundene erfüllt global ODER für die Abteilung). Durchgesetzt je Schloss
   für Detail/Verwalten/Protokoll/Öffnen/Verriegeln und Berechtigungs-Aktionen; Detail
   liefert per-Schloss `darf_*`-Flags; Umhängen der Abteilung nur vereinsweit; account-
   weiter Sync nur vereinsweit (`darf_sync`); Chip-Detail filtert Schlösser/Logs auf den
   Scope. **Datenschutzhinweis** an den Protokoll-Ansichten ✅. **Log-Aufbewahrung** (append-
   only → alters-basiertes Löschen) wird **ins allgemeine Prune** gezogen statt hier separat
   gebaut → als TODO in `TODO.md` notiert (Retention-Dauer dort festzulegen).
4. **Komfort (umgesetzt):** **Self-Service-Sicht** ✅ – `GET /schliessanlage/mein-zugang`
   (eigene Chips, Türen, befristete App-Berechtigungen, letzte eigene Zutritte über das
   verknüpfte Mitglied; kein schliessanlage-Recht nötig, nur eigene Daten) + Card „Mein
   Zugang" in der ProfilePage. **Kurzzeitige App-Betätigungs-Berechtigung** ✅ (s. u.).
   **Event-Benachrichtigungen** ✅ – `ALARM_RECORD_TYPES` (44 Sabotage, 48 mehrf.
   Falsch-Passcode); `logs_sync` meldet nur **neue** Alarm-Records, `notify_alarme` schickt
   einen Sammel-Digest an aktive Admins über das bestehende Notification-System (E-Mail/
   Matrix), verdrahtet in API-`/sync` und Cron. **Offen:** Empfänger feiner als „alle
   Admins" (z. B. abteilungsgebunden), Auswertungen/Reports.

### Geplante Erweiterung: kurzzeitige App-Betätigungs-Berechtigung (Phase 4)

Ziel: Einer **konkreten Person (User)** befristet das Recht geben, ein **bestimmtes
Schloss per App zu öffnen** – ohne physischen Chip und ohne dauerhaftes Recht. Use-Cases:
Handwerker/Reinigung für einen Tag, Gast-Übungsleiter für ein Wochenende, Vertretung.

- **Datenmodell:** neue Tabelle `tuer_app_berechtigung` (`user_id`, `schloss_id`,
  `gueltig_von`, `gueltig_bis`, `grund`, `erteilt_von`, +Audit/Soft-Delete). Bewusst
  getrennt von `tuer_berechtigung` (= Chip↔Schloss/IC-Card), weil es hier **keinen Chip**
  gibt, sondern nur das App-/Gateway-Öffnen.
- **Autorisierung:** `_darf_oeffnen()` zusätzlich gegen diese Tabelle prüfen (User hat
  einen aktiven, im Gültigkeitsfenster liegenden Eintrag für das Schloss). Globales Recht
  `schliessanlage.oeffnen` und Chip-Berechtigung bleiben die anderen beiden Wege.
- **Vergabe:** nur mit `schliessanlage.verwalten`; Dialog „Befristet öffnen erlauben"
  (User wählen, Schloss, von/bis, Grund). Ablauf erzwingt die App selbst über das
  Gültigkeitsfenster (kein Cronjob nötig); optional Soft-Delete zum vorzeitigen Entzug.
- **Nachvollziehbarkeit:** Vergabe/Entzug ins `access_log`; jede Nutzung erscheint
  ohnehin als Gateway-Event im Zutrittslog.
- **Kein TTLock-Schreibzugriff nötig:** rein lokale Berechtigung über das bereits
  verifizierte `v3/lock/unlock` – damit ohne Chip-Anlern-Abhängigkeit auch **vor** Phase 2
  baubar.

## Phase 5 (teils umgesetzt): Zutrittslog vollständig auf Mitglieder auflösen

Ziel: Jede Log-Zeile zeigt – soweit möglich – **welches Mitglied** mit **welcher Methode**
geöffnet hat.

> **Umgesetzt (#66, Teil A + B):**
> - **A – `key_name`-Fallback:** `logWer` zeigt den Cloud-Credential-Namen (`key_name`,
>   z. B. eKey-/Fingerprint-Label) als Fallback vor dem TTLock-Sammelkonto.
> - **B – App-/Gateway-Öffnung → Mitglied:** `logs_sync()` korreliert Gateway-Remote-Records
>   (`recordType ∈ {3, 12}`) per Zeit+Schloss mit dem `access_log`-Eintrag der App-Öffnung
>   (`schliessanlage_unlock`, `AccessLogRepository.find_schliessanlage_unlock_near`,
>   ±120 s) → VTB-User → verknüpftes Mitglied. **Ohne Migration** (nutzt vorhandene Daten),
>   kein Backfill (greift ab Einführung), keine Auflösung ohne verknüpftes Mitglied.
>
> **Verifiziert (dev-db + echte Test-Hardware, 2026-07-01):** Korrelations-SQL real gegen
> PG18 (`make_interval`/`EXTRACT EPOCH`/`::timestamptz`-Casts, `LIKE`-Präfix trennt Schloss
> 5/50); recordType einer echten App-Fernöffnung ist **12** (in `{3, 12}`); End-to-end
> (App-Öffnung → `logs_sync`) löst den Gateway-Record korrekt auf das verknüpfte Mitglied
> auf, Alt-Records ohne App-Öffnung bleiben ohne Personenbezug; realer Zeitversatz
> `lockDate` ↔ `access_log.created_at` ≈ **2 s** (120-s-Fenster großzügig).
>
> **Offen (Teil C):** Fingerprint/Passcode/eKey → Mitglied (s. u.) – braucht die
> Zuordnungsschicht + einen echten TTLock-Sync für die `credentialId`-Frage.

Vor Teil A/B löste `logs_sync()` **nur die IC-Karte** auf ein Mitglied auf
(`keyboardPwd` = Kartennummer → `schluessel_chip` → `mitglied`, nur `recordType ∈ {7, 35}`).
Fingerprint (8/33), Passcode (4/34) und **direkter** App/eKey (1/11) bleiben weiter ohne
Personenbezug – die Anzeige (`logWer` in `SchliessanlagePage.vue`) fällt dann auf
`chip_bezeichnung` bzw. `key_name`/`ttlock_username` (= TTLock-Sammelkonto) zurück.

### Auflösung je Methode

- **IC-Karte:** vorhanden (Kartennummer → Chip → Mitglied).
- **App-/Gateway-Öffnung über die VTB-App (Sonderfall – am einfachsten):** Wenn das Öffnen
  über *uns* läuft (`POST /schloesser/{id}/oeffnen` → `v3/lock/unlock`), **kennen wir den
  eingeloggten User exakt** und schreiben ihn bereits in `access_log`
  (`action='schliessanlage_unlock'`, `user_id`, Schloss, Zeit – s. `backend/api/schliessanlage.py`).
  TTLock zeigt dieselbe Aktion nur als „Gateway (remote)" (recordType 3/12) mit dem einen
  Sammelkonto `ttlock@…` – **nicht** unterscheidbar. Auflösung daher **nicht über TTLock,
  sondern per Korrelation TTLock-Record ↔ `access_log`** (gleiches Schloss, `lockDate` ≈
  `access_log.created_at` innerhalb eines kleinen Fensters) → echter VTB-User. Befristete
  App-Berechtigungen (Phase 4) sind damit automatisch mit abgedeckt.
  *Abgrenzung:* Gateway-Remote-Events **ohne** passenden `access_log`-Eintrag stammen aus
  der nativen TTLock-App/vom Admin → bleiben dem TTLock-Konto/„System" zugeordnet.
- **Fingerprint:** über `tuer_credential` (Typ fingerprint) am Schloss, Match per
  `fingerprintId` bzw. `keyName` ↔ zugeordnetem Mitglied.
- **Passcode:** über `tuer_credential` (Typ passcode) per `keyboardPwdId`/`keyName` –
  **Passcode-Wert ist sensibel, kein Klartext speichern/anzeigen.**
- **eKey (BLE direkt):** über `username`/eKey-Credential → Mitglied.

### Voraussetzung (Hauptarbeit für Fingerprint/Passcode/eKey)

Eine **Credential→Mitglied-Zuordnung für alle Typen**, analog zur Chip→Mitglied-Zuordnung
(#59). Fingerprint/Passcode/eKey existieren bisher nur als **read-only Cloud-Mirror**
(`tuer_credential`, v59) **ohne** Personen-Bezug; es fehlt die Zuordnungsschicht.

- **Datenmodell:** `mitglied_id` an `tuer_credential` (oder eigene Mapping-Tabelle) +
  Migration. Trennung Mirror (1:1 Cloud) vs. Zuordnung (unser Konzept) sauber halten.
- **UI:** in der Credential-Übersicht je Schloss ein Mitglied zuordnen – suchbares Dropdown
  wie bei der Chip→Mitglied-Zuordnung.
- **Resolver:** `logs_sync()` (bzw. ein nachgelagerter Resolve-Pass) setzt `mitglied_id`
  je `recordType` über die Zuordnung/Korrelation – optional **rückwirkend** (Backfill der
  bestehenden Logs) statt nur ab jetzt.
- **Frontend:** `logWer` um das aufgelöste Mitglied erweitern, `key_name` als Fallback.
- **DSGVO:** vollständige Auflösung erhöht den Personenbezug deutlich → Zweckbindung +
  Recht `schliessanlage.protokoll` bleiben Pflicht; Datenschutzhinweis ggf. schärfen.

### Offene Fragen

- Trägt `lockRecord` die `credentialId` (`fingerprintId`/`keyboardPwdId`) oder nur
  `keyName`? Entscheidet ID- vs. (fragiles) Namens-Matching – per echtem Sync/PoC prüfen.
- Korrelations-Fenster App-Öffnung ↔ `access_log` (Sekunden? Toleranz bei Gateway-Latenz)?
- Backfill der bestehenden Logs gewünscht oder nur ab Einführung?

**Aufwand:** App-/Gateway-Auflösung klein (Daten liegen schon vor); Fingerprint/Passcode/
eKey mittel–groß (Mapping + UI + Resolver + Migration + Tests). Eigener Branch.

## Externes Schloss ohne Cloud-Anschluss (umgesetzt, Schema v90)

Das Tor an der Einfahrt hängt an einer **eigenen Anlage**, wird aber mit **denselben
Chips** geöffnet. Es gehört fachlich in dieselbe Übersicht wie die TTLock-Schlösser –
nur kommt sein Log nicht per Sync, sondern als CSV-Export aus der Fremdanlage:

```
Unlock Account,Unlock Type, Lock Name,Unlock Time
Chip8,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05
```

**Entscheidung: eine Tabelle, zwei Herkünfte.** `tuer_schloss.quelle` und
`tuer_zutritt_log.quelle` (`ttlock` | `extern`) trennen die Welten, statt ein zweites
Log daneben zu stellen – Gesamt-Log, Schloss-Protokoll, Chip-Nutzung und „Mein Zugang"
funktionieren dadurch unverändert. Dafür wurden `ttlock_lock_id` und `ttlock_record_id`
optional; alles Bestehende bekam per DEFAULT `quelle='ttlock'`.

- **Dedupe** ohne recordId: partieller Unique-Index über
  `(schloss_id, lock_date, COALESCE(extern_konto,''))` für `quelle='extern'` – derselbe
  Export darf beliebig oft erneut eingelesen werden (auch überlappende Zeiträume).
- **Personenbezug**: Das Konto der Fremdanlage (`Unlock Account`) wird über
  `schluessel_chip.externe_kennung` → Bezeichnung → Kartennummer auf Chip und Mitglied
  aufgelöst (case-insensitiv, gepflegte Kennung gewinnt). Unbekannte Konten stehen im
  Import-Bericht; sobald jemand die Kennung am Chip pflegt, werden **früher importierte
  Zeilen nachträglich zugeordnet** (`resolve_extern_konto`).
- **Zeit**: Die Anlage schreibt naive Ortszeit; gespeichert wird wie überall UTC-ISO
  (`Europe/Berlin`, in der doppelten Stunde der Zeitumstellung gilt Sommerzeit).
- **Cloud-Operationen sind gesperrt**: Fernöffnen/-verriegeln, Anlernen und alle Syncs
  überspringen Schlösser ohne lockId (`list_all(nur_ttlock=True)`, `_cloud_schloss`).
  Das Schloss-Detail zeigt statt leerer Gateway-/Akku-/Credential-Kästen einen Hinweis.
- **Rechte**: `POST /api/schliessanlage/import` verlangt `schliessanlage.verwalten`
  **und** `schliessanlage.protokoll`, beides **vereinsweit**. Verwalten, weil der
  Import ein Schloss anlegen kann und Bewegungsdaten schreibt; Protokoll, weil der
  **Bericht selbst eine Nutzungsauswertung ist** (Person + Anzahl je Konto, Zeitraum
  je Schloss) – anders als bei `/sync`, dessen Antwort nur Zählwerte und Alarme
  enthält, käme man sonst am Protokollrecht vorbei an genau die Daten, die es
  schützt. Sichtbarkeit des Buttons über das eigene Flag `darf_import` aus `/status`,
  damit die Regel nicht im Frontend nachgebaut wird. Ohne `commit` reine Vorschau
  („Vorschau == Aktion").

Ein unbekannter `Lock Name` wird beim Lauf automatisch als externes Schloss angelegt
(die Vorschau kündigt das an); Standort/Abteilung/Notiz danach normal im
Stammdaten-Dialog pflegbar. Code: `app/services/zutritt_import_service.py`.

## Auswertung: „wer, wann, welche Tür" verdichtet (umgesetzt, #161)

Vierter Reiter neben Schlösser/Chips/Log. Kein neues Schema – reine Aggregation über
`tuer_zutritt_log`, hinter demselben Recht wie das Log (`schliessanlage.protokoll`) und
mit demselben Abteilungs-Scope: verdichtete Bewegungsdaten sind dieselbe DSGVO-Klasse
wie die Einzelzeilen, nur bequemer lesbar.

- **Grundmenge „Öffnung"**: Positivliste `OEFFNUNG_RECORD_TYPES` (App, Gateway,
  Passcode, IC-Karte, Fingerprint, Armband, mech. Schlüssel, von innen, Fernbedienung)
  plus Fremdanlagen-Zeilen ohne erkannten Typ, jeweils nur mit `erfolg IS NOT FALSE`.
  Verriegeln, Türmagnet, Auto-Lock und Alarme zählen bewusst nicht mit — sie würden die
  Rangliste verdoppeln. Fehlversuche und Alarme erscheinen separat als Randnotiz.
- **Ortszeit ist Pflicht**: `lock_date` steht als UTC-ISO in der Spalte; Stunde,
  Wochentag und „früheste Öffnung" ergeben nur in `Europe/Berlin` Sinn. Die Umrechnung
  passiert einmal in SQL (`AT TIME ZONE`), das Ergebnis geht als fertiger String raus –
  so kann im Frontend niemand ein zweites Mal umrechnen.
- **Aufteilung**: SQL-Aggregate im Repository (`auswertung()`), Aufbereitung im
  `zutritt_auswertung_service` (aufgefüllte Achsen, Anteile, Labels, Auszeichnungen),
  dünner Endpunkt `GET /api/schliessanlage/auswertung?tage=30|90|365|0`.
- **Auszeichnungen** (Frühaufsteher, Nachteule, Stammgast, meistgenutzte Tür,
  Wochenend-Held, Nachtschicht, Schlüsselbund, Rekordtag, längste Serie) erscheinen nur,
  wenn es sie wirklich gibt – ein leerer Zeitraum zeigt keine leeren Medaillen.
- **Verlauf** wird nach Spannweite gebündelt (bis 45 Tage täglich, bis 200 wöchentlich,
  darüber monatlich) und beginnt frühestens beim ersten Zutritt, damit „1 Jahr" bei
  einem Monat Daten keine elf leeren Monate zeigt.
- Diagramme sind reines CSS (keine Chart-Bibliothek): Säulen für Verlauf/Uhrzeit/
  Wochentag, liegende Balken für die Ranglisten – Balkenfarbe je Theme, in „VTB" gelb
  auf blauer Karte.

Aktuell 13 kleine Aggregat-Queries pro Aufruf über die volle Log-Tabelle. Bei ein paar
tausend Zeilen unkritisch; wenn das Log irgendwann sechsstellig wird, wäre ein
Ausdrucks-Index auf `(lock_date::timestamptz)` der erste Hebel.

## Chip-Inhaber ohne Mitgliedschaft (umgesetzt, Schema v91)

Nicht jeder mit Chip ist Mitglied: Platzwart, Hausmeister, Betreuer eines Gastvereins
haben ein App-Konto, aber keinen Mitgliedsdatensatz. Bisher blieben ihre Chips
zwangsweise „nicht zugeordnet" — seit dem Zuordnungs-Filter (#160) sogar standardmäßig
ausgeblendet. `schluessel_chip.user_id` ist deshalb die zweite mögliche Inhaberschaft.

- **Genau ein Inhaber**: `mitglied_id` ODER `user_id`, sonst Pool-Chip mit Standort. Die
  Regel steht in der API (`_inhaber_pruefen`, 400 mit Ansage), nicht als DB-CHECK — der
  müsste beim ALTER jede Altzeile mitprüfen und könnte nichts erklären.
- **Wer beides ist, hängt am Mitglied**: Wählt jemand im Picker ein Benutzerkonto mit
  verknüpftem Mitglied, schreibt der Endpunkt still auf `mitglied_id` um. Sonst gäbe es
  je nach Auswahl zwei Wahrheiten über dieselbe Person, und die Log-Auflösung
  (`tuer_zutritt_log.mitglied_id`) liefe ins Leere. Der Picker bietet solche Konten
  entsprechend gar nicht erst in der Benutzer-Gruppe an (`/users` liefert `mitglied_id`).
- **Namensauflösung**: Log-Anzeige und Auswertung setzen den Benutzernamen zwischen
  Mitglied und Chip-Bezeichnung (`_WER`, `user_username`).
- **Self-Service** greift über beide Wege: `user_has_valid_for_schloss` prüft Mitglied
  *und* `schluessel_chip.user_id`, „Mein Zugang" listet Chips aus beiden Quellen.
- Kein `PRUNE_REGISTRY`-Eintrag nötig: `users` wird bewusst nicht geprunt, der neue FK
  kann also nichts blockieren.

### Konten ohne Zugang: Schlüsselträger ohne App-Konto (Schema v96)

Der Absatz oben setzte voraus, dass der Platzwart wenigstens ein App-Konto hat. Viele
haben keins und sollen keins bekommen — sie tragen nur einen Schlüssel. Weil
`users.email` NOT NULL war, musste man für den Hausmeister eine Adresse erfinden, damit
sein Name an einem Chip stehen kann. Seit v96 geht das ehrlich:

- **Konto ohne Zugang** = `email IS NULL` UND `password_hash = ''`. Kein Anmeldeweg,
  weder Magic-Link noch Passwort. Angelegt wird es wie jedes Benutzerkonto
  (`personen.permissions`), nur ohne E-Mail und Passwort.
- **Solche Konten sind inaktiv** (`UserService._pruefe_anmeldeweg`): Ein aktives Konto
  ohne jeden Anmeldeweg wäre eine Karteileiche, die man für einen kaputten Zugang hält.
  Wer später eine E-Mail nachträgt oder ein Passwort setzt, kann es aktivieren.
- **Unique-Index mit Bedingung**: `uix_users_email_active` gilt nur noch
  `WHERE email IS NOT NULL` — sonst wäre schon der zweite Hausmeister ein Duplikat.
  NULL statt Leerstring auch deshalb, weil `WHERE email = %s` mit leer abgeschickter
  Adresse sonst ein fremdes Konto fände.
- **Der Chip-Picker zeigt sie** (`/schliessanlage/users` filtert nicht mehr auf `active`),
  die befristete **App-Öffnung nicht** — dort wäre die Berechtigung wirkungslos, der
  Endpunkt weist inaktive Konten mit 400 ab.
- **Anmeldung**: Konten ohne Passwort tragen jetzt einen leeren Hash statt eines
  bcrypt-Hashes über einen festen Platzhalter-Text. Der Text stand im Quelltext und war
  damit ein gültiges Passwort für jedes so angelegte Konto; für den Altbestand schließt
  `authenticate` ihn ausdrücklich aus.

### „Wer war es" gehört in die Log-Zeile, nicht an den heutigen Chip (Schema v92)

`tuer_zutritt_log.mitglied_id` ist seit jeher eine **Momentaufnahme**: beim Einfügen aus
dem damaligen Chip-Inhaber gestempelt, danach fest. Für Inhaber ohne Mitgliedsdatensatz
fehlte das Gegenstück — sie ließen sich nur über den heutigen `schluessel_chip.user_id`
auflösen. Chips werden aber weitergegeben, und `tuer_zutritt_log.chip_id` bleibt dabei
stehen: Der neue Inhaber hätte in „Mein Zugang" die Öffnungen seines Vorgängers gesehen,
mit Tür, Uhrzeit und Namen — an einer Stelle, die bewusst **ohne** `schliessanlage.protokoll`
läuft. Deshalb `tuer_zutritt_log.user_id`, gesetzt in beiden Schreibpfaden (Cloud-Sync und
Fremd-Log-Import, inkl. `resolve_extern_konto`).

- **Selbstauskunft** sucht nur noch über die gestempelten Personenspalten:
  `list_selbstauskunft(mitglied_id=…, user_id=…)` → `WHERE l.mitglied_id = … OR l.user_id = …`.
  Nie über die heutigen Chips.
- **Kein Backfill**: Vor v91 konnte kein Chip auf ein Konto laufen, es gibt also nichts
  richtig zuzuordnen — und aus dem heutigen Inhaber zu schließen wäre genau der Fehler.
  Zeilen aus dem Fenster zwischen v91 und v92 bleiben NULL und tauchen in keiner
  Selbstauskunft auf (fail closed).
- Dieselbe Momentaufnahme trägt die Auswertung: eine Chip-Weitergabe verschiebt dort
  keine Öffnungen mehr von einem Öffner zum nächsten.

## Akku schwach → internes Ticket (umgesetzt, Schema v110)

Der Ladestand kam mit jedem Inventar-Sync herein (`electricQuantity`) und stand in der
Liste; gehandelt hat trotzdem nur, wer hinschaute. Jetzt meldet sich die Anlage selbst:
Unterhalb einer eingestellten Schwelle legt sie ein **internes Ticket** im konfigurierten
Bereich an — über den regulären `TicketService`, also samt Benachrichtigung an die im
Bereich Zuständigen.

- **Stammdaten** (`schliessanlage_einstellungen`, Single-Row wie `fibu_einstellungen`):
  Ticket-Bereich, Schwelle in Prozent, Priorität. Gepflegt im Bereich Schließanlage,
  Reiter **Einstellungen** (vereinsweites `schliessanlage.verwalten`). **Ohne Bereich
  passiert nichts** — das ist der Aus-Schalter. Dieselbe Schwelle färbt auch die
  Akku-Anzeige („Akku niedrig"), damit es nicht zwei Begriffe davon gibt.
- **Ein Ticket je Entladung, nicht je Lauf:** `tuer_schloss.akku_ticket_id` merkt sich die
  offene Meldung. Der Sync läuft alle sechs Stunden — ohne Merker stünden nach einer Woche
  28 gleichlautende Tickets im Bereich. Freigegeben wird der Merker erst, wenn der Akku
  wieder ≥ Schwelle + 10 Prozentpunkte meldet (Batteriewechsel); bewusst **nicht** am
  Ticket-Status festgemacht, sonst käme ein zu früh geschlossenes Ticket sechs Stunden
  später als neues zurück. Der Merker wird ohne Versions-Bump geschrieben (Maschinen-
  zustand wie der Sync-Cursor) und erzeugt deshalb keine History-Zeile.
- **Kein FK** auf `tickets`/`ticket_bereiche`: beide sind geprunte Entitäten, ein FK
  zwänge zu einem `ChildRef` — und der würde beim Prune eines Bereichs die Einstellungen
  bzw. beim Prune eines Tickets das Schloss mitlöschen. Ein ins Leere zeigender Verweis
  ist folgenlos (gilt als „nicht eingerichtet" bzw. „kein offenes Ticket").
- **`tickets.gemeldet_von` ist jetzt optional:** Hinter einem automatischen Ticket steht
  kein Mensch; die API zeigt dort **„System"**. Ein Platzhalter-Benutzer wäre eine
  Behauptung über jemanden — samt dessen Benachrichtigungen und Leserecht am internen
  Ticket.
- **Wo es läuft:** am Ende des Syncs, wenn die Akkustände frisch sind — im Cron-Sidecar
  (`tools/zutritt_sync.py`) wie im on-demand-Sync der Seite
  (`app/services/schloss_akku_service.py`).

## Offene Punkte (vor/während Phase 1 klären)

- ~~**Scheduler für den 4×/Tag-Hintergrund-Sync.**~~ ✅ **entschieden 2026-06-29, umgesetzt
  2026-06-30:** Management-Command (`tools/zutritt_sync.py`) ruft Inventar-/IC-Card-/
  Log-Sync für alle aktiven Schlösser; robust, kein Worker-Duplikations-Problem. **Deployment:**
  eigener **docker-compose-Sidecar `zutritt-sync`** (gleiches Image wie `vtb-verein`, kein
  zweiter Build) mit Schleife `python tools/zutritt_sync.py; sleep TTLOCK_SYNC_INTERVAL_HOURS`
  (Default 6 h = 4×/Tag), `depends_on: vtb-verein (healthy)` damit die Migrationen durch sind,
  `restart: unless-stopped`. Für Bare-Metal alternativ Host-Cron/systemd-Timer auf denselben
  Command. Derselbe Sync-Pfad bedient den on-demand-Button „Jetzt synchronisieren".
- ~~**TTLock-Dev-Account-Freischaltung** (clientId/clientSecret) + **EU-Endpoint**
  bestätigen.~~ ✅ **erledigt 2026-06-29** (PoC): clientId/clientSecret gültig & EU,
  Endpoint `euapi.ttlock.com`. **Offen bleibt:** die echten Vereins-Schlösser als
  **Admin** unter das produktive API-Konto bringen (PoC lief gegen ein Einzel-Test-Schloss).
- ~~**`recordType`-Mapping** final aus der TTLock-Doc übernehmen.~~ ✅ **erledigt** –
  vollständiger Schlüssel oben dokumentiert und im PoC hinterlegt (`7` = IC-Karte bestätigt).
- **Gateway-Online-Status** kommt aus `gateway/list` (nicht `listByLock`) – in
  `inventar_sync()` berücksichtigen.
- **Chip-Erstanlernung**: Festlegen, ob am Schloss gescannt (Weg 1, empfohlen) oder mit
  RFID-Leser erfasst (Weg 2) wird; Mapping der **bestehenden** Chips ↔ Mitglieder.
- **Secret-Handling**: Ablage von `clientSecret`/Konto-Passwort (Env vs. Secret-Store);
  Tokens verschlüsselt at-rest?
