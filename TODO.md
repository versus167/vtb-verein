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

## 🎫 Phase 4 - Ticketsystem

### Datenbank & Schema
- [ ] DB-Schema Ticketsystem anlegen
  - Tabelle `ticket_areas` (Bereiche: Platz, Kabinen, Gebäude, …)
  - Tabelle `ticket_categories` (Kategorien: Schaden, Sicherheit, Ausstattung, …)
  - Tabelle `tickets` (id, title, description, status, priority, area_id, category_id, reported_by, assigned_to, due_date, closed_at, closed_by, version, created_at, deleted_at, deleted_by)
  - Tabelle `ticket_comments` (id, ticket_id, author_id, body, visibility `public|internal`, version, created_at, deleted_at, deleted_by)
  - Tabelle `ticket_attachments` (id, ticket_id, comment_id, original_name, stored_name, mime_type, file_size, uploaded_by, uploaded_at, deleted_at, deleted_by)
  - Tabelle `ticket_participants` (ticket_id, member_id, added_by, added_at)
  - History-Tabellen: `tickets_history`, `ticket_comments_history`
  - INSERT/UPDATE-Trigger für `tickets` und `ticket_comments` (kein DELETE-Trigger)
  - Keine History-Trigger für `ticket_attachments` und `ticket_participants`

- [ ] Dateiablage für Anhänge definieren
  - Speicherverzeichnis konfigurierbar (z. B. über `.env`)
  - `stored_name` nach Schema: `att_{id:06d}.{ext}` (ID-basiert, zweistufig: INSERT → UPDATE)
  - Soft-Delete in DB, physische Datei bleibt erhalten (Prune-Funktion für später)

### Repositories & Service
- [ ] `TicketAreaRepository` (CRUD, Soft-Delete, `get_all_active()`)
- [ ] `TicketCategoryRepository` (CRUD, Soft-Delete, `get_all_active()`)
- [ ] `TicketRepository`
  - `create()`, `update()`, `mark_ticket_deleted()`
  - `get_by_id()`, `get_for_user()` (gefiltert nach Rolle/Bereich)
  - `get_all_for_admin()`, `get_by_area()`
  - Optimistic Locking (version)
- [ ] `TicketCommentRepository`
  - `create()`, `update()`, `mark_comment_deleted()`
  - `get_for_ticket(ticket_id, visibility_filter)` – interne Kommentare nur für Platzwart+
- [ ] `TicketAttachmentRepository`
  - `create()`, `mark_attachment_deleted()`
  - `get_for_ticket()`, `get_for_comment()`
- [ ] `TicketParticipantRepository`
  - `add_participant()`, `remove_participant()`, `get_participants(ticket_id)`
- [ ] `TicketService` (Business-Logik)
  - Berechtigungsprüfung (Rolle + Bereichs-Scope)
  - Status-Übergänge validieren (offen → in_pruefung → eingeplant → erledigt etc.)
  - Anhang-Upload: Datei speichern + DB-Eintrag anlegen
  - Interne Kommentare nur für Platzwart/Bereichsleiter/Admin sichtbar
  - Custom Exceptions: `KeinZugriffError`, `UngueltigerStatusError`

### Berechtigungskonzept
- [ ] Ticket-Berechtigungen in Permission-Matrix integrieren
  - Neue Permissions: `tickets.lesen`, `tickets.erstellen`, `tickets.bearbeiten`, `tickets.verwalten`
  - Rollen-Defaults: Mitglied → erstellen+eigene lesen; Platzwart → Bereich lesen+bearbeiten; Admin → alles
- [ ] Bereichs-Scope für Platzwarte
  - Zuordnung Platzwart ↔ `ticket_area` (eigene Tabelle oder über `user_permissions` mit area_id)
  - Platzwart sieht nur Tickets seiner zugewiesenen Bereiche

### UI
- [ ] Ticket erstellen (Mitglied-Sicht)
  - Formular: Titel, Beschreibung, Kategorie, Bereich, Priorität
  - Anhänge hochladen (Fotos, max. Dateigröße prüfen)
  - Bestätigung nach Anlage
- [ ] Meine Tickets (Mitglied-Sicht)
  - Liste eigener Tickets mit Status-Badge
  - Detail-Ansicht: öffentliche Kommentare, Anhänge, Status-Verlauf
  - Eigenen öffentlichen Kommentar ergänzen
- [ ] Ticket-Übersicht (Platzwart-Sicht)
  - Gefiltert auf eigene Bereiche
  - Status ändern, Ticket übernehmen/zuweisen
  - Interne und öffentliche Kommentare schreiben
  - Anhänge anzeigen / herunterladen
- [ ] Ticket-Verwaltung (Admin-Sicht)
  - Alle Tickets systemweit
  - Filter: Bereich, Kategorie, Status, Priorität, Zeitraum
  - Eskalation, Bereichswechsel, Abschluss
  - Bereiche und Kategorien konfigurieren
- [ ] Navigation & Dashboard-Card
  - Menüpunkt „Tickets" rollenabhängig sichtbar
  - Dashboard-Card mit offenen Tickets (Mitglied: eigene; Platzwart: Bereich; Admin: alle)

### Technisches
- [ ] Migration `schema_vX` für Ticketsystem-Tabellen
- [ ] `datastore.py`: Ticket-Repositories und Service einbinden
- [ ] `main.py`: Ticket-Seiten registrieren
- [ ] Datei-Serving: Route für Anhänge mit Zugriffsprüfung (nicht öffentlich zugänglich)

## 📋 Phase 3 - Mitgliederverwaltung Erweiterungen

### Anzeige & Navigation
- [ ] Gelöschte Mitglieder anzeigen/wiederherstellen
  - Eigene Ansicht „Gelöschte Mitglieder"
  - Wiederherstellungs-Button
  - Konsistent mit Abteilungs-Wiederherstellung

- [ ] Filter in Mitgliederliste
  - Nach Status (aktiv, passiv, ausgetreten)
  - Nach Abteilung
  - Nach Zahlungsart
  - Nach Austrittsdatum (z.B. „Letzten 6 Monate")

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
  - [x] „Auf Rollen-Standard zurücksetzen"-Button
  - [x] Schutz: letzter Admin kann USERS_MANAGE nicht verlieren
  - [x] Kassenbuch-Gruppe vorläufig integriert (in Phase 3.2 wieder entfernt)

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
- [x] `KassenbuchService` in `kassenbuch_service.py`
  - [x] Buchungssperre (Export-Schutz) via `BuchungGesperrtError`
  - [x] Bestandsprüfung (kein negativer Bestand) via `NegativerBestandError`
  - [x] Belegnummer-Generierung automatisch beim Anlegen
  - [x] Atomarer CSV-Export: Buchungen holen → CSV → Export-Datensatz → Buchungen sperren
  - [x] `get_kassenbericht_daten()` für PDF-Bericht
- [x] Kassenbuch-Repositories in `datastore.py` integriert
- [x] `db.kassenbuch`-Property auf `KassenbuchService`
- [x] Kasse-Permissions in `permission.py` vorläufig ergänzt (in 3.2 rückgebaut)
- [x] Migration `_migrate_6_to_7()`: vorläufige Kasse-Permissions für bestehende User

### Phase 3.2 - Kassenspezifische Berechtigungen (Schema v8)
- [x] Schema-Migration v7 → v8
  - [x] Neue Tabelle `kasse_berechtigungen` (darf_lesen / darf_schreiben / darf_exportieren, Soft-Delete, Versionierung)
  - [x] Neue Tabelle `kasse_berechtigungen_history` + INSERT/UPDATE-Trigger (kein DELETE-Trigger)
  - [x] Globale `kasse.*`-Permissions per Soft-Delete aus `user_permissions` entfernt
  - [x] Admins erhalten automatisch alle Rechte für bestehende Kassen
- [x] `KasseBerechtigungRepository` in `kasse_berechtigung_repository.py`
  - [x] `get_berechtigung()`, `get_berechtigungen_fuer_kasse()`, `get_kassen_ids_fuer_user()`
  - [x] `hat_lesezugriff()`, `hat_schreibzugriff()`, `hat_exportrecht()`
  - [x] `set_berechtigung()` (anlegen + aktualisieren + reaktivieren)
  - [x] `revoke_berechtigung()`, `revoke_alle_berechtigungen_fuer_kasse()`
- [x] `kasse.*`-Konstanten und `defaults_for_role()`-Einträge aus `permission.py` entfernt
- [x] `KasseBerechtigungRepository` in `datastore.py` eingebunden (`db.kasse_berechtigungen`)
- [x] Kassenbuch-Gruppe aus `permission_management.py` entfernt; Info-Hinweis ergänzt

### Phase 3.3 - Kassenverwaltungs-UI (Admin)
- [x] `kasse_management.py` erstellt
  - [x] Route `/kassen`: Liste aller Kassen als Cards (Name, Anfangsbestand, Abteilung)
  - [x] Kasse anlegen (Dialog mit Name, Beschreibung, Anfangsbestand, Abteilung)
  - [x] Beim Anlegen: Admins automatisch mit allen Rechten eintragen
  - [x] Kasse bearbeiten (gleicher Dialog, vorausgefüllt)
  - [x] Kasse löschen (Bestätigungsdialog, Soft-Delete + Berechtigungen entziehen)
  - [x] Route `/kassen/{id}/berechtigungen`: Berechtigungsmatrix pro Kasse
  - [x] Berechtigungsmatrix: Nicht-Admin-User × Lesen/Schreiben/Exportieren-Checkboxen
  - [x] Logik: Schreiben aktivieren setzt Lesen automatisch
  - [x] Info-Hinweis: Admins haben immer vollen Zugriff
- [x] `navigation.py`: Menüpunkt „Kassen" (nur Admins, Icon `account_balance_wallet`)
- [x] `main.py`: `create_kasse_management_page(db)` registriert; Dashboard-Card ergänzt

### Phase 3.4 - Berechtigungs-Integration & Kassenbuch-Page
- [x] `KassenbuchService`: kassenspezifische Berechtigungsprüfung integriert
  - [x] `get_kassen_fuer_user(user_id, is_admin)` – nur berechtigte Kassen
  - [x] `_pruefe_lesezugriff()`, `_pruefe_schreibzugriff()`, `_pruefe_exportrecht()`
  - [x] Custom Exceptions: `KeinLesezugriffError`, `KeinSchreibzugriffError`, `KeinExportrechtError`
  - [x] Admin-Bypass in allen Prüfmethoden
- [x] `KasseBerechtigungRepository` an `KassenbuchService` übergeben
- [x] `kassenbuch_page.py` erstellt (Route `/kassenbuch`)
  - [x] Kassen-Auswahl per Tab (nur berechtigte Kassen; Admins sehen alle)
  - [x] Kassenbestand prominent im Header (grün/rot)
  - [x] Buchungsliste mit laufendem Bestand (SQL-seitig, kein Python-Loop)
  - [x] Einnahmen grün, Ausgaben rot
  - [x] Stornierte Buchungen durchgestrichen + grau; per Checkbox einblendbar
  - [x] Exportierte Buchungen mit 🔒-Icon, Edit/Storno gesperrt
  - [x] Datumsfilter (Von/Bis) mit flexibler Eingabe
  - [x] Neue Buchung anlegen: separate Buttons Einnahme/Ausgabe (nur mit Schreibzugriff)
  - [x] Buchung bearbeiten: Dialog lädt Buchung frisch per ID aus DB
  - [x] Buchung stornieren: Bestätigungsdialog, Soft-Delete
  - [x] CSV-Export-Dialog (nur mit Exportrecht)
  - [x] **History-Expander pro Buchung**
    - [x] Toggle „Änderungshistorie anzeigen" steuert ob Expander-Button gerendert wird
    - [x] Nur sichtbar wenn `version > 1`
    - [x] Lazy load: `get_history(buchung_id)` erst beim Öffnen aufrufen
    - [x] History-Zeilen in gedämpfter Farbe (Grau), gleiche Spalten, read-only
    - [x] Versionsnummer je Zeile (v1, v2, …)
  - [x] `main.py`: Import + `create_kassenbuch_page(db)` registriert
- [x] `navigation.py`: Menüpunkt „Kassenbuch" für berechtigte User + Admins
  - [x] Sichtbar wenn mind. eine Kasse mit Lesezugriff vorhanden
  - [x] Aktiv-Highlighting passend zu anderen Menüeinträgen

### Phase 3 - Kassenbuch
- [x] Kassenbuch-Grundstruktur (Buchungen, Kassenabschluss, Export)
- [x] Export-Dateiname nach Schema: `{kassename}-export-{id}-{von}-bis-{bis}.csv`
- [x] Re-Export alter Exporte direkt aus dem Exportverlauf-Dialog

---

**Legende:**
- 🔥 = Hohe Priorität, nächste Schritte
- 🎫 = Ticketsystem (Phase 4)
- 📊 = Kassenbuch nächste Schritte (Phase 3)
- 📋 = Mittelfristig, Phase 3
- 🔮 = Längerfristig, Phase 4
- 💡 = Ideen, noch nicht priorisiert
- ✅ = Fertig
