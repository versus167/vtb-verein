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
- [x] **IBAN-Prüfung bei Änderung** – beim Bearbeiten/Speichern der IBAN validieren
      (Format + Prüfziffer nach ISO 13616/Modulo 97), ungültige Eingaben ablehnen.
      Kern `app/services/iban.py` (Struktur + Länderlänge + Modulo-97) → HTTP-Adapter
      `iban_or_422` (422 bei Ungültig, kanonische Speicherung), verdrahtet an allen
      Save-Endpoints (`personen.py`/`mitglieder.py`); Frontend-Inline-Prüfung
      (`utils/iban.js`, `:rules`) in MitgliedEditDialog/Profil/Personen. **Immer strikt**
      (Alt-IBANs müssen beim Speichern korrigiert/geleert werden). BIC + SPG-Import
      bewusst ausgeklammert.
- [x] **Ausgetretene in der Personenliste standardmäßig ausblenden** – ausgetretene
      Mitglieder (Austrittsdatum in der Vergangenheit) sind per Default ausgeblendet,
      nur per Häkchen „Ausgetretene anzeigen" sichtbar (v2026.06.17.17). „Ausgetreten"-
      Definition konsistent zum Statistik-Dashboard (am Austrittstag selbst noch Mitglied).
      Spalte „Eintritt" → „Eintritt/Austritt" (Austrittsdatum weiß auf rot).
- [ ] **Aufbewahrung/Archivierung ausgetretener Mitglieder** – offen: nach X Jahren
      automatisch archivieren/löschen (DSGVO-Aufbewahrungsfristen?), o. Ä.

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
- [x] **Zählprotokoll** – Stückelung der Barkasse erfassen (Anzahl je Münz-/Scheinwert →
      automatische Summe, Soll-/Ist-Abgleich mit dem Kassenstand). Umsetzung: eine Zählung
      **ist eine Buchung** – jede Zählung erzeugt eine „Zähl-/Differenzbuchung", an die das
      Protokoll-PDF gehängt wird (Uhrzeit/Ersteller über die Buchung dokumentiert). Die
      Differenz (Ist−Soll) wird immer verbucht: unter der **auslösenden Kategorie**
      (Kategorie-Trigger `loest_zaehlung_aus`) sonst unter **„Kassendifferenz"**; bei
      Differenz 0 als 0-€-Buchung. `soll_cent` wird eingefroren. Auslöser: Button
      „Kasse zählen" **+** Kategorie-Flag (Prompt nach der Buchung). Tabelle
      `kassen_zaehlungen` (Stückelung als JSONB), Migration **v43**, keine eigene Permission
      (Schreibzugriff auf die Kasse). Plan: `ZAEHLPROTOKOLL_PLAN.md`.

### Beiträge / Gebühren
- [x] **Fibu-Export der Sollstellungen** – **kein** SEPA-Export in dem Sinne, sondern ein
      **Delta-/Inkrement-Export**: ausgegeben werden alle bisher **nicht exportierten**
      Sollstellungen. Statt der Markierung „bezahlt" bekommt eine Sollstellung beim Export
      die Markierung **„exportiert"** (in die Finanzbuchhaltung exportiert). Auch
      **Stornos/Löschungen** bereits exportierter Sollstellungen fließen in den nächsten
      Export ein – als korrespondierende **Export-(Gegen-)Buchung** –, damit die Fibu
      konsistent bleibt (kein stilles Verschwinden bereits exportierter Beträge).
      Umgesetzt im Format **hmd FBASC** (`fbasc.hia`, Migration **v46**, Permission
      `fibu.export`, Seite „Fibu-Export"). Konten: Debitor = Basis + Mitgliedsnr.,
      Gegenkonto je Regel/Gebühr, Kostenstelle aus Abteilung (Verein = 12), Kostenträger 1.
      Bisherige Platzhalter-SEPA-CSV-Exporte (Beiträge/Gebühren) entfernt. Offen: echte
      Kontenrahmen-Werte (SKR49 o.Ä.) sind als Daten zu pflegen, nicht im Code.
  - [x] Sollstellungen von Beiträgen und Gebühren je Person sichtbar (Tab „Beiträge &
        Gebühren" im Mitglied-Editor, read-only inkl. Export-Status)

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
- [x] **Einheitliche Mitglied-Edit-Komponente** – `MitgliedEditDialog.vue` (Stammdaten +
      Abteilungen + Funktionen) ist Single-Source und wird in `PersonenPage.vue` +
      `BeitragsverwaltungPage.vue` genutzt. Die alte, dupliziert pflegende
      `MitgliederPage.vue` war eine verwaiste Seite (nur per direkter URL `/mitglieder`
      erreichbar, nirgends verlinkt) und wurde samt Route entfernt.
- [x] **Beitragslogik: Funktions-/Ausnahme-Bedingungen zeitraumgenau** – früher
      werteten die Funktions-/Ausnahme-Bedingungen `CURRENT_DATE` statt des Abrechnungs-
      Stichtags aus (bei rückwirkender Abrechnung zählten *aktuelle* statt *historischer*
      Funktionen). Jetzt gehen die Funktions-/Ausnahme-Intervalle in die **anteilige
      Monatsberechnung** ein: Einschluss schränkt die abgerechneten Monate ein
      (Schnittmenge), Ausnahme zieht Monate ab – „angefangener Monat zählt voll",
      konsistent zu Mitgliedschaften/Alter (am Stichtag). Reine Logik in
      `funktions_monats_restriktion` (unit-getestet); der frühere SQL-`EXISTS`/
      `CURRENT_DATE`-Filter in `_betroffene_mitglieder` entfällt.
- [ ] **mitglied_funktion.funktion → funktion_id umstellen** – echter FK statt
      String-Key (FK auf partiellen Unique-Index nicht möglich); betrifft
      Repository, API, Frontend und Beitragsregeln (`bedingung_funktionen`);
      v35 loggt verwaiste Keys nur als WARN
- [x] Tote Konstante `VALID_FUNKTIONEN` in `mitglied_funktion_repository.py`
      entfernt (Katalog validiert längst über die `funktion`-Tabelle)

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
Mannschaften (v27) · Beiträge inkl. Sollstellung, altersabhängige Regeln (v26) ·
Gebühren (v28) · Fibu-Export der Sollstellungen (FBASC, v46) · Kassenbuch (Multi-Kasse,
Storno, CSV-Export, PDF-Bericht, kassenspezifische
Berechtigungen) · Tickets (vollständig, inkl. Bereichs-Berechtigungen) · domänen-isolierte
Anhänge · Audit-Trail & Soft-Delete durchgängig · E-Mail- + Matrix-Benachrichtigungen ·
PWA · Personen-Liste mit Filter (Status/Abteilung/Funktion) + Volltextsuche ·
Mobile-Optimierung (Kassenbuch + Tickets) · Dark Mode ·
Auth-Härtung (Ticket #48): Magic-Link-Token nur als SHA-256-Hash, Single-Use
(`UPDATE … RETURNING`) + Rate-Limit (v47); JWT im HttpOnly-Cookie statt localStorage;
Ticket-Tool auf Cookie-Auth umgestellt.
