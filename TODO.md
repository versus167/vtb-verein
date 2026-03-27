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

## 📊 Kassenbuch - Phase 3 (nächste Schritte)

### Phase 3.2 - Kassenspezifische Berechtigungen (Schema v8)

> **Architektur-Entscheidung:** Kassen anlegen/konfigurieren/löschen ist eine reine
> Admin-Funktion (erfordert `users.manage`). Zugriff auf einzelne Kassen wird
> **kassenspezifisch** über eine eigene Tabelle gesteuert – nicht über globale
> `kasse.*`-Permissions. Die globalen `kasse.*`-Permissions (Schema v7) werden
> durch dieses System ersetzt (Variante A: kein doppeltes Berechtigungskonzept).

- [ ] **Schema-Migration v7 → v8**
  - Neue Tabelle `kasse_berechtigungen`:
    - `id`, `kasse_id`, `user_id`
    - `darf_lesen` (INTEGER 0/1)
    - `darf_schreiben` (INTEGER 0/1) – inkl. Stornieren
    - `darf_exportieren` (INTEGER 0/1)
    - Soft-Delete (`deleted_at`, `deleted_by`), Versionierung, Audit-Trigger
  - Neue Tabelle `kasse_berechtigungen_history` + INSERT/UPDATE-Trigger
  - Globale `kasse.*`-Permissions aus `user_permissions` entfernen
    (für alle bestehenden User per Migration bereinigen)
  - `kasse.read`, `kasse.write`, `kasse.delete`, `kasse.export` aus `permission.py` entfernen
  - `defaults_for_role()` entsprechend anpassen
  - Beim Anlegen einer neuen Kasse: Admin erhält automatisch alle drei Rechte

- [ ] **Repository: `KasseBerechtigungRepository`**
  - `get_berechtigungen_fuer_kasse(kasse_id)` – alle Berechtigten einer Kasse
  - `get_kassen_fuer_user(user_id)` – alle Kassen, auf die ein User Zugriff hat
  - `set_berechtigung(kasse_id, user_id, darf_lesen, darf_schreiben, darf_exportieren, actor)`
  - `revoke_berechtigung(kasse_id, user_id, actor)` – Soft-Delete
  - `hat_lesezugriff(kasse_id, user_id)` / `hat_schreibzugriff(...)` / `hat_exportrecht(...)` – für Service-Checks

- [ ] **Service-Anpassung: `KassenbuchService`**
  - Alle Methoden prüfen kassenspezifische Berechtigung des aktuellen Users
  - `get_kassen_fuer_user(user_id)` als Einstiegspunkt (statt alle Kassen)
  - Admin (via `users.manage`) sieht und verwaltet alle Kassen ohne Eintrag in `kasse_berechtigungen`

- [ ] **UI: Berechtigungsverwaltung pro Kasse**
  - In `kasse_management.py`: Button „Berechtigungen“ pro Kasse (nur für Admins sichtbar)
  - Dialog mit User-Liste + Checkboxen (Lesen / Schreiben / Exportieren)
  - Warnung wenn Kasse keine Berechtigten hat
  - Beim Anlegen einer neuen Kasse: direkt Berechtigungen-Dialog öffnen

- [ ] **Permission-UI anpassen**
  - Kassenbuch-Gruppe aus `permission_management.py` entfernen
  - (Kassen-Rechte werden künftig nur noch pro Kasse vergeben)

### UI
- [ ] `kasse_management.py` erstellen (Kassenverwaltung, nur Admin)
  - Liste aller Kassen mit aktuellem Bestand
  - Kasse anlegen/bearbeiten/löschen (nur `users.manage`)
  - Beim Anlegen: direkt Berechtigungen-Dialog
  - Navigation zu Kassenbuchungen der gewählten Kasse

- [ ] `kassenbuch_page.py` erstellen (Buchungen einer Kasse)
  - Nur Kassen anzeigen, auf die der User Lesezugriff hat
  - Tabellarische Ansicht aller Buchungen (sortiert nach Datum/Belegnummer)
  - Stornierte Buchungen standardmäßig ausgeblendet, per Toggle einblendbar (ausgegraut/durchgestrichen)
  - Neue Buchung anlegen (Dialog, nur mit Schreibzugriff)
  - Buchung bearbeiten (Dialog, gesperrt wenn exportiert; Belegnummer read-only)
  - Buchung stornieren (mit Bestätigung, gesperrt wenn exportiert, nur mit Schreibzugriff)
  - Laufenden Bestand anzeigen (aus DB, nicht berechnet in Python)
  - History-Expander pro Buchung (lazy load, nur sichtbar wenn `version > 1`)
    - Toggle „Änderungshistorie anzeigen" steuert ob Expander-Button gerendert wird
    - History-Zeilen in gedämpfter Farbe (z.B. Gelb/Grau), gleiche Spalten, read-only
    - Versionsnummer je History-Zeile (v1, v2, …) zur Orientierung
  - Exportierte Buchungen mit Schloss-Icon 🔒 kennzeichnen

- [ ] Export-Dialog (nur mit Exportrecht)
  - Zeitraum wählen (Von/Bis)
  - Vorschau: Anzahl betroffener Buchungen + Betragssumme
  - Startet Export → CSV-Download (nur aktive, nicht-exportierte Buchungen)
  - Export-Liste anzeigen (Verlauf vergangener Exporte)

- [ ] PDF-Kassenbericht (nicht sperrend, nur mit Lesezugriff)
  - Flexibler Zeitraum (Von/Bis), unabhängig vom CSV-Export
  - Enthält: Kassename, Zeitraum, Erstellungsdatum, Anfangsbestand
  - Tabellarische Buchungsübersicht mit laufendem Bestand je Zeile
  - Endbestand und Summenspalten (Einnahmen/Ausgaben gesamt)
  - Optional: Summen nach Kategorie
  - Optional: Stornierte Buchungen einblendbar (mit Vermerk)

- [ ] Navigation erweitern
  - Menüpunkt "Kassenbuch" in `navigation.py`
  - Sichtbar wenn User mind. eine Kasse mit Lesezugriff hat (oder Admin)

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
- [x] Permission-Verwaltung in der Benutzerverwaltungs-UI (`permission_management.py`)
  - [x] Checkbox-Matrix gruppiert nach Ressource
  - [x] Visueller Hinweis bei Abweichung vom Rollen-Standard (orange)
  - [x] "Auf Rollen-Standard zurücksetzen"-Button
  - [x] Schutz: letzter Admin kann USERS_MANAGE nicht verlieren
  - [x] Kassenbuch-Gruppe vorläufig integriert (wird in Phase 3.2 wieder entfernt)

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
- [x] Kasse-Permissions in `permission.py` vorläufig ergänzt: `kasse.read`, `kasse.write`, `kasse.delete`, `kasse.export`
  - ⚠️ Werden in Phase 3.2 (Schema v8) durch kassenspezifische Berechtigungen ersetzt
- [x] `defaults_for_role()` vorläufig um Kasse-Permissions erweitert (wird in 3.2 rückgebaut)
- [x] Migration `_migrate_6_to_7()`: vorläufige Kasse-Permissions für bestehende User

---

**Legende:**
- 🔥 = Hohe Priorität, nächste Schritte
- 📊 = Kassenbuch nächste Schritte (Phase 3)
- 📋 = Mittelfristig, Phase 3
- 🔮 = Längerfristig, Phase 4
- 💡 = Ideen, noch nicht priorisiert
- ✅ = Fertig
