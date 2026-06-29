# Plan: Zutrittskontrolle / Schließsystem (TT-Lock)

> Status: geplant · Branch (vorgeschlagen) `feature/zutrittskontrolle` · Schema-Migration **v57**
> (Stand 2026-06-29: aktuelle `SCHEMA_VERSION = 56`, letzte Migration v55→v56 → Zutritt wird v57.
> Nummer vor Implementierung gegen `database.py` final prüfen, falls zwischenzeitlich Migrationen landen.)
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
```

Admin bleibt uneingeschränkt (`has_permission` liefert für `role='admin'` True).
`schliessanlage.protokoll` bewusst **getrennt** vom normalen Read, weil Logs
personenbezogene Bewegungsdaten sind.

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

1. **Fundament & Read-only (geringstes Risiko, sofort Nutzen):** TTLock-Client + Auth/
   Token-Refresh, Inventar-Sync (Schlösser/Gateways), **Log-Sync + Anzeige**. Noch
   **keine** schreibenden Schloss-Operationen. Liefert sofort sichtbare Zutrittslogs.
2. **Chip-Verwaltung:** Chips ↔ Mitglieder pflegen, Berechtigungen vergeben/verlängern/
   sperren über Gateway (`identityCard/add|changePeriod|delete`), Gültigkeitszeiträume,
   Kartennummer→Chip-Auflösung in den Logs.
3. **Rechte & DSGVO:** Permission-Matrix-Integration, **Abteilungs-Scoping**
   (`schloss.abteilung_id`, analog Personen-Pilot), Aufbewahrung/Löschung der Logs über
   das **Prune-System**, Datenschutzhinweis für Mitglieder.
4. **Komfort:** Self-Service-Sicht (eigene Chips/Zutritte), Benachrichtigungen bei
   relevanten Events (z. B. Sabotage-Alarm `recordType 44`) über das bestehende
   Notification-System, Auswertungen/Reports.

## Offene Punkte (vor/während Phase 1 klären)

- ~~**Scheduler für den 4×/Tag-Hintergrund-Sync.**~~ ✅ **entschieden 2026-06-29:**
  Management-Command (`tools/zutritt_sync.py` bzw. `python -m …`) ruft `logs_sync()` für
  alle aktiven Schlösser, getriggert per **externem Cron/systemd-Timer** – robust, kein
  Worker-Duplikations-Problem, passt zur bestehenden on-demand-Linie (so läuft auch `prune`).
  Derselbe Pfad bedient den on-demand-Button „Jetzt synchronisieren".
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
