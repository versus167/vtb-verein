# TODO – VTB Vereinsverwaltung

> Roadmap / offene Aufgaben. Der **Funktionsumfang des fertigen Stands** steht in
> `README.md`; der Architektur-Rewrite (NiceGUI/SQLite → FastAPI/Quasar/PostgreSQL) ist
> abgeschlossen. Hier stehen **nur offene Punkte** — was erledigt ist, wird aus dieser
> Datei entfernt und lebt in `README.md`, im jeweiligen Plandokument und im Code weiter.
>
> Abgeschlossene Vorhaben mit eigenem Planungsdokument liegen unter
> [`docs/archiv/`](docs/archiv/); Pläne mit offenen Etappen bleiben im
> Wurzelverzeichnis und sind unten jeweils verlinkt.
>
> *Stand des letzten Abgleichs gegen den Code: 2026-09-04.*

## 🔥 Hohe Priorität

### Mitgliederverwaltung
- [ ] **Export** – Mitgliederliste als CSV (konfigurierbare Spalten) und Excel
- [ ] **Pagination / Lazy Loading** für große Listen (>1000 Mitglieder); Performance-Test.
      `GET /api/personen` liefert heute alles auf einmal.
- [ ] **Neu importierte SPG-Felder in der Personen-UI sichtbar machen** (der Importer
      `tools/import_spg.py` schreibt sie längst, die Oberfläche zeigt sie nicht)

### Benachrichtigungen (Phase 3 – Automatisierung)
E-Mail, Telegram, Matrix und Web-Push sind als Kanäle fertig und je Profil wählbar;
Ticket- und Termin-Ereignisse lösen bereits Benachrichtigungen aus. Offen ist die
Verdrahtung weiterer Ereignisse:
- [ ] **Willkommens-Mail → multi-channel** (hängt in `user_service.py` weiterhin direkt
      an `EmailService.send_welcome_email`, statt über den Benachrichtigungs-Dienst zu gehen)
- [ ] Beitrags-/Zahlungs-Erinnerungen
- [ ] Abteilungs-Ankündigungen

### Reporting
- [ ] **Zahlungsstatus im Dashboard** – bewusst ausgeklammert; ergänzen, sobald die
      Auswertung der offenen Beiträge/Sollstellungen definiert ist

### Fibu
- [ ] **Echte Kontenrahmen-Werte pflegen** (SKR49 o. Ä.) – die Konten des FBASC-Exports
      sind als *Daten* zu führen, nicht im Code
- [ ] **Probeimport in hmd** mit einer echten `fbasc.hia` aus Sollstellungen, Kassenbuch
      und Rechnungen – alle drei Exporte sind gebaut, aber noch nie gegen die Ziel-Fibu
      eingelesen worden

## 🧭 Laufende Vorhaben (Pläne mit offenen Etappen)

Was hier steht, hat ein Planungsdokument. Pläne mit offenen Etappen liegen weiter im
Wurzelverzeichnis, abgeschlossene unter [`docs/archiv/`](docs/archiv/) — bei letzteren
sind nur noch die Reste unten offen. Was jeweils schon fertig ist, steht im Kopf des
Dokuments.

### Spielplan / Spielstätten — [`DFBNET_IMPORT_PLAN.md`](DFBNET_IMPORT_PLAN.md)
Alle fünf Etappen sind umgesetzt; die Belegungsansicht kam zuletzt (#152, Schema v118,
v2026.09.02.242, rollende 7-Tage-Sicht in .245). Offen sind nur noch die Grundsatzfragen
im Kopf des Plans — Spielende, Turniere, Importrhythmus, Platzwarte als eigene Rolle.
Sobald die entschieden sind, gehört das Dokument ins Archiv.

### Zutrittskontrolle — [`ZUTRITTSKONTROLLE_PLAN.md`](ZUTRITTSKONTROLLE_PLAN.md)
- [ ] **Phase 5 zu Ende führen**: Zutrittslog vollständig auf Mitglieder auflösen.
      Heute löst der Sync die IC-Karte auf (`tuer_zutritt_log.mitglied_id`);
      Fingerprint/Passcode/eKey brauchen die Zuordnung der gespiegelten Credentials
      (`tuer_credential`, v59 — hat bis heute keinen Personen-Bezug) zu Personen.
- [ ] **Alarm-Empfänger feiner scopen** (heute zu grob adressiert)
- [ ] **Auswertungen/Reports** über die Zutritte (die verdichtete „wer, wann, welche Tür"-
      Sicht aus #161 steht, weitergehende Berichte nicht)
- [ ] **Chip identifizieren** – Idee: unbekannten Chip über den Zutrittslog zuordnen.
      Vorher zu klären: erzeugen unberechtigte Chips überhaupt einen Record?

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
**Stand 2026-08-24: liegt.** Der Echt-Export ist nie eingetroffen, Instanz B zum
vorgesehenen 20.08.2026 nicht gestartet; ein neuer Termin steht nicht fest. Der Code ist
fertig und wartet auf Daten — kein Entwicklungs-, sondern ein Zulieferthema.
- [ ] ⚠️ **Echt-Export beschaffen und den Import damit prüfen.** Parser, Mapping und
      Endpunkt stehen, aber **nur gegen den Muster-Auszug**. Der **Dry-Run**
      (`commit=False`) ist der Pflicht-Erstschritt jedes Laufs. Offene Datenfragen:
      Status-Werte, zusätzliche Spalten, Dubletten mit dem SPG-Bestand.
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
- [ ] **Body-Size-Limit im Proxy** setzen (Betriebs-Aufgabe, nicht Code): Die App bricht
      übergroße Uploads jetzt selbst ab, aber erst nachdem sie den Strom gelesen hat.

## 🧹 Tech-Debt / bekannte Altlasten

- [ ] **PostgreSQL-Test-Fixture/`conftest.py` etablieren.** Es gibt weiterhin keine
      gemeinsame Fixture: Jede Integrationstest-Datei baut ihre DB-Anbindung selbst und
      skippt einzeln, wenn `VTB_TEST_DATABASE_URL` fehlt. Bewährter Weg bisher:
      Wegwerf-Container `postgres:18`, leere DB, `VereinsDB` legt das Schema beim Connect an.
- [ ] **Tote Methoden in `access_log_repository.py` entfernen** –
      `count_page_views_older_than` und `cleanup_page_views` ruft niemand mehr auf, seit
      die Bereinigung generisch über das `LOG_REGISTRY` läuft.
- [ ] **`mitglied_funktion.funktion` → `funktion_id` umstellen** – echter FK statt
      String-Key (FK auf partiellen Unique-Index nicht möglich); betrifft
      Repository, API, Frontend und Beitragsregeln (`bedingung_funktionen`);
      v35 loggt verwaiste Keys nur als WARN

## 💡 Backlog / Ideen (längerfristig)

### Rollenspezifische Sichten
- [ ] Dashboard für Abteilungsleiter (nur eigene Abteilung(en), Mitglieder + Statistik)
- [ ] Dashboard für Übungsleiter (Trainingsgruppen, Anwesenheit)

> Hinweis: Abteilungsleiter/Übungsleiter werden **als Funktion** abgebildet (Funktionen-System),
> nicht über ein dediziertes Feld an der Abteilung.

### Weitere Module
- [ ] Trainingsplan-/Hallenplanung (Trainingszeiten, Trainer-Zuordnung) – **weitgehend
      abgedeckt**: Terminserien, Spielstätten und seit #152 die Belegungsansicht je Platz.
      Offen bliebe die *Vergabe* selbst — Zeiten zuteilen, statt bestehende Termine nur
      anzuzeigen; zu klären, ob dafür überhaupt Bedarf besteht
- [ ] Anwesenheitslisten (Check-in/-out, Statistik je Mitglied) – **Zu-/Absagen** je Termin
      sind da (`termin_zusage`); offen ist die *tatsächliche* Anwesenheit und deren Auswertung
- [ ] Dokumentenverwaltung pro Mitglied (Verträge, Bescheinigungen, Ablaufdatum-Tracking)

### Infrastruktur
- [ ] CI/CD (GitHub Actions): automatische Tests, Container-Registry-Push, Auto-Deploy auf Tag
      (`.github/workflows/` existiert bisher nicht)
- [ ] Multi-Mandanten-Fähigkeit (mehrere Vereine, Datentrennung) — bewusst zurückgestellt
      zugunsten der zweiten Instanz, s. [`ZWEITE_INSTANZ.md`](ZWEITE_INSTANZ.md)
- [ ] Externe REST-API / Webhooks für Integrationen
