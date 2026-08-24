# VTB Vereinsverwaltung

Moderne Web-Anwendung zur Verwaltung von Vereinsmitgliedern, Abteilungen, Mannschaften,
Beiträgen, Gebühren und Kassen.

**Tech-Stack:** Quasar/Vue (Frontend) · FastAPI (Backend) · PostgreSQL (psycopg3).
Die frühere NiceGUI/SQLite-Variante wurde abgelöst.

## Features

✅ **Personenverwaltung** (Benutzer + Mitglieder vereint)
- Eine „Personen"-Seite für System-Benutzer und Vereinsmitglieder
- Nur noch zwei Rollen: **`admin`** (uneingeschränkt) und **`mitglied`** *(v36)* — alles
  Weitere regelt die feingranulare Permission-Matrix
- **Zugänge**: Mitglieder werden einzeln für den Login freigeschaltet
  (`personen.freischalten`, v88); Konten ohne E-Mail sind zulässig *(v96)*, etwa für
  Schlüsselträger ohne App-Zugang. Die Übersicht zeigt je Konto, ob die letzte
  Einladung abgeschickt werden konnte *(v97)*; solange sich noch nie jemand
  angemeldet hat, lässt sich die Login-Adresse dort korrigieren und neu einladen —
  der bis dahin verschickte Anmeldelink wird damit ungültig
- E-Mail-Adressen werden beim Speichern auf ihren Aufbau geprüft (Login-Adresse,
  Kontakte, Tresor-Kontakte) — ein Vertipper legte sonst klaglos ein Konto an, an
  das nie eine Mail gehen kann
- Automatische Mitgliedsnummer-Vergabe (manuell überschreibbar)
- Persönliche Daten, Adresse, Vereinsdaten (Eintritt/Austritt/Status), Zahlungsdaten (IBAN/BIC)
- Der **Mitgliedsstatus** sagt nur, welche Form die Mitgliedschaft hat: `aktiv` oder
  `passiv` *(v103)*. Ob jemand noch dabei ist, entscheidet allein das Austrittsdatum —
  „ausgetreten"/„inaktiv" als Status waren eine zweite, konkurrierende Wahrheit.
  Angezeigt und gepflegt wird der Status nicht (er bleibt für Vereine, die ihn
  brauchen); die Berichte zeigen stattdessen **„davon in Abteilungen"** — Mitglieder
  mit einer heute laufenden, aktiven Abteilungs-Zuordnung
- Passwort-Hashing (bcrypt), Magic-Link-Login per E-Mail
- Anmelde-Bremse gegen Passwort-Raten: 10 Fehlversuche je Konto bzw. 30 je
  Verbindung in 15 Minuten, danach 429. Ein erfolgreicher Login setzt die
  Zählung zurück; der Login-Link bleibt als Weg herein offen, damit die Sperre
  niemanden dauerhaft aussperren kann.
- Self-Service-Profil für die Rolle `mitglied`

✅ **Kontaktdaten (mehrfach)** *(Schema v24)*
- Beliebig viele E-Mails/Telefonnummern je Mitglied (`mitglied_kontakt`), voll normalisiert
- Genau ein Primärkontakt je Typ; Primär-E-Mail/-Telefon weiter in Formularen pflegbar

✅ **Abteilungen & Funktionen**
- Abteilungen mit Soft-Delete + Wiederherstellung
- Mitglied-Abteilung-Zuordnung (Status, Von/Bis)
- Funktionen je Mitglied (Schiedsrichter, Übungsleiter, Abteilungsleiter …) mit **Pflicht-Zeitraum** *(v25)*

✅ **Mannschaften / Teams** *(Schema v27)*
- Mannschaften je Abteilung (Name, Saison)
- Kader-Zuordnung mit Rolle (spieler, uebungsleiter, betreuer) und Zeitraum.
  „trainer" ist mit *(v71)* entfallen — im Verein ist das dasselbe wie „uebungsleiter"

✅ **Mannschafts-Termine & Spielbetrieb** *(Schema v68–v72)*
- Training/Spiel/Sonstiges je Mannschaft, wöchentliche Serien (rollierend materialisiert)
- Zu-/Absagen der Spieler (`termin_zusage`), stellvertretendes Eintragen durch Trainer/Betreuer
- **Gäste**: Mitglieder außerhalb des Kaders eintragen (sagen zu) oder **einladen**
  *(v102: `antwort` darf NULL sein = eingeladen, Antwort steht aus)*. Der Kreis ist die
  Abteilung; mit `termine.gaeste_vereinsweit` der ganze Verein — samt Filter „alle mit
  Funktion X" für die gelegentliche Runde (Vorstand, Abteilungsleiter). Die Auswahl ist
  ein Schnappschuss, keine dauerhafte Verknüpfung zur Funktion
- Zugriff über die **Kader-ACL** (`mitglied_mannschaft`); `termine.verwalten` nur vereinsweit
- Gastspieler als eigene Personenart *(v72)* — ohne Mitgliedsnummer, Beiträge und Statistik

✅ **Spielplan-Import aus dem DFBnet** *(Schema v80–v86, v94/v95)*
- Vereinsspielplan-Export (UTF-16LE, Tab-getrennt) → Termine, Anker ist die Spielkennung
- Dry-Run, Verlegungs-Diff, Abweichungen zur Entscheidung vorgelegt statt still übernommen
- Spielstätten-Stammdaten inkl. Untergrund; fremde Spiele laufen in die Platzbelegung
- Import-Verlauf mit Zeitpunkt, Zeilenzahl und **Zeitraum der Datei** *(v95)*

✅ **Kalender-Abo (ICS)** *(Schema v89)*
- „Meine Termine" als Feed für Handy-/Desktop-Kalender, Token je Gerät widerrufbar

✅ **Beiträge**
- Beitragsregeln (Verein vs. Abteilung), Einzugsturnus, Gültigkeitszeitraum
- Bedingungen nach Abteilungsstatus, Funktion und **Alter** *(v26)*
- Flexible Ein-/Ausschlüsse je Abteilungsliste *(v40/v41)*, einstellbare Quartals-Rückschau *(v49)*
- Sollstellungs-Lauf (Vorschau + Abrechnung), Umbuchung in Abteilungskasse
- **SEPA-Lastschrift** als eigener Einzug im Format **pain.008** *(Schema v79)*: Läufe mit
  Positionen, Gläubiger-Angaben an den Fibu-Einstellungen

✅ **Gebühren (Aufnahme-/Einmalgebühren)** *(Schema v28)*
- Gebühren-Katalog mit Gültigkeit (Verein vs. Abteilung, Zahler Mitglied/Abteilung)
- Einmalige Forderung je Mitglied (Duplikatschutz), einziehbar wie Beiträge (SEPA / Umbuchung)

✅ **Kassenbuch**
- Mehrere Barkassen (vereinsweit oder je Abteilung), Beträge in **Cent** (kein Float)
- Belegnummer `YYYY-NNN`, Stornierung (Soft-Delete), Bestandsberechnung per SQL
- Verwaltete Kassen-Kategorien statt Freitext *(Schema v38)*
- Kassenzählung mit Stückelung/Zählprotokoll und automatischer Differenzbuchung *(v42/v62)*
- Ressourcen-genaue Kassenrechte über eigene ACL (`kasse_berechtigungen`)

✅ **Fibu-Export (hmd FBASC)** *(Schema v45/v55/v61–v64)*
- Delta-Export der Sollstellungen und Kassenbuchungen im FBASC-Format (statt generischem CSV)
- Exportsperre/Storno-Läufe, konfigurierbare Sach-/Gegenkonten, Kostenträger je Kategorie
- ÜL-Honorare als Kreditor je Übungsleiter

✅ **Funktionsbasierte Berechtigungen** *(Schema v35/v36, siehe [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md))*
- Rechte hängen an Vereins-Funktionen statt an festen Rollen
- Effektiv = Sockel ∪ Funktionsrechte ∪ individuelle Grants − Denies
- Automatischer Rechteverlust beim Ablauf einer Funktions-Zuordnung

✅ **Mitglieder-Import (SPG-Verein und LINEAR)** *(Schema v29)*
- Eigene Import-Seite mit Formatauswahl, Dry-Run, idempotenter Abgleich
- SPG: Zusatzfelder (Geschlecht, SEPA-Mandat, Bemerkungen); LINEAR: Kreuz-Spalten je
  Abteilung, Wiedererkennung über einen `[LINEAR:…]`-Vermerk (s. [LINEAR_IMPORT_PLAN.md](LINEAR_IMPORT_PLAN.md))
- Abteilungen werden **nur gematcht, nie angelegt** — Unbekanntes bricht den Lauf mit Klartext ab

✅ **Eigene angemeldete Geräte** *(Schema v37)*
- Serverseitige Sessions, im Profil einseh- und einzeln abmeldbar

✅ **Zugriffsprotokoll** *(Schema v40)*
- Append-only `access_log` für An-/Abmeldungen und Seitenaufrufe (Protokoll-Seite),
  getrennt nach Kategorie (`auth`, `page`, `schliessanlage`, Übriges)
- Beim Magic-Link steht die **angefragte Adresse** im Eintrag — bei `no_match` die
  einzige Spur, mit welcher Schreibweise es jemand versucht hat

✅ **Datenbereinigung & Konsistenzprüfung** *(Schema v47/v48)*
- **Prune**: endgültiges Löschen soft-gelöschter Zeilen nach konfigurierbarer Frist
  (`PRUNE_REGISTRY`, Kinder vor Eltern) — die einzige Stelle im Code, die hart löscht
- **Log-Retention**: jedes Protokoll hat eine Frist (`LOG_REGISTRY`, Default 365 Tage,
  Seitenaufrufe 90), je Regel auf der Datenbereinigungs-Seite einstellbar.
  **Kein Log wird unbegrenzt aufbewahrt**
- **Konsistenzcheck** (Admin, read-only): findet aktive Datensätze, die auf einen
  soft-gelöschten Parent zeigen — genau das, was FK-Constraints ohne Papierkorb-Kenntnis
  nicht abdecken; dazu gezielte Einmal-Reparaturen

✅ **Übungsleiter-Stundenerfassung** *(Schema v52–v55/v59)*
- Erfassung von ÜL-Stunden je Abrechnung mit Sätzen und Trainerlizenz-Klassifikation
- Lizenz-Gültigkeitsfenster am Mitglied (von/bis), Bestätigungs-Workflow, Stundennachweis-PDF
- Rechte über `ulstunden.*` (erfassen, erfassen_fremd, bestätigen, verwalten)

✅ **Zutrittskontrolle / Schließsystem (TTLock)** *(Schema v56–v59/v64, v90–v93, v96)*
- Cloud-Anbindung (TTLock): Schlösser, Chip-Schlüssel und Tür-Berechtigungen
- Kurzzeitiges App-Öffnen ohne Chip, read-only Credential-Mirror (Fingerprints, Passcodes, Karten)
- Konnektivitäts-Log je Schloss (seit wann offline), append-only Zutritts-Protokoll
- **Chip-Rechtegruppen** *(v93)*: eine Gruppe bündelt Türen und wird Chips dauerhaft zugeordnet
- **Externes Schloss ohne Cloud-Anschluss** *(v90)* mit Log-Import — dasselbe Protokoll
- Chip-Inhaber ohne Mitgliedschaft *(v91)*, Verursacher fest in der Log-Zeile statt
  aus dem heutigen Chip-Inhaber hergeleitet *(v92)*
- Rechte über `schliessanlage.*` (read, oeffnen, protokoll, verwalten)

✅ **Passwort-Tresor** *(Schema v65/v73)*
- Verschlüsselte Zugangsdaten in benannten Tresoren (BYTEA), Zugriffs-Log
- Unverschlüsselte **Tresor-Kontakte** *(v73)*: Handwerker, Notdienste — Telefonnummern
  sind keine Geheimnisse und sollen im Notfall ohne Entschlüsselung greifbar sein
- Ressourcen-genaue Freigaben (`tresor_freigabe`) an User / Abteilung / Funktion mit Aktiv-am-Stichtag-Semantik

✅ **Teamkasse (Clubdeckel)** *(Schema v75/v76)*
- Mannschaftsinterne Strichliste („Deckel"), **bewusst getrennt** von Kassenbuch, Fibu
  und Beiträgen — eigenes schlankes Ledger, Saldo je Mitglied = Summe der Buchungen
- Tap-to-Buchen am „Tresen", Artikel in Gruppen mit Verkäufer (Team oder Mitglied),
  monatlicher Mannschaftsbeitrag mit Befreiungen
- Rechte rein teamintern: Kader-`uebungsleiter`/`betreuer` schalten frei und ernennen
  die Warte (ACL) — **kein globaler Permission-Key, kein Vorstands-Einblick**

✅ **Rechnungen einreichen & freigeben** *(Schema v78)*
- Auslagen mit Belegen einreichen, Freigabe/Ablehnung, Export an die Buchhaltung
- `rechnungen.freigeben` ist **abteilungsscharf** durchgesetzt; Vereinsrechnungen ohne
  Abteilung nur mit `rechnungen.verwalten` (Details in [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md))

✅ **Offene Aufgaben** *(#133)*
- Eine Zahl an Nav-Punkt und Dashboard-Kachel je Bereich, gezählt in der jeweiligen
  Domäne — mit demselben Rechte-/Abteilungs-Scope wie die Liste dahinter

✅ **Tickets** *(Bereiche, Kategorien, bereichsspezifische Rechte)*
- Ticket-Bereiche mit eigener ACL (`ticket_bereich_berechtigungen`: lesen/bearbeiten/schließen)
- **Anhänge** (Fotos/PDFs) in domänenspezifischer Ablage
- Rechte über `tickets.*` (create, read, edit, close, assign, bereiche_verwalten …)

✅ **Benachrichtigungen (mehrkanalig)** *(Schema v67)*
- E-Mail, Telegram, Matrix und **Web-Push** (`push_subscriptions`) als je Profil wählbare Kanäle

✅ **Themes & Branding**
- Drei Themes je Gerät wählbar: **VTB** (Wappenblau auf Gelb), **Hell**, **Dunkel**
- Vereinsidentität kommt aus Env und Branding-Ordner, **nicht aus dem Code**: Farben
  liefert das Backend als `/api/branding.css`, Name/Logo/Texte über Variablen. Eine
  zweite Instanz färbt damit ohne eigenen Build um (s. [ZWEITE_INSTANZ.md](ZWEITE_INSTANZ.md))

✅ **Audit-Trail & Soft-Delete** durchgängig
- `*_history`-Tabellen je Entität, automatisch via DB-Trigger (INSERT/UPDATE)
- Optimistic Locking (`version`), Soft-Delete (`deleted_at`/`deleted_by`)
- **Niemals hart löschen** — weder Zeilen noch Dateien; endgültig entfernt wird nur
  über den Prune-Lauf

✅ **Sicherheits-Härtung**
- JWT im **HttpOnly-Cookie** (SameSite=strict), serverseitige Sessions, Magic-Link-Token
  nur als SHA-256-Hash und Single-Use *(v46/v47)*
- **Content-Security-Policy** ohne `unsafe-eval`/`unsafe-inline` im Skript-Kanal,
  `frame-ancestors 'none'`, `object-src 'none'`
- **Upload-Grenze** gestückelt beim Einlesen durchgesetzt (Starlettes `max_part_size`
  greift für Datei-Parts nicht) — Anhänge und Import-Dateien getrennt konfigurierbar
- **Anhang-Downloads** hängen an der Berechtigung des Elternobjekts, nicht an der Anhang-ID
- **Abteilungs-Scope** auch auf jedem ID-adressierten Personen-Endpunkt, nicht nur in Listen
- **Delegationsregel**: niemand vergibt Rechte weiter, die er selbst nicht hat

## Architektur

```
┌─────────────────────────────┐
│  Frontend (Quasar/Vue, PWA) │  frontend/src/        – SPA, ruft /api
└──────────────┬──────────────┘
               │ HTTP /api
┌──────────────┴──────────────┐
│  API (FastAPI)              │  backend/api/         – Router, Auth (JWT), Permissions
└──────────────┬──────────────┘
               │
┌──────────────┴──────────────┐
│  Service-Layer              │  vtb_verein/app/services/  – Business-Logik, Orchestrierung
└──────────────┬──────────────┘
               │
┌──────────────┴──────────────┐
│  Repository-Layer           │  vtb_verein/app/db/   – CRUD, SQL, Mapping → Models
└──────────────┬──────────────┘
               │
┌──────────────┴──────────────┐
│  PostgreSQL (psycopg3)      │  Schema + Migrationen in app/db/database.py
└─────────────────────────────┘
```

Der Service-/Repository-Layer unter `vtb_verein/app/` wird vom FastAPI-Backend über
`PYTHONPATH=vtb_verein` importiert. Das produktive Docker-Image baut das Quasar-Frontend und
serviert es als statische PWA zusammen mit der API.

## Installation

### Option 1: Docker Compose (empfohlen)

**Voraussetzungen:** Docker + Docker Compose.

1. **Repository klonen**
   ```bash
   git clone https://github.com/versus167/vtb-verein.git
   cd vtb-verein
   ```
2. **Environment-Datei anlegen**
   ```bash
   cp .env.example .env
   # mindestens VTB_PG_USER / VTB_PG_PASSWORD / VTB_PG_DB und VTB_SECRET_KEY setzen
   # (Reihenfolge und Schlüssel-Erzeugung: ERSTEINRICHTUNG.md)
   ```
3. **Stack starten** (PostgreSQL + App-Container)
   ```bash
   docker compose up -d --build
   ```
4. **Browser öffnen:** http://localhost:8000  *(Host-Port via `VTB_PORT`, Default 8000)*

**Nützliche Befehle:**
```bash
docker compose logs -f          # Logs
docker compose restart vtb-verein
docker compose down             # stoppen
docker compose build --no-cache # neu bauen
```

**Daten-Persistenz:** Die PostgreSQL-Daten liegen im Volume `./pg_data`, Uploads in `./uploads`.

### Option 2: Lokale Entwicklung

**Voraussetzungen:** Python 3.12+, Node 22+, eine erreichbare PostgreSQL-Instanz.

1. **PostgreSQL bereitstellen** (Beispiel via Docker):
   ```bash
   docker run -d --name vtb-pg -e POSTGRES_USER=vtb -e POSTGRES_PASSWORD=vtb_dev \
     -e POSTGRES_DB=verein -p 5432:5432 postgres:18
   ```
2. **`.env` anlegen** und `VTB_DATABASE_URL` setzen, z.B.:
   ```bash
   cp .env.example .env
   # VTB_DATABASE_URL=postgresql://vtb:vtb_dev@localhost:5432/verein
   ```
3. **Backend** (Service-Layer liegt unter `vtb_verein/`, daher `PYTHONPATH`):
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r vtb_verein/requirements.txt -r backend/requirements.txt
   PYTHONPATH=vtb_verein python -m uvicorn backend.main:app --reload --port 8000
   ```
   Das Schema wird beim Start **automatisch** auf die aktuelle Version migriert.
4. **Frontend** (in zweitem Terminal):
   ```bash
   cd frontend
   npm ci
   npx quasar dev
   ```
   Der Quasar-Dev-Server öffnet den Browser; API-Aufrufe (`/api`) werden laut
   `frontend/quasar.config.js` auf `http://localhost:8000` weitergeleitet.

## Erste Schritte

Beim ersten Start wird automatisch ein Admin-Account angelegt:

- **Username:** `admin`
- **Passwort:** `admin123`

⚠️ **Passwort sofort nach dem ersten Login ändern.**

Damit läuft die App — eingerichtet ist sie aber noch nicht: Ohne eigenen
Signaturschlüssel, ohne SMTP und ohne Vereins-Stammdaten (die Instanz nennt sich
sonst sichtbar „Beispielverein"). Der vollständige Weg steht in
**[ERSTEINRICHTUNG.md](ERSTEINRICHTUNG.md)**.

## Konfiguration

Alle Einstellungen kommen aus Umgebungsvariablen (bzw. `.env`). Die vollständige,
kommentierte Liste steht in **[`.env.example`](.env.example)** — sie ist die
maßgebliche Referenz und wird bewusst nicht hier zweitverwertet.

Der Weg durch die Ersteinrichtung — in welcher Reihenfolge was gesetzt wird, welche
Schlüssel vorher zu erzeugen sind und was man danach prüft — steht in
**[ERSTEINRICHTUNG.md](ERSTEINRICHTUNG.md)**.

**Datenbank zurücksetzen (Docker):**
```bash
docker compose down
sudo rm -rf pg_data/
docker compose up -d --build
```

## Projektstruktur

```
vtb-verein/
├── docker-compose.yml           # PostgreSQL + App-Container
├── README.md                    # Diese Datei
├── TODO.md                      # Roadmap / offene Aufgaben
├── CLAUDE.md                    # verbindliche Projekt-Konventionen (auch für KI-Assistenten)
├── ERSTEINRICHTUNG.md           # Weg von „geklont" bis „Verein arbeitet damit"
├── BERECHTIGUNGEN.md            # Berechtigungskonzept (funktionsbasiert, Scope, Delegation)
├── *_PLAN.md                    # laufende Vorhaben mit offenen Etappen
├── docs/archiv/                 # abgeschlossene Pläne (Chronik der Entscheidungen)
├── tools/                       # Importer, Ticket-Brücke (vtb_tickets.py), Hilfsskripte
├── frontend/                    # Quasar/Vue Single-Page-App (PWA)
│   ├── src/pages/               # Seiten (Personen, Zugänge, Abteilungen, Mannschaften,
│   │                            #   Termine, Spielplan-Import, Spielstätten, Teamkasse,
│   │                            #   Beiträge, Gebühren, Kassenbuch, Fibu, Rechnungen,
│   │                            #   ÜL-Stunden, Schließanlage, Tresor, Tickets, Import,
│   │                            #   Berichte, Protokoll, Datenbereinigung, Konsistenz …)
│   ├── src/layouts/             # MainLayout (Navigation)
│   ├── src/router/              # Routen (+ meta.permission)
│   ├── src/stores/              # Pinia (auth)
│   ├── src/css/                 # quasar.variables.scss (Vereinsfarben), app.scss (3 Themes)
│   └── quasar.config.js         # Dev-Proxy /api → Backend
├── backend/                     # FastAPI
│   ├── Dockerfile               # baut Frontend + Backend, startet uvicorn
│   ├── main.py                  # App, Router-Registrierung, /api/health, Security-Header
│   ├── api/                     # Router je Domäne
│   ├── core/                    # deps (CurrentUser, DB), config, scope, authz
│   └── requirements.txt
└── vtb_verein/                  # Service-/Repository-/Model-Layer (via PYTHONPATH importiert)
    ├── requirements.txt
    ├── tests/                   # pytest-Suite (s. tests/README.md)
    └── app/
        ├── db/                  # Repositories + database.py (Schema & Migrationen)
        ├── models/              # Dataclasses (mitglied, beitrag, gebuehr, kasse, permission …)
        └── services/            # Business-Logik (person, beitrags, gebuehren, kassenbuch …)
```

Das frühere NiceGUI-UI unter `vtb_verein/app/ui/` ist mit dem Rewrite entfernt worden;
`vtb_verein/` ist heute reine Domänen-/DB-Schicht ohne eigene Oberfläche.

## Datenbank-Schema & Migrationen

Das Schema wird **nicht** über Alembic zur Laufzeit verwaltet, sondern über eine eigene,
versionierte Pipeline in `vtb_verein/app/db/database.py`:

- `SCHEMA_VERSION` definiert die Zielversion (aktuell **96**).
- Beim Backend-Start vergleicht `Database._init_schema()` die DB-Version und führt fehlende
  `_migrate_vX_to_vY()`-Schritte sequenziell aus (jeweils in eigener Transaktion).
- Neue Migration = neue `_migrate_…`-Funktion + Eintrag in `migration_map` + `SCHEMA_VERSION`
  erhöhen. Das Frisch-Schema (`_create_tables` / `_create_trigger_functions` /
  `_create_triggers` / `_create_indexes`) parallel pflegen.

**Fresh == Migriert** ist dabei die tragende Regel: DDL für neue Tabellen steht als
geteilte Modul-Konstante (`_DDL_*`, `_FN_*`, `_*_TRIGGERS`, `_*_INDEXES`) und wird aus
*beiden* Pfaden aufgerufen. Sonst driften eine frisch angelegte und eine gewachsene
Datenbank auseinander — was v87 einmal einebnen musste. Wird eine Spalte ergänzt, gehört
die **Neuanlage der Audit-Funktion** dazu: Die Spaltenliste steckt im Funktionsrumpf.

Durchgängige Prinzipien: **Soft-Delete** (`deleted_at`/`deleted_by`, nie hart löschen),
**Optimistic Locking** (`version`) und **Audit-History** (`*_history`-Tabellen via
INSERT/UPDATE-Trigger). Beträge im Kassenbuch in **Cent** (Integer).

Meilensteine bis v67: v24 mehrere Kontaktdaten · v25 Funktions-Pflichtzeitraum ·
v26 altersabhängige Beitragsregeln · v27 Mannschaften · v28 Aufnahme-/Einmalgebühren ·
v29 SPG-Import-Felder · v35/v36 funktionsbasierte Berechtigungen · v37 serverseitige
Sessions · v38 verwaltete Kassen-Kategorien · v40 Zugriffsprotokoll (`access_log`) ·
v42/v62 Kassenzählung + Differenzbuchung · v45/v61–v64 Fibu-Export (hmd FBASC) ·
v46 Magic-Link-Härtung (Token-Hash) · v47/v48 konfigurierbarer Prune · v50 Zeitstempel
tabellenweit auf `TIMESTAMPTZ` · v52–v55/v59 ÜL-Stundenerfassung · v56–v59/v64
Zutrittskontrolle (TTLock) · v65 Passwort-Tresor · v67 Web-Push.

Seither: v68–v70 Mannschafts-Termine, Zusagen und Serien · v72 Personenart Gastspieler ·
v73 Tresor-Kontakte · v75/v76 Teamkasse (Clubdeckel) · v77 Ticket-„Gesehen"-Log ·
v78 Rechnungen einreichen & freigeben · v79 SEPA-Lastschrift (pain.008) ·
v80 Spielstätten-Stammdaten · v81–v84 DFBnet-Spielplan-Import (Team-Zuordnung,
Schnappschuss, Abweichungen) · v85 Untergrund der Spielstätte · v86 eigenes Recht
`spielstaetten.verwalten` · v87 Schema-Diff Frischaufbau ↔ gewachsen eingeebnet ·
v88 Recht `personen.freischalten` · v89 Kalender-Abos (ICS) · v90 externes Schloss ohne
Cloud · v91 Chip-Inhaber ohne Mitgliedschaft · v92 Verursacher in der Zutritts-Log-Zeile ·
v93 Chip-Rechtegruppen · v94/v95 Stand und Zeitraum des Spielplan-Imports ·
v96 Konten ohne Zugang (E-Mail optional) · v97 Versandstand der Einladung am Konto ·
v98–v101 Teamkasse am Termin (Fremdbuchung, Sortiments-Stände, Wart-Artikel) ·
v102 Gäste einladen statt für sie zuzusagen + Recht `termine.gaeste_vereinsweit` ·
v103 Mitgliedsstatus nur noch aktiv/passiv (ausgetreten ist ein Datum).

## Permissions

Feingranulare Permission-Matrix in der Form `ressource.aktion`, geprüft im API-Layer
(`user.has_permission(...)` + `backend/core/deps.py`). Ressourcen u.a.:
`personen.*` (inkl. `personen.freischalten`, `personen.permissions`), `abteilungen.*`,
`mannschaften.*`, `termine.verwalten`, `spielstaetten.verwalten`, `beitraege.*`,
`gebuehren.*`, `rechnungen.*`, `kassen.verwalten`, `fibu.export`, `funktionen.verwalten`,
`ulstunden.*`, `schliessanlage.*`, `tresor.verwalten`, `berichte.*`, `tickets.*`,
`system.config`/`system.protokoll`.

**Ressourcen-genaue Rechte** (einzelne Kasse, Tresor, Ticket-Bereich, Mannschafts-Termine,
Teamkasse) laufen **nicht** über globale Permissions, sondern über eigene ACL-Tabellen
(`kasse_berechtigungen`, `tresor_freigabe`, `ticket_bereich_berechtigungen`,
`mitglied_mannschaft` als Kader-ACL, `clubdeckel_berechtigung`); die globalen
`*.verwalten`-Rechte gelten nur fürs Anlegen/Verwalten. Die Teamkasse hat bewusst
**gar keinen** globalen Key — sie ist eine teaminterne Angelegenheit.

Berechtigungen sind **funktionsbasiert**, nicht rollenbasiert (Umbau Ticket #22,
Stufen A–E, Details in [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md)):

```
effektiv = Sockel (BASE_PERMISSIONS) ∪ Funktionsrechte ∪ individuelle Grants − Denies
```

- **Sockel:** festes Grundpaket im Code (`BASE_PERMISSIONS`, aktuell `tickets.access`),
  gilt für jeden aktiven, eingeloggten User.
- **Funktionsrechte:** je Katalog-Funktion (`funktion_permission`); ein User erbt die
  Rechte aller am heutigen Tag gültigen Funktions-Zuordnungen seines Mitglieds.
  Endet eine Zuordnung, erlöschen die geerbten Rechte automatisch.
- **Individuelle Overrides** (`user_permissions`, Tri-State `grant`/`deny`): **Deny
  schlägt alles**, Grants sind sticky.
- Die Rolle kennt nur noch **`admin`** (immer uneingeschränkt) und **`mitglied`**;
  `defaults_for_role` wurde entfernt.

Zwei Regeln kommen oben drauf und sind leicht zu übersehen:

- **Abteilungs-Scope wird durchgesetzt**, nicht nur angezeigt. Wer `personen.read` aus
  einer abteilungsgebundenen Funktion bezieht, sieht die übrigen Mitglieder weder in der
  Liste noch über deren ID (`backend/core/scope.py`).
- **Delegationsregel**: Rechte weitergeben — als individueller Grant oder über eine
  Funktions-Zuordnung — darf nur, wer sie selbst hat
  (`backend/core/authz.py::authorize_permission_delegation`). Funktionen ohne hinterlegte
  Rechte bleiben frei zuordenbar, Rechte *entziehen* bleibt frei.

## Tests

```bash
# immer über das venv ausführen (nie System-Python); Warnungen gelten als Fehler
./venv/bin/python -m pytest vtb_verein/tests/ -q
```

1540 Tests in 96 Dateien (davon 414 nur mit Datenbank). Die Suite umfasst reine
Unit-Tests (z. B. `test_iban`,
`test_effective_permissions`, `test_beitrags_service`, `test_gebuehren_service`,
`test_kassen_kategorie`, `test_ul_stunden_service`, `test_vault_crypto`), **Endpunkt-Tests
mit Stubs** (z. B. `test_personen_scope_api`, `test_delegation_api`, `test_login_bremse_api`)
sowie **DB-nahe Integrationstests** (z. B. `test_tresor_integration`,
`test_prune_integration`, `test_schloss_status_log_integration`,
`test_ticket_bereich_berechtigung_integration`). Letztere **skippen automatisch**, solange
`VTB_TEST_DATABASE_URL` nicht auf einen leeren Wegwerf-PostgreSQL zeigt (z. B.
`docker run … postgres:18`); `VereinsDB` legt das Schema beim Connect an. Beide Schema-Pfade
(Frischaufbau *und* Migration) werden geprüft. Details in
[`vtb_verein/tests/README.md`](vtb_verein/tests/README.md).

**Warnungen gelten als Fehler** (`filterwarnings = error`) — eine `DeprecationWarning`
lässt die Suite rot werden, und das ist Absicht.

## Roadmap

Siehe [TODO.md](TODO.md). Offene Schwerpunkte u.a.: Mitglieder-Export (CSV/Excel),
Pagination für große Listen, Belegungsansicht für die Spielstätten und der
Probeimport der FBASC-Dateien in die Ziel-Fibu.

## Lizenz

Copyright (C) 2026 Volker Süß and contributors

Dieses Programm ist freie Software: Du kannst es unter den Bedingungen der
**GNU Affero General Public License**, Version 3 oder (nach deiner Wahl) einer
späteren Version, weitergeben und/oder verändern (`AGPL-3.0-or-later`). Der
vollständige Lizenztext steht in [LICENSE](LICENSE).

Es wird in der Hoffnung bereitgestellt, dass es nützlich ist, jedoch **ohne
jegliche Gewährleistung** (siehe Lizenz).

Hinweis zur AGPL (§13): Wird eine veränderte Fassung als Netzwerkdienst
betrieben, muss den Nutzern der Quellcode dieser Fassung zugänglich gemacht
werden – z. B. über einen „Quellcode"-Link in der App.

## Credits

- [Vue](https://vuejs.org/) + [Quasar Framework](https://quasar.dev/) – Frontend
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) – Backend
- [PostgreSQL](https://www.postgresql.org/) + [psycopg](https://www.psycopg.org/) – Datenbank
- [bcrypt](https://github.com/pyca/bcrypt/) – Password Hashing
- [Docker](https://www.docker.com/) – Containerisierung
