# VTB Vereinsverwaltung

Moderne Web-Anwendung zur Verwaltung von Vereinsmitgliedern, Abteilungen und Beiträgen.

## Features

✅ **Benutzerverwaltung**
- Rollenbasierte Zugriffskontrolle (Admin, Bearbeiter, Nur Lesen)
- Feingranulare Permission-Matrix pro User (unabhängig von der Rolle)
- Passwort-Management mit bcrypt
- Session-Management

✅ **Abteilungsverwaltung**
- CRUD-Operationen für Abteilungen
- Soft-Delete mit Wiederherstellung
- Validierung von Abhängigkeiten
- Anzeige und Wiederherstellung gelöschter Abteilungen

✅ **Mitgliederverwaltung**
- Vollständige Mitgliederverwaltung mit allen relevanten Daten
- Automatische Mitgliedsnummer-Vergabe (manuell überschreibbar)
- Persönliche Daten, Kontakt, Adresse
- Vereinsdaten (Eintritt, Austritt, Status)
- Zahlungsdaten (IBAN, BIC, Zahlungsart)
- Soft-Delete mit History

✅ **Mitglied-Abteilung-Zuordnung**
- Mehrfachzuordnung von Mitgliedern zu Abteilungen
- Status-Management (aktiv, passiv, trainer, vorstand, etc.)
- Von/Bis-Datumsfelder für zeitliche Zuordnungen
- Sub-Dialog zur Verwaltung der Zuordnungen
- Vollständiger Audit-Trail

✅ **Audit-Trail**
- Vollständige Versionierung aller Änderungen
- History-Tabellen für jeden Datensatz
- Nachvollziehbare Datenänderungen (wer, wann, was)

✅ **Moderne UI**
- Responsive Design mit Quasar Framework
- Intuitive Navigation
- Echtzeit-Validierung
- Übersichtliche Dialoge mit Sections

## Installation

### Option 1: Docker (Empfohlen)

**Voraussetzungen:**
- Docker und Docker Compose installiert

**Schnellstart:**

1. **Repository klonen**
   ```bash
   git clone https://github.com/versus167/vtb-verein.git
   cd vtb-verein
   ```

2. **Environment-Datei erstellen**
   ```bash
   cp .env.example .env
   # .env bearbeiten und SMTP-Einstellungen konfigurieren
   ```

3. **Container starten**
   ```bash
   docker compose up -d
   ```

4. **Browser öffnen**
   ```
   http://localhost:8080
   ```

**Docker-Befehle:**

```bash
# Container stoppen
docker compose down

# Logs anzeigen
docker compose logs -f

# Container neu bauen
docker compose build --no-cache

# Container neu starten
docker compose restart
```

**Daten-Persistence:**

Die SQLite-Datenbank wird im `./data` Verzeichnis gespeichert und bleibt bei Container-Updates erhalten.

### Option 2: Manuelle Installation

**Voraussetzungen:**

- Python 3.11 oder höher
- pip (Python Package Manager)

**Setup:**

1. **Repository klonen**
   ```bash
   git clone https://github.com/versus167/vtb-verein.git
   cd vtb-verein
   ```

2. **Virtuelle Umgebung erstellen (empfohlen)**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # oder
   venv\Scripts\activate  # Windows
   ```

3. **Abhängigkeiten installieren**
   ```bash
   cd vtb_verein
   pip install -r requirements.txt
   ```

4. **Umgebungsvariablen konfigurieren (optional)**
   ```bash
   cp .env.example .env
   # Dann .env bearbeiten
   ```

5. **Anwendung starten**
   ```bash
   python main.py
   ```

6. **Browser öffnen**
   ```
   http://localhost:8080
   ```

## Erste Schritte

### Standard-Admin-Account

Beim ersten Start wird automatisch ein Admin-Account erstellt:

- **Username:** `admin`
- **Passwort:** `admin123`

⚠️ **WICHTIG:** Bitte Passwort sofort nach dem ersten Login ändern!

### Neue Benutzer anlegen

1. Als Admin einloggen
2. Navigation: "Benutzer" klicken
3. "Neuen Benutzer anlegen" Button
4. Formular ausfüllen und speichern

### Abteilungen verwalten

1. Als Admin oder Bearbeiter einloggen
2. Navigation: "Abteilungen" klicken
3. Abteilungen anlegen, bearbeiten oder löschen
4. Gelöschte Abteilungen können wiederhergestellt werden

### Mitglieder verwalten

1. Als Admin oder Bearbeiter einloggen
2. Navigation: "Mitglieder" klicken
3. "Neues Mitglied anlegen" Button
4. Formular ausfüllen:
   - Mitgliedsnummer wird automatisch vergeben (kann geändert werden)
   - Pflichtfelder: Vorname, Nachname, Zahlungsart
5. Mitglieder bearbeiten oder löschen
6. "Abteilungen verwalten" Button: Zuordnung zu Abteilungen

## Konfiguration

### Umgebungsvariablen

Die Anwendung kann über Umgebungsvariablen konfiguriert werden:

```bash
# Datenbank
VTB_DB_PATH=verein.db  # Docker: /data/verein.db

# Server
VTB_HOST=0.0.0.0
VTB_PORT=8080

# Security
VTB_STORAGE_SECRET=your-secret-key-here

# SMTP (für Magic-Link-Login)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
MAIL_FROM=VTB Verein <vereinsverwaltung@gmail.com>
BASE_URL=http://localhost:8080
```

Alternativ: `.env` Datei im Projektverzeichnis anlegen.

### Datenbank

Die Anwendung verwendet SQLite als Datenbank. Die Datenbankdatei wird automatisch beim ersten Start erstellt.

**Datenbank zurücksetzen:**

```bash
# Manuell
rm verein.db
cd vtb_verein
python main.py

# Docker
docker compose down
rm -rf data/
mkdir data
docker compose up -d
```

## Docker Production Deployment

### Image bauen

```bash
# Image bauen
docker build -t vtb-verein:latest .

# Image mit Tag bauen
docker build -t vtb-verein:v1.0.0 .
```

### Container manuell starten

```bash
docker run -d \
  --name vtb-verein \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e VTB_DB_PATH=/data/verein.db \
  -e VTB_STORAGE_SECRET=your-secret-key \
  --env-file .env \
  --restart unless-stopped \
  vtb-verein:latest
```

### Health Check

Das Docker-Image enthält einen integrierten Health Check:

```bash
# Container-Status prüfen
docker ps

# Health-Status anzeigen
docker inspect --format='{{.State.Health.Status}}' vtb-verein
```

### Ressourcen-Limits

In `docker-compose.yml` sind bereits Ressourcen-Limits definiert:

- **CPU:** Max 1.0 Core, Reserve 0.25 Core
- **Memory:** Max 512MB, Reserve 128MB

Passe diese nach Bedarf an.

## Entwicklung

### Projektstruktur

```
vtb-verein/
├── requirements.txt             # Python-Abhängigkeiten
├── README.md                    # Diese Datei
├── TODO.md                      # Roadmap und offene Aufgaben
├── Dockerfile                   # Docker-Image-Definition
├── docker-compose.yml           # Docker Compose Konfiguration
├── .dockerignore                # Dateien für Docker-Build ausschließen
└── vtb_verein/
    ├── main.py                  # Haupteinstiegspunkt
    ├── __init__.py
    └── app/
        ├── auth/                # Authentifizierung
        │   ├── auth_helper.py   # Session, require_permission-Decorator
        │   └── __init__.py
        ├── db/                  # Datenbank-Layer (Repository Pattern)
        │   ├── __init__.py
        │   ├── base_repository.py         # Basis-Klasse für Repositories
        │   ├── database.py                # Connection & Schema-Management
        │   ├── datastore.py               # VereinsDB Facade (Backward Compat.)
        │   ├── mitglied_repository.py     # Mitglied-Datenzugriff
        │   ├── abteilung_repository.py    # Abteilung-Datenzugriff
        │   ├── user_repository.py         # User-Datenzugriff
        │   └── permission_repository.py   # Permission-Datenzugriff
        ├── models/              # Datenmodelle
        │   ├── abteilung.py
        │   ├── mitglied.py
        │   ├── user.py
        │   ├── permission.py    # Permission-Konstanten & UserPermission-Modell
        │   └── __init__.py
        ├── services/            # Business-Logik
        │   ├── abteilungen_service.py
        │   ├── mitglied_abteilung_service.py
        │   ├── user_service.py
        │   └── __init__.py
        ├── ui/                  # User Interface
        │   ├── abteilung_management.py
        │   ├── mitglied_management.py
        │   ├── mitglied_abteilung_dialog.py
        │   ├── login_page.py
        │   ├── navigation.py
        │   ├── user_management.py
        │   └── __init__.py
        └── web/                 # Web-spezifische Komponenten
            └── __init__.py
```

### Testing

```bash
# Anwendung im Entwicklungsmodus starten
cd vtb_verein
python main.py
```

### Neue Features hinzufügen

1. Branch erstellen: `git checkout -b feature/mein-feature`
2. Änderungen durchführen
3. Commit: `git commit -am "Add: Mein Feature"`
4. Push: `git push origin feature/mein-feature`
5. Pull Request erstellen

## Technische Details

### Architektur

**Repository Pattern (seit v2.0):**

Die Anwendung nutzt das Repository Pattern für saubere Trennung von Datenzugriff und Business-Logik:

```
┌─────────────────┐
│   UI Layer      │  NiceGUI-Komponenten
└────────┬────────┘
         │
┌────────┴────────┐
│ Service Layer   │  Business-Logik, Validierung, Orchestrierung
└────────┬────────┘
         │
┌────────┴────────┐
│ Repository Layer│  Reine CRUD-Operationen, SQL-Queries
└────────┬────────┘
         │
┌────────┴────────┐
│   Database      │  SQLite mit Row Factory
└─────────────────┘
```

**Layer-Verantwortlichkeiten:**

1. **UI Layer** (`app/ui/`):
   - NiceGUI-Komponenten
   - User Interaction
   - Keine Business-Logik

2. **Service Layer** (`app/services/`):
   - Business-Logik (z.B. "Letzter Admin"-Schutz)
   - Validierung (z.B. Passwort-Hashing)
   - Orchestrierung mehrerer Repositories
   - **Keine direkten SQL-Queries**

3. **Repository Layer** (`app/db/`):
   - Pure CRUD-Operationen
   - SQL-Queries
   - Mapping von DB-Rows zu Models
   - **Keine Business-Logik**

4. **Models** (`app/models/`):
   - Datenklassen (dataclasses)
   - Permission-Konstanten (`Permission`-Klasse)
   - Type Safety

**Vorteile:**
- ✅ Klare Trennung der Verantwortlichkeiten
- ✅ Testbarkeit (Repositories können gemockt werden)
- ✅ Wartbarkeit (SQL-Änderungen nur in Repositories)
- ✅ Wiederverwendbarkeit (Repositories in mehreren Services nutzbar)

### Permission-System

Seit Schema v5 verwendet die Anwendung eine feingranulare **Permission-Matrix** statt rein rollenbasierter Zugriffssteuerung.

**Permissions** haben die Form `ressource.aktion`, z.B.:
- `mitglieder.read`, `mitglieder.write`, `mitglieder.delete`
- `abteilungen.read`, `abteilungen.write`, `abteilungen.delete`
- `beitraege.read`, `beitraege.write`
- `berichte.read`, `berichte.export`
- `users.read`, `users.manage`
- `system.config`

**Rollen** vergeben beim Anlegen eines Users automatisch Default-Permissions:
- `admin`: alle Permissions
- `user`: alle außer `users.manage` und `system.config`
- `readonly`: nur `*.read`

Individuelle Permissions können anschließend pro User angepasst werden (über `PermissionRepository`).

**Zugriffsprüfung in der UI:**
```python
from app.auth.auth_helper import AuthHelper, require_permission
from app.models.permission import Permission

# Imperativ
if AuthHelper.has_permission(Permission.MITGLIEDER_WRITE):
    ...

# Als Decorator
@require_permission(Permission.MITGLIEDER_WRITE)
def edit_member():
    ...
```

### Datenbank-Schema

**Mitgliedsnummern:**
- Typ: INTEGER (automatische Vergabe)
- UNIQUE Constraint
- Manuelle Überschreibung möglich
- Validierung auf Duplikate

**Mitglied-Abteilung-Zuordnung:**
- Many-to-Many Beziehung via mitglied_abteilung Tabelle
- Status-Feld für verschiedene Rollen
- Von/Bis-Datumsfelder für zeitliche Zuordnungen
- Soft-Delete Support

**Soft-Delete:**
- Alle Entitäten unterstützen Soft-Delete
- `deleted_at` und `deleted_by` Felder
- Wiederherstellung möglich
- History bleibt erhalten

**Optimistic Locking:**
- Version-Feld für Concurrency Control
- Verhindert Überschreiben von Änderungen
- Konflikterkennung bei Updates

**History/Audit-Trail:**
- Automatische Versionierung via Database-Triggers
- Jede Änderung wird in `*_history` Tabellen protokolliert
- Nachvollziehbarkeit aller Änderungen (wer, wann, was)

**Schema-Versionen:**

| Version | Inhalt |
|---------|--------|
| 1 | Initiales Schema (mitglied, abteilung, beitrag, users) |
| 2 | History-Trigger für mitglied; DELETE-Trigger entfernt |
| 3 | Rolle `special` in users-Tabelle |
| 4 | `auth_tokens` für Magic-Link-Authentication |
| 5 | `user_permissions` für Permission-Matrix |

### Repository Pattern Details

**BaseRepository:**
- Gemeinsame Basis für alle Repositories
- Stellt `cursor()` Context Manager bereit
- Automatisches Commit/Rollback

**Spezialisierte Repositories:**
- `MitgliedRepository`: CRUD für Mitglieder, Mitgliedsnummer-Management
- `AbteilungRepository`: CRUD für Abteilungen, Dependency-Checks
- `UserRepository`: CRUD für User, Authentication-Queries
- `PermissionRepository`: CRUD für User-Permissions (grant, revoke, set)

**VereinsDB Facade:**
- Kombiniert alle Repositories
- Stellt einheitliche Schnittstelle bereit
- Backward Compatibility für Legacy-Code

## Roadmap

Siehe [TODO.md](TODO.md) für die detaillierte Roadmap und offene Aufgaben.

## Support

Bei Fragen oder Problemen:

1. Issue erstellen: https://github.com/versus167/vtb-verein/issues
2. Dokumentation prüfen: Diese README
3. Code anschauen: Gut kommentiert

## Lizenz

Dieses Projekt ist privat und nicht für die öffentliche Nutzung bestimmt.

## Credits

Entwickelt mit:
- [NiceGUI](https://nicegui.io/) - Python UI Framework
- [SQLite](https://www.sqlite.org/) - Datenbank
- [bcrypt](https://github.com/pyca/bcrypt/) - Password Hashing
- [Quasar Framework](https://quasar.dev/) - UI Components
- [Docker](https://www.docker.com/) - Containerization
