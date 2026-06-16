# TODO – VTB Vereinsverwaltung

> Roadmap / offene Aufgaben. Der **Funktionsumfang des fertigen Stands** steht in
> `README.md`; der Architektur-Rewrite (NiceGUI/SQLite → FastAPI/Quasar/PostgreSQL) ist
> abgeschlossen und in `REWRITE.md` dokumentiert. Hier stehen nur noch **offene** Punkte.

## 🔥 Hohe Priorität

### Mitgliederverwaltung
- [x] **Papierkorb für Mitglieder** – gelöschte Mitglieder anzeigen + wiederherstellen,
      konsistent zur Abteilungs-Wiederherstellung
- [ ] **Export** – Mitgliederliste als CSV (konfigurierbare Spalten) und Excel
- [ ] **Pagination / Lazy Loading** für große Listen (>1000 Mitglieder); Performance-Test
- [ ] **IBAN-Prüfung bei Änderung** – beim Bearbeiten/Speichern der IBAN validieren
      (Format + Prüfziffer nach ISO 13616/Modulo 97), ungültige Eingaben ablehnen
- [ ] **Umgang mit ausgetretenen Mitgliedern klären** – aktuell bleiben Mitglieder mit
      Status „ausgetreten" zeitlich unbegrenzt in der Personenliste (nur Soft-Delete in
      den Papierkorb blendet sie aus). Offen: sollen sie per Default ausgeblendet werden
      (Filter „Ausgetretene anzeigen"), nach X Jahren automatisch archiviert/gelöscht
      werden (DSGVO-Aufbewahrungsfristen?), o. Ä.

### Mitglieder-Import (SPG-Verein)
- [x] Echter Import-Lauf der Bestandsdaten durchführen (Importer `tools/import_spg.py`
      ist fertig + idempotent)
- [x] Beiträge-Import ergänzen
- [ ] Neu importierte Felder in der Personen-UI sichtbar machen

### Tickets
- [ ] **History-Expander** im Ticket-Detail (lazy load der `*_history`-Daten)

### Kassenbuch
- [x] **Verwaltete Kassen-Kategorien statt Freitext** – Stammdaten-Tabelle `kassen_kategorien`
      (allgemein für alle Kassen oder kassenspezifisch via `kasse_id`) + Dropdown bei der
      Erfassung (Migration v38). Buchung speichert die Kategorie weiterhin als Text;
      Bestands-Freitexte bleiben als Legacy erhalten.
  - [x] **Pflicht zur Kategorieauswahl** – Frontend erzwingt die Auswahl, sobald Kategorien
        existieren; Backend validiert die Zugehörigkeit (leer erlaubt, unveränderter
        Legacy-Altwert beim Bearbeiten geschont).
  - Bewusst **keine eigene Berechtigung**: Verwaltung läuft über `kassen.verwalten`.
- [ ] **Zählprotokoll** – Stückelung der Barkasse erfassen (Anzahl je Münz-/Scheinwert →
      automatische Summe, Soll-/Ist-Abgleich mit dem Kassenstand)

## 🔔 Benachrichtigungen (Phase 3 – Automatisierung)

E-Mail + Matrix als Kanäle sind fertig; Ticket-Ereignisse lösen bereits Benachrichtigungen aus.
Offen ist die Verdrahtung weiterer Ereignisse:
- [ ] Willkommens-Mail → multi-channel (aktuell nur E-Mail)
- [ ] Beitrags-/Zahlungs-Erinnerungen
- [ ] Abteilungs-Ankündigungen
- [ ] **Web Push (PWA)** – Service Worker ist vorhanden; offen: `pywebpush` + VAPID-Keys
      + `push_subscriptions`-Tabelle + Abo-Flow im Frontend

## 📊 Reporting

- [x] **Statistik-Dashboard / Kennzahlen** – eigene Berichte-Seite (`BerichtePage.vue`,
      Route `berichte`, Permission `berichte.read`) mit KPI-Karten, Mitgliederentwicklung
      (Zu-/Abgänge, umschaltbar **letzte 12 Monate / letzte 12 Jahre**), Altersstruktur,
      Geschlechterverteilung und Abteilungsübersicht; grafische Auswertungen ohne neue
      Dependency (CSS/Quasar). Backend: `StatistikRepository` +
      `GET /api/berichte/statistik` (Branch `feature/statistik-dashboard`)
  - [x] **Getestet gegen echte DB (2026-06-15):** API ohne SQL-Fehler, alle Blöcke
        plausibel; Stichprobe (Ø-Alter, Altersgruppen, Mitglieder je Abteilung) deckt
        sich; Berechtigung (Backend 403 + Nav-/Dashboard-Karte/Route-Guard auf
        `berichte.read`); Frontend rendert (eslint sauber, Umschalter im `outline`-Stil
        Dark-Mode-tauglich, vom Nutzer visuell bestätigt).
  - [x] **Datums-Edge-Cases abgesichert:** die Regex-Guards prüften nur das *Format*,
        nicht die *Gültigkeit* – format-gültige Unmöglichkeiten (z. B. `2026-02-30`)
        ließen den `::date`-Cast und damit die Query abstürzen (HTTP 500). Behoben mit
        DB-Funktion `safe_to_date(text)` (Migration **v39**, Frischaufbau + Migrationspfad
        im Wegwerf-Container getestet); `kpis()`/`altersstruktur()` casten darüber.
- [ ] **Zahlungsstatus im Dashboard** – bewusst ausgeklammert; ergänzen, sobald die
      Auswertung der offenen Beiträge/Sollstellungen definiert ist

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
- [ ] **Stundenabrechnung Übungsleiter** – Übungsleiter tragen ihre geleisteten Stunden
      je Zeitraum (**Monat/Quartal**) in der App ein, der Abteilungsleiter bestätigt sie
      (Genehmigungs-Workflow). Erst nach Bestätigung folgt die **Verbuchung / Export an die
      Fibu** (Finanzbuchhaltung). Voraussetzung: hinterlegte **Stundensätze** als Stammdaten,
      voraussichtlich **je Abteilung** (ggf. zusätzlich personenabhängig). Auswertung:
      bestätigte Stunden × Satz → Abrechnungsübersicht/Export pro Übungsleiter und Zeitraum.

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
