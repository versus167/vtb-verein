# VTB Vereinsverwaltung

Moderne Web-Anwendung zur Verwaltung von Vereinsmitgliedern, Abteilungen und Beiträgen.

## Features

✅ **Benutzerverwaltung**
- Rollenbasierte Zugriffskontrolle (Admin, Bearbeiter, Nur Lesen, Spezielle Funktionen)
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

### Voraussetzungen

- Python 3.12 oder höher
- pip (Python Package Manager)

### Setup

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
VTB_DB_PATH=verein.db

# Server
VTB_HOST=0.0.0.0
VTB_PORT=8080

# Security
VTB_STORAGE_SECRET=your-secret-key-here
```

Alternativ: `.env` Datei im Projektverzeichnis anlegen.

### Datenbank

Die Anwendung verwendet SQLite als Datenbank. Die Datenbankdatei wird automatisch beim ersten Start erstellt.

**Datenbank zurücksetzen:**
```bash
rm verein.db
cd vtb_verein
python main.py
```

## Entwicklung

### Projektstruktur

```
vtb-verein/
├── requirements.txt             # Python-Abhängigkeiten
├── README.md                    # Diese Datei
├── TODO.md                      # Roadmap und offene Aufgaben
└── vtb_verein/
    ├── main.py                  # Haupteinstiegspunkt
    ├── __init__.py
    └── app/
        ├── auth/                # Authentifizierung
        │   ├── auth_helper.py
        │   └── __init__.py
        ├── db/                  # Datenbank-Layer (Repository Pattern)
        │   ├── __init__.py
        │   ├── base_repository.py       # Basis-Klasse für Repositories
        │   ├── database.py              # Connection & Schema-Management
        │   ├── datastore.py             # VereinsDB Facade (Backward Compat.)
        │   ├── mitglied_repository.py   # Mitglied-Datenzugriff
        │   ├── abteilung_repository.py  # Abteilung-Datenzugriff
        │   └── user_repository.py       # User-Datenzugriff
        ├── models/              # Datenmodelle
        │   ├── abteilung.py
        │   ├── mitglied.py
        │   ├── user.py
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
   - Type Safety

**Vorteile:**
- ✅ Klare Trennung der Verantwortlichkeiten
- ✅ Testbarkeit (Repositories können gemockt werden)
- ✅ Wartbarkeit (SQL-Änderungen nur in Repositories)
- ✅ Wiederverwendbarkeit (Repositories in mehreren Services nutzbar)

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
- Jede Änderung wird in *_history Tabellen protokolliert
- Nachvollziehbarkeit aller Änderungen (wer, wann, was)

### Repository Pattern Details

**BaseRepository:**
- Gemeinsame Basis für alle Repositories
- Stellt `cursor()` Context Manager bereit
- Automatisches Commit/Rollback

**Spezialisierte Repositories:**
- `MitgliedRepository`: CRUD für Mitglieder, Mitgliedsnummer-Management
- `AbteilungRepository`: CRUD für Abteilungen, Dependency-Checks
- `UserRepository`: CRUD für User, Authentication-Queries

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
