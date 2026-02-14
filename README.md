# VTB Vereinsverwaltung

Moderne Web-Anwendung zur Verwaltung von Vereinsmitgliedern, Abteilungen und Beiträgen.

## Features

✅ **Benutzerverwaltung**
- Rollenbasierte Zugriffskontrolle (Admin, Bearbeiter, Nur Lesen)
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
   pip install -r requirements.txt
   ```

4. **Umgebungsvariablen konfigurieren (optional)**
   ```bash
   cp .env.example .env
   # Dann .env bearbeiten
   ```

5. **Anwendung starten**
   ```bash
   cd vtb_verein
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
└── vtb_verein/
    ├── main.py                  # Haupteinstiegspunkt
    ├── __init__.py
    └── app/
        ├── auth/               # Authentifizierung
        │   ├── auth_helper.py
        │   └── __init__.py
        ├── db/                 # Datenbank
        │   ├── datastore.py    # Schema & Migrationen
        │   └── __init__.py
        ├── models/             # Datenmodelle
        │   ├── abteilung.py
        │   ├── mitglied.py
        │   ├── user.py
        │   └── __init__.py
        ├── services/           # Business-Logik
        │   ├── abteilungen_service.py
        │   ├── user_service.py
        │   └── __init__.py
        └── ui/                 # User Interface
            ├── abteilung_management.py
            ├── mitglied_management.py
            ├── login_page.py
            ├── navigation.py
            ├── user_management.py
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

### Datenbank-Schema

**Mitgliedsnummern:**
- Typ: INTEGER (automatische Vergabe)
- UNIQUE Constraint
- Manuelle Überschreibung möglich
- Validierung auf Duplikate

**Soft-Delete:**
- Alle Entitäten unterstützen Soft-Delete
- `deleted_at` und `deleted_by` Felder
- Wiederherstellung möglich
- History bleibt erhalten

**Optimistic Locking:**
- Version-Feld für Concurrency Control
- Verhindert Überschreiben von Änderungen
- Konflikterkennung bei Updates

### Architektur

**Layered Architecture:**
1. **UI Layer** (`app/ui/`): NiceGUI-Komponenten
2. **Service Layer** (`app/services/`): Business-Logik
3. **Data Layer** (`app/db/`): Pure CRUD-Operationen
4. **Models** (`app/models/`): Datenklassen

**Vorteile:**
- Klare Trennung der Verantwortlichkeiten
- Testbarkeit
- Wartbarkeit
- Erweiterbarkeit

## Roadmap

### Phase 1 (✅ Abgeschlossen)
- [x] Benutzerverwaltung
- [x] Abteilungsverwaltung
- [x] Soft-Delete mit Wiederherstellung (Abteilungen)
- [x] Navigation
- [x] Audit-Trail
- [x] Mitgliederverwaltung (Basis)
- [x] Automatische Mitgliedsnummer-Vergabe

### Phase 2 (In Arbeit)
- [ ] Suchfunktion für Mitglieder
- [ ] Filter in Mitgliederliste
- [ ] Mitglied-Abteilung Zuordnung
- [ ] Sub-Dialog für Abteilungszuordnung

### Phase 3 (Geplant)
- [ ] Gelöschte Mitglieder anzeigen/wiederherstellen
- [ ] Import/Export (CSV, Excel)
- [ ] Pagination bei vielen Einträgen
- [ ] Beitragsregeln
- [ ] Beitragssollstellung

### Phase 4 (Zukunft)
- [ ] Berichte & Statistiken
- [ ] SEPA-Export
- [ ] Dashboard mit Kennzahlen
- [ ] E-Mail-Benachrichtigungen

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
