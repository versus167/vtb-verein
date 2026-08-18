# TODO – VTB Vereinsverwaltung

> Roadmap / offene Aufgaben. Der **Funktionsumfang des fertigen Stands** steht in
> `README.md`; der Architektur-Rewrite (NiceGUI/SQLite → FastAPI/Quasar/PostgreSQL) ist
> abgeschlossen. Hier stehen nur noch **offene** Punkte.
>
> Abgeschlossene Vorhaben mit eigenem Planungsdokument liegen unter
> [`docs/archiv/`](docs/archiv/); Pläne mit offenen Etappen bleiben im
> Wurzelverzeichnis und sind unten jeweils verlinkt.

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
- [x] **Zutrittslog-Aufbewahrung ins allgemeine Prune** – erledigt: `tuer_zutritt_log`
      läuft wie alle append-only Protokolle über das **`LOG_REGISTRY`** in
      `app/services/prune_service.py` (alters-basiertes Löschen, Frist je Regel auf der
      Datenbereinigungs-Seite einstellbar, Default 365 Tage). **Grundsatz: kein Protokoll
      wird unbegrenzt aufbewahrt** – jede neue Log-Tabelle braucht eine `LogRule`.

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
      (Schreibzugriff auf die Kasse).

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

E-Mail, Telegram, Matrix und Web-Push sind als Kanäle fertig und je Profil wählbar;
Ticket- und Termin-Ereignisse lösen bereits Benachrichtigungen aus.
Offen ist die Verdrahtung weiterer Ereignisse:
- [ ] Willkommens-Mail → multi-channel (aktuell nur E-Mail)
- [ ] Beitrags-/Zahlungs-Erinnerungen
- [ ] Abteilungs-Ankündigungen
- [x] **Web Push (PWA)** – umgesetzt (#96, Schema v67): `pywebpush` + VAPID,
      `push_subscriptions`, Abo-Flow im Profil. Live getestet (v2026.07.13.98).

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

## 🧭 Laufende Vorhaben (Pläne mit offenen Etappen)

Was hier steht, hat ein Planungsdokument. Pläne mit offenen Etappen liegen weiter im
Wurzelverzeichnis, abgeschlossene unter [`docs/archiv/`](docs/archiv/) — bei letzteren
sind nur noch die Reste unten offen. Was jeweils schon fertig ist, steht im Kopf des
Dokuments.

### Spielplan / Spielstätten — [`DFBNET_IMPORT_PLAN.md`](DFBNET_IMPORT_PLAN.md)
- [ ] **Belegungsansicht für Plätze** (letztes Stück von Etappe 5): eigene Termine und
      die fremden Spiele aus der Platzbelegung in *einer* Sicht, filterbar nach Platz und
      Zeitraum. Die Voraussetzungen stehen bereits — eigenes Recht
      `spielstaetten.verwalten` (v86) und `spielstaette_id` an Terminen *und* Serien (v80),
      Trainings sind also schon erfasst.

### Zutrittskontrolle — [`ZUTRITTSKONTROLLE_PLAN.md`](ZUTRITTSKONTROLLE_PLAN.md)
- [ ] **Phase 5 zu Ende führen**: Zutrittslog vollständig auf Mitglieder auflösen.
      Heute löst der Sync die IC-Karte auf; Fingerprint/Passcode/eKey brauchen die
      Zuordnung der gespiegelten Credentials (`tuer_credential`, v59) zu Personen.
- [ ] **Alarm-Empfänger feiner scopen** (heute zu grob adressiert)
- [ ] **Auswertungen/Reports** über die Zutritte (die verdichtete „wer, wann, welche Tür"-
      Sicht aus #161 steht, weitergehende Berichte nicht)

### Spielbetrieb, Etappe 4 — Plan im Archiv ([`docs/archiv/SPIELBETRIEB_PLAN.md`](docs/archiv/SPIELBETRIEB_PLAN.md))
Etappen 1–3 sind umgesetzt; hier bleibt der optionale Rest:
- [ ] Automatischer fussball.de-Sync (statt/neben CSV-Import) — Risiko: TOS, Bruchgefahr
- [ ] Aufgaben rund um den Termin (Fahrdienst, Trikotwäsche)
- [ ] Aufstellungen
- [ ] Antwortfristen/Strafenkatalog — Grundsatzfrage, ob gewünscht oder ob die Erinnerung reicht

### Teamkasse — Plan im Archiv ([`docs/archiv/CLUBDECKEL_PLAN.md`](docs/archiv/CLUBDECKEL_PLAN.md))
Umgesetzt; offen sind nur die beiden „bei Bedarf"-Punkte:
- [ ] Warnschwellen bei hohem Negativ-Saldo (Anzeige/Benachrichtigung)
- [ ] Events/Push aus dem Vorbild — später als Erweiterung oder ganz weglassen

### LINEAR-Import / zweite Instanz — [`LINEAR_IMPORT_PLAN.md`](LINEAR_IMPORT_PLAN.md), [`ZWEITE_INSTANZ.md`](ZWEITE_INSTANZ.md)
- [ ] ⚠️ **Echt-Export beschaffen und den Import damit prüfen.** Parser, Mapping und
      Endpunkt stehen, aber **nur gegen den Muster-Auszug**. Die im Plan gesetzte Frist
      (17.08.2026) ist verstrichen, Instanz B ist für den 20.08.2026 vorgesehen →
      **Dry-Run ist Pflicht**, nicht Kür. Offene Datenfragen: Status-Werte, zusätzliche
      Spalten, Dubletten mit dem SPG-Bestand.
- [ ] Nach dem Import nachzupflegen: **SEPA-Mandatsreferenz und -datum** (die Datei
      liefert sie nicht → ohne sie ist kein Einzug möglich) sowie **E-Mail-Adressen**
      (ohne die kein Magic-Link-Zugang)

## 🔐 Sicherheit (offene Punkte)

Die Härtungsrunde vom August 2026 ist umgesetzt (Anhang-Downloads, Abteilungs-Scope auf
ID-Endpunkten, Delegationsregel, Anmelde-Bremse, Upload-Grenzen, CSP — v2026.08.12.193
bis .196). Was daraus offen blieb:

- [ ] **API-Doku ist öffentlich erreichbar** – `/api/docs`, `/api/redoc` und
      `/api/openapi.json` hängen ohne Auth an der App (`backend/main.py`). Das ist eine
      vollständige Landkarte der Endpunkte für jeden, der die URL kennt. Entscheidung
      nötig: hinter Auth legen, auf Admins beschränken oder in Produktion abschalten.
- [ ] **`VTB_SECRET_KEY`-Länge nicht geprüft** – Default ist der Platzhalter
      `CHANGE_ME_IN_PRODUCTION`, und ein zu kurzer Schlüssel fällt nur als PyJWT-Warnung
      auf. Beim Start prüfen (≥ 32 Byte) und bei Platzhalter/zu kurz laut abbrechen statt
      still weiterlaufen.
- [ ] **Body-Size-Limit im Proxy** setzen (Betriebs-Aufgabe, nicht Code): Die App bricht
      übergroße Uploads jetzt selbst ab, aber erst nachdem sie den Strom gelesen hat.

## 🧹 Tech-Debt / bekannte Altlasten

Offen:
- [ ] **PostgreSQL-Test-Fixture/`conftest.py` etablieren.** Es gibt weiterhin keine
      gemeinsame Fixture: Jede Integrationstest-Datei baut ihre DB-Anbindung selbst und
      skippt einzeln, wenn `VTB_TEST_DATABASE_URL` fehlt. Bewährter Weg bisher:
      Wegwerf-Container `postgres:18`, leere DB, `VereinsDB` legt das Schema beim Connect an.
- [ ] **Tote Methoden in `access_log_repository.py` entfernen** –
      `count_page_views_older_than` und `cleanup_page_views` ruft niemand mehr auf, seit
      die Bereinigung generisch über das `LOG_REGISTRY` läuft. Sie stehen nur noch als
      Fußnote da (ihr früherer Wortlaut hatte die irrige Annahme genährt, Auth-Ereignisse
      würden dauerhaft aufbewahrt).
- [x] Stale SQLite-Erwähnung in `vtb_verein/tests/README.md` bereinigt (2026-08-18);
      die Datei beschreibt jetzt die tatsächliche Suite statt zweier Alt-Dateien
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
- [ ] Trainingsplan-/Hallenplanung (Trainingszeiten, Trainer-Zuordnung) – **teilweise
      abgedeckt**: Terminserien und Spielstätten gibt es; was fehlt, ist die Sicht *vom
      Platz/der Halle aus* (s. Belegungsansicht oben)
- [ ] Anwesenheitslisten (Check-in/-out, Statistik je Mitglied) – **Zu-/Absagen** je Termin
      sind da (`termin_zusage`); offen ist die *tatsächliche* Anwesenheit und deren Auswertung
- [ ] Dokumentenverwaltung pro Mitglied (Verträge, Bescheinigungen, Ablaufdatum-Tracking)
- [x] **Stundenabrechnung Übungsleiter** – umgesetzt (Schema v52–v55/v59): Erfassung je
      Abrechnungszeitraum, Stundensätze als Stammdaten, Bestätigungs-Workflow durch den
      Abteilungsleiter, Trainerlizenz-Klassifikation mit Gültigkeitsfenster,
      Stundennachweis-PDF und Fibu-Export als Kreditor je Übungsleiter. Rechte über
      `ulstunden.*`; das Bestätigen ist **abteilungsscharf** (der Scope kommt aus der
      Funktions-Zuordnung, individuelle Grants wirken dagegen vereinsweit — so gewollt).
- [x] **Zutrittskontrolle / Schließsystem (TT-Lock)** – umgesetzt (Schema v56–v59/v64,
      ausgebaut bis v96). Inventar-/Log-Spiegel aus der TTLock-Cloud, Fernöffnen,
      Chip-Verwaltung übers Gateway, Rechtegruppen, externes Schloss ohne Cloud-Anschluss,
      Chip-Inhaber ohne Mitgliedschaft. Offene Reste stehen oben unter „Laufende Vorhaben".
      Plan: [`ZUTRITTSKONTROLLE_PLAN.md`](ZUTRITTSKONTROLLE_PLAN.md).

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

Seit Juli 2026 dazugekommen: Mannschafts-Termine mit Serien und Zu-/Absagen (v68–v70) ·
Gastspieler als eigene Personenart (v72) · Teamkasse/Clubdeckel (v75/v76) ·
Rechnungen einreichen & freigeben (v78) · SEPA-Lastschrift pain.008 (v79) ·
DFBnet-Spielplan-Import inkl. Abweichungs-Workflow (v80–v86, v94/v95) ·
Kalender-Abo als ICS-Feed (v89) · Web-Push als wählbarer Kanal (v67, #96) ·
LINEAR-Import (ohne Migration) · Konsistenzprüfung + generische Log-Retention ·
drei Themes und Branding aus Env statt aus dem Code ·
Sicherheitsrunde August 2026: Anhang-Downloads an der Elternberechtigung,
Abteilungs-Scope auf ID-Endpunkten, Delegationsregel, Anmelde-Bremse, Upload-Grenzen, CSP.
