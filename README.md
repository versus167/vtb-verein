# VTB Vereinsverwaltung

Moderne Web-Anwendung zur Verwaltung von Vereinsmitgliedern, Abteilungen, Mannschaften,
Beiträgen, Gebühren und Kassen.

**Tech-Stack:** Quasar/Vue (Frontend) · FastAPI (Backend) · PostgreSQL (psycopg3).
Die frühere NiceGUI/SQLite-Variante wurde abgelöst.

## Features

✅ **Personenverwaltung** (Benutzer + Mitglieder vereint)
- Eine „Personen"-Seite für System-Benutzer und Vereinsmitglieder
- Rollen (admin, user, readonly, mitglied, special) + feingranulare Permission-Matrix je User
- Automatische Mitgliedsnummer-Vergabe (manuell überschreibbar)
- Persönliche Daten, Adresse, Vereinsdaten (Eintritt/Austritt/Status), Zahlungsdaten (IBAN/BIC)
- Passwort-Hashing (bcrypt), Magic-Link-Login per E-Mail
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
- Kader-Zuordnung mit Rolle (spieler, uebungsleiter, trainer, betreuer) und Zeitraum

✅ **Beiträge**
- Beitragsregeln (Verein vs. Abteilung), Einzugsturnus, Gültigkeitszeitraum
- Bedingungen nach Abteilungsstatus, Funktion und **Alter** *(v26)*
- Sollstellungs-Lauf (Vorschau + Abrechnung), SEPA-Export, Umbuchung in Abteilungskasse

✅ **Gebühren (Aufnahme-/Einmalgebühren)** *(Schema v28)*
- Gebühren-Katalog mit Gültigkeit (Verein vs. Abteilung, Zahler Mitglied/Abteilung)
- Einmalige Forderung je Mitglied (Duplikatschutz), einziehbar wie Beiträge (SEPA / Umbuchung)

✅ **Kassenbuch**
- Mehrere Barkassen (vereinsweit oder je Abteilung), Beträge in **Cent** (kein Float)
- Belegnummer `YYYY-NNN`, Stornierung (Soft-Delete), Bestandsberechnung per SQL
- Verwaltete Kassen-Kategorien statt Freitext *(Schema v38)*
- Revisionssicherer CSV-Export mit Exportsperre

✅ **Funktionsbasierte Berechtigungen** *(Schema v35/v36, siehe [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md))*
- Rechte hängen an Vereins-Funktionen statt an festen Rollen
- Effektiv = Sockel ∪ Funktionsrechte ∪ individuelle Grants − Denies
- Automatischer Rechteverlust beim Ablauf einer Funktions-Zuordnung

✅ **Mitglieder-Import (SPG-Verein)** *(Schema v29)*
- Eigene Import-Seite, idempotenter Abgleich, Zusatzfelder (Geschlecht, SEPA-Mandat, Bemerkungen)

✅ **Eigene angemeldete Geräte** *(Schema v37)*
- Serverseitige Sessions, im Profil einseh- und einzeln abmeldbar

✅ **Zugriffsprotokoll** *(Schema v40)*
- Append-only `access_log` für An-/Abmeldungen und Seitenaufrufe (Protokoll-Seite), 90-Tage-Prune

✅ **Tickets** & **Anhänge** (Fotos/PDFs), domänenspezifische Ablage

✅ **Audit-Trail & Soft-Delete** durchgängig
- `*_history`-Tabellen je Entität, automatisch via DB-Trigger (INSERT/UPDATE)
- Optimistic Locking (`version`), Soft-Delete (`deleted_at`/`deleted_by`)

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
   # mindestens VTB_PG_USER / VTB_PG_PASSWORD / VTB_PG_DB setzen,
   # optional SMTP-Daten für Magic-Link-Login
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

**Voraussetzungen:** Python 3.11+, Node 20+, eine erreichbare PostgreSQL-Instanz.

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

## Konfiguration

Konfiguration über Umgebungsvariablen (bzw. `.env`):

```bash
# Datenbank (PostgreSQL)
VTB_DATABASE_URL=postgresql://USER:PASSWORT@HOST:PORT/DBNAME
# Für docker compose werden daraus genutzt:
VTB_PG_USER=vtb
VTB_PG_PASSWORD=...
VTB_PG_DB=verein

# Server
VTB_PORT=8000            # Host-Port (Compose), Default 8000

# Uploads
VTB_UPLOAD_PATH=uploads/ # Docker: /app/uploads
VTB_MAX_UPLOAD_MB=10

# Magic-Link-Login (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=...
SMTP_PASSWORD=...
MAIL_FROM=VTB Verein <vereinsverwaltung@gmail.com>
BASE_URL=http://localhost:8000
```

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
├── frontend/                    # Quasar/Vue Single-Page-App (PWA)
│   ├── src/pages/               # Seiten (Personen, Abteilungen, Mannschaften, Beiträge,
│   │                            #   Gebühren, Kassenbuch, Tickets, Import, Berichte, Protokoll …)
│   ├── src/layouts/             # MainLayout (Navigation)
│   ├── src/router/              # Routen (+ meta.permission)
│   ├── src/stores/              # Pinia (auth)
│   └── quasar.config.js         # Dev-Proxy /api → Backend
├── backend/                     # FastAPI
│   ├── Dockerfile               # baut Frontend + Backend, startet uvicorn
│   ├── main.py                  # App, Router-Registrierung, /api/health
│   ├── api/                     # Router je Domäne
│   ├── core/                    # deps (CurrentUser, DB), config
│   └── requirements.txt
└── vtb_verein/                  # Service-/Repository-/Model-Layer (via PYTHONPATH importiert)
    ├── requirements.txt
    └── app/
        ├── db/                  # Repositories + database.py (Schema & Migrationen)
        ├── models/              # Dataclasses (mitglied, beitrag, gebuehr, kasse, permission …)
        └── services/            # Business-Logik (person, beitrags, gebuehren, kassenbuch …)
```

## Datenbank-Schema & Migrationen

Das Schema wird **nicht** über Alembic zur Laufzeit verwaltet, sondern über eine eigene,
versionierte Pipeline in `vtb_verein/app/db/database.py`:

- `SCHEMA_VERSION` definiert die Zielversion (aktuell **40**).
- Beim Backend-Start vergleicht `Database._init_schema()` die DB-Version und führt fehlende
  `_migrate_vX_to_vY()`-Schritte sequenziell aus (jeweils in eigener Transaktion).
- Neue Migration = neue `_migrate_…`-Funktion + Eintrag in `migration_map` + `SCHEMA_VERSION`
  erhöhen. Das Frisch-Schema (`_create_tables` / `_create_trigger_functions` /
  `_create_triggers` / `_create_indexes`) parallel pflegen.

Durchgängige Prinzipien: **Soft-Delete** (`deleted_at`/`deleted_by`, nie hart löschen),
**Optimistic Locking** (`version`) und **Audit-History** (`*_history`-Tabellen via
INSERT/UPDATE-Trigger). Beträge im Kassenbuch in **Cent** (Integer).

Jüngste Meilensteine: v24 mehrere Kontaktdaten · v25 Funktions-Pflichtzeitraum ·
v26 altersabhängige Beitragsregeln · v27 Mannschaften · v28 Aufnahme-/Einmalgebühren ·
v29 SPG-Import-Felder · v35/v36 funktionsbasierte Berechtigungen · v37 serverseitige
Sessions · v38 verwaltete Kassen-Kategorien · v40 Zugriffsprotokoll (`access_log`).

## Permissions

Feingranulare Permission-Matrix in der Form `ressource.aktion`, geprüft im API-Layer
(`user.has_permission(...)` + `backend/core/deps.py`). Ressourcen u.a.:
`personen.*`, `abteilungen.*`, `mannschaften.*`, `beitraege.*`, `gebuehren.*`,
`kassen.*`, `berichte.*`, `tickets.*`, `protokoll.*`, `system.config`.

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

## Tests

```bash
# immer über das venv ausführen
./venv/bin/python -m pytest vtb_verein/tests/ -q
```

Aktuell sind einige Unit-Tests vorhanden (`test_anhang_service`, `test_beitrags_service`,
`test_effective_permissions`, `test_iban`, `test_kassen_kategorie`,
`test_notification_services`). Eine PostgreSQL-Test-Fixture (conftest) existiert noch nicht;
DB-nahe Tests werden derzeit gegen einen Wegwerf-PostgreSQL-Container gefahren.

## Roadmap

Siehe [TODO.md](TODO.md). Offene Schwerpunkte u.a.: Mitglieder-Export (CSV/Excel),
Pagination für große Listen und Fibu-Export der Sollstellungen.

## Lizenz

Privat, nicht für die öffentliche Nutzung bestimmt.

## Credits

- [Vue](https://vuejs.org/) + [Quasar Framework](https://quasar.dev/) – Frontend
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) – Backend
- [PostgreSQL](https://www.postgresql.org/) + [psycopg](https://www.psycopg.org/) – Datenbank
- [bcrypt](https://github.com/pyca/bcrypt/) – Password Hashing
- [Docker](https://www.docker.com/) – Containerisierung
