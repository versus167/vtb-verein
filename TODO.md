# TODO - VTB Vereinsverwaltung

## 🔥 High Priority

### Abteilungen
- [ ] Abteilungsleiter-Zuordnung
  - Feld `abteilungsleiter_id` in Abteilung-Tabelle
  - User-Auswahl (Dropdown) in Abteilungsverwaltung
  - Ein Abteilungsleiter pro Abteilung
  - User kann mehrere Abteilungen leiten
  - Anzeige in Abteilungsliste (neue Spalte)
  - Migration für DB-Schema

- [ ] Übungsleiter-Zuordnung
  - Analog zu Abteilungsleiter
  - Feld `uebungsleiter_id` in Abteilung-Tabelle
  - Eigene Berechtigung/Dashboard später

### Permission-Matrix (UI)
- [ ] Permission-Verwaltung in der Benutzerverwaltungs-UI
  - Checkboxen pro Permission pro User
  - Anzeige der aktuellen Permissions
  - Speichern über `PermissionRepository.set_permissions_for_user()`
  - Hinweis wenn User keine Permissions hat

## 📊 Kassenbuch - Phase 3 (nächste Schritte)

### UI
- [ ] `kasse_management.py` erstellen (Kassenverwaltung)
  - Liste aller Kassen mit aktuellem Bestand
  - Kasse anlegen/bearbeiten/löschen
  - Navigation zu Kassenbuchungen der gewählten Kasse

- [ ] `kassenbuch_page.py` erstellen (Buchungen einer Kasse)
  - Tabellarische Ansicht aller Buchungen (sortiert nach Datum/Belegnummer)
  - Stornierte Buchungen standardmäßig ausgeblendet, per Toggle einblendbar (ausgegraut/durchgestrichen)
  - Neue Buchung anlegen (Dialog)
  - Buchung bearbeiten (Dialog, gesperrt wenn exportiert; Belegnummer read-only)
  - Buchung stornieren (mit Bestätigung, gesperrt wenn exportiert)
  - Laufenden Bestand anzeigen (aus DB, nicht berechnet in Python)
  - History-Expander pro Buchung (lazy load, nur sichtbar wenn `version > 1`)
    - Toggle „Änderungshistorie anzeigen" steuert ob Expander-Button gerendert wird
    - History-Zeilen in gedämpfter Farbe (z.B. Gelb/Grau), gleiche Spalten, read-only
    - Versionsnummer je History-Zeile (v1, v2, …) zur Orientierung
  - Exportierte Buchungen mit Schloss-Icon 🔒 kennzeichnen

- [ ] Export-Dialog
  - Zeitraum wählen (Von/Bis)
  - Vorschau: Anzahl betroffener Buchungen + Betragssumme
  - Startet Export → CSV-Download (nur aktive, nicht-exportierte Buchungen)
  - Export-Liste anzeigen (Verlauf vergangener Exporte)

- [ ] PDF-Kassenbericht (nicht sperrend)
  - Flexibler Zeitraum (Von/Bis), unabhängig vom CSV-Export
  - Enthält: Kassename, Zeitraum, Erstellungsdatum, Anfangsbestand
  - Tabellarische Buchungsübersicht mit laufendem Bestand je Zeile
  - Endbestand und Summenspalten (Einnahmen/Ausgaben gesamt)
  - Optional: Summen nach Kategorie
  - Optional: Stornierte Buchungen einblendbar (mit Vermerk)
  - Zeigt aktuellen Stand zum Zeitpunkt der Erstellung (kein Snapshot)
  - Erfordert `kasse.read`-Permission (keine eigene Export-Permission nötig)

- [ ] Navigation erweitern
  - Menüpunkt "Kassenbuch" in `navigation.py`
  - Zugang nur mit `kasse.read`-Permission

## 📋 Phase 3 - Mitgliederverwaltung Erweiterungen

### Anzeige & Navigation
- [ ] Gelöschte Mitglieder anzeigen/wiederherstellen
  - Eigene Ansicht "Gelöschte Mitglieder"
  - Wiederherstellungs-Button
  - Konsistent mit Abteilungs-Wiederherstellung

- [ ] Filter in Mitgliederliste
  - Nach Status (aktiv, passiv, ausgetreten)
  - Nach Abteilung
  - Nach Zahlungsart
  - Nach Austrittsdatum (z.B. "Letzte 6 Monate")

- [ ] Suchfunktion für Mitglieder
  - Volltextsuche: Name, Mitgliedsnummer, E-Mail
  - Ergänzung zu Filtern
  - Live-Search während Eingabe

- [ ] Abteilungsansicht: Übersicht aller Mitglieder einer Abteilung
  - Neue Seite/Dialog pro Abteilung
  - Liste aller zugeordneten Mitglieder
  - Inkl. Status und Von/Bis-Datum

### Import/Export
- [ ] CSV-Export
  - Mitgliederliste exportieren
  - Konfigurierbare Spalten

- [ ] Excel-Export
  - Formatierte Excel-Datei
  - Mehrere Sheets (Mitglieder, Abteilungen, etc.)

- [ ] CSV-Import
  - Mitglieder importieren
  - Validierung und Fehlerbehandlung
  - Duplikatserkennung

### Performance
- [ ] Pagination bei vielen Einträgen
  - Lazy Loading für große Listen
  - Konfigurierbare Seitengröße
  - Performance-Tests mit >1000 Mitgliedern

## 🔮 Phase 4 - Beiträge & Berichte

### Beitragsverwaltung
- [ ] Beitragsregeln definieren
  - Pro Abteilung oder vereinsweit
  - Betrag und Periode (monatlich, jährlich, etc.)
  - Gültigkeit (von/bis)
  - Bedingungen (Alter, Status, etc.)

- [ ] Beitragssollstellung
  - Automatische Berechnung basierend auf Regeln
  - Zeitraum-basiert
  - Berücksichtigung von Ein-/Austritten

- [ ] SEPA-Export
  - XML-Format für Banken
  - Lastschrift-Dateien generieren
  - Validierung IBAN/BIC

### Reporting
- [ ] Berichte & Statistiken
  - Mitgliederentwicklung (Zu-/Abgänge)
  - Abteilungsübersicht
  - Altersstruktur
  - Zahlungsstatus

- [ ] Dashboard mit Kennzahlen
  - Gesamtanzahl Mitglieder (aktiv/passiv)
  - Neueintritte/Austritte im Monat
  - Beitragsstand
  - Grafische Auswertungen

### Kommunikation
- [ ] E-Mail-Benachrichtigungen
  - Willkommens-Mail bei Neuanmeldung
  - Erinnerung bei fehlendem Beitrag
  - Benachrichtigung an Abteilungsleiter
  - E-Mail-Templates konfigurierbar

## 💡 Ideen / Backlog

### Spezielle Features für Rollen
- [ ] Dashboard für Abteilungsleiter
  - Nur ihre Abteilung(en) sichtbar
  - Mitgliederübersicht
  - Statistiken ihrer Abteilung

- [ ] Dashboard für Übungsleiter
  - Trainingsgruppen-Verwaltung
  - Anwesenheitslisten
  - Trainingspläne

### Erweiterte Funktionen
- [ ] Trainingsplan-Management
  - Trainingszeiten definieren
  - Hallenplanung
  - Trainer-Zuordnung

- [ ] Anwesenheitslisten
  - Check-in/Check-out
  - Statistiken pro Mitglied
  - Export für Abrechnungen

- [ ] Dokumentenverwaltung
  - Dateianhang pro Mitglied
  - Verträge, Bescheinigungen, etc.
  - Ablaufdatum-Tracking

### Technische Verbesserungen
- [ ] Multi-Stage Build für Docker
  - Optimale Image-Größe
  - Build-Optimierung

- [ ] CI/CD-Integration
  - GitHub Actions Pipeline
  - Automatische Tests
  - Container Registry Push (Docker Hub / GitHub Packages)
  - Auto-Deploy auf Tag

- [ ] Mobile App / Progressive Web App
  - Offline-Fähigkeit
  - Push-Benachrichtigungen
  - Native App-Feeling

- [ ] Multi-Mandanten-Fähigkeit
  - Mehrere Vereine in einer Instanz
  - Trennung der Daten
  - Zentrales Admin-Dashboard

- [ ] API-Endpunkte
  - REST-API für externe Integrationen
  - Webhook-Support
  - API-Dokumentation

## ✅ Abgeschlossen

### Phase 1
- [x] Benutzerverwaltung
- [x] Abteilungsverwaltung
- [x] Soft-Delete mit Wiederherstellung (Abteilungen)
- [x] Navigation
- [x] Audit-Trail
- [x] Mitgliederverwaltung (Basis)
- [x] Automatische Mitgliedsnummer-Vergabe

### Phase 2
- [x] Mitglied-Abteilung Zuordnung
- [x] Sub-Dialog für Abteilungszuordnung
- [x] Status-Management für Zuordnungen
- [x] History-Tracking für Zuordnungen
- [x] Repository Pattern Migration
- [x] Separation of Concerns: Service vs Repository
- [x] Neue Benutzerrolle `special` (in Phase 2.7 durch Permission-Matrix abgelöst)

### Phase 2.5 - Authentication & Security
- [x] Magic-Link Authentication per E-Mail
  - [x] Token-Generierung und Speicherung (`auth_tokens` Tabelle)
  - [x] E-Mail-Versand mit Login-Link (HTML-Templates)
  - [x] Login via Link (Alternative zu Passwort)
  - [x] Token-Gültigkeit: 7 Tage
  - [x] Dual-Login-UI: Passwort + Magic-Link Tabs
  - [x] Einmalige Token-Verwendung
  - [x] Token-Cleanup (expire/used)
- [x] Remember-Me Sessions
  - [x] Rollenbezogene Session-Timeouts
  - [x] Admin/User: 30 Tage (mit Remember-Me)
  - [x] Readonly: 7 Tage
  - [x] Standard: 24h (ohne Remember-Me)

### Phase 2.6 - Deployment
- [x] Docker-Container für Deployment
  - [x] Dockerfile erstellt (Python + NiceGUI)
  - [x] Volume-Mapping für SQLite-Datenbank
  - [x] Environment-Variablen für Konfiguration (.env)
  - [x] docker-compose.yml für lokales Testing
  - [x] Production-ready Image (Health-Checks, Logging, Ressourcen-Limits)
  - [x] README mit Docker-Setup-Anleitung
  - [x] .dockerignore für optimales Build

### Phase 2.7 - Permission-Matrix (Schema v5)
- [x] `user_permissions` Tabelle mit Soft-Delete und Versionierung
- [x] `user_permissions_history` Tabelle + INSERT/UPDATE-Trigger
- [x] `Permission`-Modell mit Konstanten (`ressource.aktion`-Format)
- [x] `Permission.defaults_for_role()` für Rollen-Defaults (admin/user/readonly)
- [x] `PermissionRepository` (get, grant, revoke, set, revoke_all)
- [x] `User.permissions`-Feld (Set, wird nach Login befüllt)
- [x] `AuthHelper` auf Permission-Prüfung umgestellt (`has_permission()`)
- [x] `require_permission()`-Decorator (ersetzt `require_role()`)
- [x] `require_role()` als Deprecated-Shim erhalten (Backward Compat.)
- [x] Rolle `special` entfernt; bestehende `special`-User erhalten `readonly`-Defaults
- [x] Migration befüllt Default-Permissions für alle bestehenden Users

### Phase 3.0 - Kassenbuch Grundstruktur (Schema v6)
- [x] DB-Schema: `kassen`, `kassenbuchungen`, `kassenbuch_exporte`
- [x] History-Tabellen für alle drei Kassenbuch-Tabellen
- [x] INSERT/UPDATE-Trigger (kein DELETE-Trigger)
- [x] Datenmodelle: `Kasse`, `Kassenbuchung`, `KassenbuchExport` (in `models/kasse.py`)
- [x] `KasseRepository` (CRUD, Soft-Delete, `get_bestand_cent()`, `get_bestand_zum_datum_cent()`)
- [x] `KassenbuchungRepository` (CRUD, Stornierung, `get_naechste_belegnummer()`, `mark_buchungen_exportiert()`)
- [x] `KassenbuchExportRepository` (Create, `get_nicht_exportierte_buchungen()`, `ist_buchung_gesperrt()`)
- [x] Beträge durchgängig in Cent (Integer) – kein Floating Point
- [x] Optimistic Locking (version-Feld) in allen Repositories
- [x] `get_bestand_zum_datum_cent()` für Periodenberechnung im Export

### Phase 3.1 - Kassenbuch Service-Layer & Facade (Schema v7)
- [x] `KassenbuchService` in `kassenbuch_service.py` (Kassen-CRUD, Buchungs-CRUD, CSV-Export, Kassenbericht-Daten)
  - [x] Buchungssperre (Export-Schutz) via `BuchungGesperrtError`
  - [x] Bestandsprüfung (kein negativer Bestand) via `NegativerBestandError`
  - [x] Belegnummer-Generierung automatisch beim Anlegen
  - [x] Atomarer CSV-Export: Buchungen holen → CSV → Export-Datensatz → Buchungen sperren
  - [x] `get_kassenbericht_daten()` für PDF-Bericht (Anfangsbestand, laufender Bestand, Kategoriesummen)
- [x] `KasseRepository`, `KassenbuchungRepository`, `KassenbuchExportRepository` in `datastore.py` integriert
- [x] `db.kassenbuch`-Property auf `KassenbuchService` in `VereinsDB`
- [x] Kasse-Permissions in `permission.py` ergänzt: `kasse.read`, `kasse.write`, `kasse.delete`, `kasse.export`
- [x] `defaults_for_role()` für `user` und `readonly` um Kasse-Permissions erweitert
- [x] Migration `_migrate_6_to_7()`: Kasse-Permissions für alle bestehenden User vergeben

---

**Legende:**
- 🔥 = Hohe Priorität, nächste Schritte
- 📊 = Kassenbuch nächste Schritte (Phase 3)
- 📋 = Mittelfristig, Phase 3
- 🔮 = Längerfristig, Phase 4
- 💡 = Ideen, noch nicht priorisiert
- ✅ = Fertig
