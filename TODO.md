# TODO – VTB Vereinsverwaltung

> Roadmap / offene Aufgaben. Der **Funktionsumfang des fertigen Stands** steht in
> `README.md`; der Architektur-Rewrite (NiceGUI/SQLite → FastAPI/Quasar/PostgreSQL) ist
> abgeschlossen und in `REWRITE.md` dokumentiert. Hier stehen nur noch **offene** Punkte.

## 🔥 Hohe Priorität

### Mitgliederverwaltung
- [ ] **Papierkorb für Mitglieder** – gelöschte Mitglieder anzeigen + wiederherstellen,
      konsistent zur Abteilungs-Wiederherstellung
- [ ] **Export** – Mitgliederliste als CSV (konfigurierbare Spalten) und Excel
- [ ] **Pagination / Lazy Loading** für große Listen (>1000 Mitglieder); Performance-Test

### Mitglieder-Import (SPG-Verein)
- [x] Echter Import-Lauf der Bestandsdaten durchführen (Importer `tools/import_spg.py`
      ist fertig + idempotent)
- [x] Beiträge-Import ergänzen
- [ ] Neu importierte Felder in der Personen-UI sichtbar machen

### Tickets
- [ ] **History-Expander** im Ticket-Detail (lazy load der `*_history`-Daten)

### Berechtigungssystem (Ticket #22, Konzept: `BERECHTIGUNGEN.md`)
Stufen A–D umgesetzt (Datenmodell v36, funktionsbasierte Rechte, Funktions- und
persönliche Matrix, Rollen-Ablösung). Offen:
- [x] **Stufe A** – Datenmodell v35 + effektive Berechnung + Sockel
- [x] **Stufe B** – Funktions-Matrix: GET/PUT `/api/funktionen/{id}/permissions`
- [x] **Stufe C** – persönlicher Berechtigungsscreen: Herkunft + Tri-State `{grants,denies}`
- [x] **Stufe D** – Rollen-Ablösung (v36): nur noch admin/mitglied,
      `defaults_for_role` entfernt, harte `role=='admin'`-Checks ersetzt
      (`funktionen.verwalten`, `kassen.verwalten`, Ticket-Bereiche/Kategorien →
      `tickets.bereiche_verwalten`, Fremdkommentar-Delete → `tickets.delete`),
      Admin-Flag-Vergabe nur durch Admins (`backend/core/authz.py`)
- [ ] **Stufe E** – Scoping-Durchsetzung, Pilot Personen-/Mitgliederliste via
      `allowed_abteilungen('personen.read')`

## 🔔 Benachrichtigungen (Phase 3 – Automatisierung)

E-Mail + Matrix als Kanäle sind fertig; Ticket-Ereignisse lösen bereits Benachrichtigungen aus.
Offen ist die Verdrahtung weiterer Ereignisse:
- [ ] Willkommens-Mail → multi-channel (aktuell nur E-Mail)
- [ ] Beitrags-/Zahlungs-Erinnerungen
- [ ] Abteilungs-Ankündigungen
- [ ] **Web Push (PWA)** – Service Worker ist vorhanden; offen: `pywebpush` + VAPID-Keys
      + `push_subscriptions`-Tabelle + Abo-Flow im Frontend

## 📊 Reporting

- [ ] **Statistik-Dashboard / Kennzahlen** – Mitgliederentwicklung (Zu-/Abgänge),
      Altersstruktur, Zahlungsstatus, Abteilungsübersicht; grafische Auswertungen
      (`DashboardPage.vue` ist aktuell reine Navigation)

## 🧹 Tech-Debt / bekannte Altlasten

Offen:
- [ ] PostgreSQL-Test-Fixture/conftest etablieren (es gibt keine DB-nahe Test-Infra;
      bewährter manueller Weg bisher: Dev-DB-Dump → Wegwerf-Container postgres:18 → migrieren)
- [ ] Stale SQLite-Erwähnung in `vtb_verein/tests/README.md` bereinigen
- [ ] **Einheitliche Mitglied-Edit-Komponente** – die neue `MitgliedEditDialog.vue`
      (Stammdaten + Abteilungen + Funktionen, eingebunden in die Abrechnungsvorschau)
      auch in `PersonenPage.vue` und `MitgliederPage.vue` nutzen, damit die
      Mitglieds-Bearbeitung eine Single-Source ist (aktuell dort dupliziert)
- [ ] **Beitragslogik: CURRENT_DATE statt Stichtag** – `beitrags_service.py`
      wertet Funktions-Bedingungen mit `CURRENT_DATE` statt dem Abrechnungs-
      Stichtag aus; bei rückwirkender Abrechnung zählen aktuelle statt
      historischer Funktionen
- [ ] **mitglied_funktion.funktion → funktion_id umstellen** – echter FK statt
      String-Key (FK auf partiellen Unique-Index nicht möglich); betrifft
      Repository, API, Frontend und Beitragsregeln (`bedingung_funktionen`);
      v35 loggt verwaiste Keys nur als WARN
- [ ] Tote Konstante `VALID_FUNKTIONEN` in `mitglied_funktion_repository.py`
      entfernen (Katalog validiert längst über die `funktion`-Tabelle)

Erledigt (2026-06-11):
- [x] Frischaufbau-FK-Bug behoben – `mitglied→users` / `beitrag_sollstellung→kassenbuchungen`
      werden jetzt nach allen CREATE TABLE per ALTER nachgezogen
      (Branch `fix/frischaufbau-fk-reihenfolge`)
- [x] Fehlende Audit-Trigger auf `beitragsregel` **und** `beitrag_sollstellung` nachgezogen
      (Migration v32, Branch `fix/fehlende-beitrag-trigger`)
- [x] Veraltete SQLite-Tests entfernt (nur noch Doku-Erwähnung übrig, s.o.)

## 💡 Backlog / Ideen (längerfristig)

### Rollenspezifische Sichten
- [ ] Dashboard für Abteilungsleiter (nur eigene Abteilung(en), Mitglieder + Statistik)
- [ ] Dashboard für Übungsleiter (Trainingsgruppen, Anwesenheit)

> Hinweis: Abteilungsleiter/Übungsleiter werden **als Funktion** abgebildet (Funktionen-System),
> nicht über ein dediziertes Feld an der Abteilung.

### Weitere Module
- [ ] Trainingsplan-/Hallenplanung (Trainingszeiten, Trainer-Zuordnung)
- [ ] Anwesenheitslisten (Check-in/-out, Statistik je Mitglied)
- [ ] Dokumentenverwaltung pro Mitglied (Verträge, Bescheinigungen, Ablaufdatum-Tracking)

### Infrastruktur
- [ ] CI/CD (GitHub Actions): automatische Tests, Container-Registry-Push, Auto-Deploy auf Tag
- [ ] Multi-Mandanten-Fähigkeit (mehrere Vereine, Datentrennung)
- [ ] Externe REST-API / Webhooks für Integrationen

---

## ✅ Bereits erledigt (Auszug – Details in README.md)

Personen-/Benutzerverwaltung (Rollen + Permission-Matrix, Magic-Link, Self-Service-Profil) ·
mehrfache Kontaktdaten (v24) · Abteilungen + Funktionen (v25) · Mitglied-Abteilung-Zuordnung ·
Mannschaften (v27) · Beiträge inkl. Sollstellung, altersabhängige Regeln (v26) & SEPA-Export ·
Gebühren (v28) · Kassenbuch (Multi-Kasse, Storno, CSV-Export, PDF-Bericht, kassenspezifische
Berechtigungen) · Tickets (vollständig, inkl. Bereichs-Berechtigungen) · domänen-isolierte
Anhänge · Audit-Trail & Soft-Delete durchgängig · E-Mail- + Matrix-Benachrichtigungen ·
PWA · Personen-Liste mit Filter (Status/Abteilung/Funktion) + Volltextsuche ·
Mobile-Optimierung (Kassenbuch + Tickets) · Dark Mode.
