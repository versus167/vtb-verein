# Plan: Trainings- & Spielbeteiligungsplanung (SpielerPlus-ähnlich)

> Status (2026-07-13): **Konzept, noch keine Umsetzung.** Grober Plan aus einer
> Diskussionsrunde; Zuschnitt und offene Fragen s. u. Prio niedrig (Ticket im
> Bereich VTB-App).

## Kernidee

Terminplanung auf **Mannschaftsebene** (Training, Spiele, Sonstiges) mit
Zu-/Absagen der Spieler und einer Trainer-Sicht über die Beteiligung — der Kern
dessen, was SpielerPlus leistet. Spielansetzungen kommen per **Import aus dem
DFBnet-Vereinsspielplan** (CSV) in die App; Verlegungen werden beim erneuten
Import als Diff erkannt.

## Vorhandene Bausteine (werden wiederverwendet)

- **Mannschaften + Kader** (`backend/api/mannschaften.py`): Zuordnungen mit
  Rollen `spieler`/`trainer`/`uebungsleiter`/`betreuer` und von/bis-Zeiträumen.
- **Mitglied ↔ User** (`Mitglied.user_id`) + **Magic-Link-Login** für
  niedrigschwelligen Spieler-Zugang.
- **Benachrichtigungen** über E-Mail/Matrix (`notification_service`,
  `matrix_service`, `preferred_contact`).
- **Import-Muster** (`imports.py` / `spg_import_service.py`): Dry-Run,
  strukturiertes ImportResult, Matching statt Auto-Anlage.
- Etablierte Muster: Soft-Delete + History + Prune, Permission-Keys,
  ACL-Scoping (Kader = ACL).

## Datenmodell (Skizze)

- **`termine`** — `mannschaft_id`, `typ` (`training`|`spiel`|`sonstiges`),
  Start/Ende, Ort, Treffpunkt(-zeit), bei Spielen Gegner + Heim/Auswärts,
  `extern_ref` (DFBnet-Spielkennung fürs Import-Matching), `serie_id`,
  `status` (geplant/abgesagt). Soft-Delete + History + `PRUNE_REGISTRY`.
- **`termin_serien`** — Wochentag/Uhrzeit/Ort/Zeitraum für wiederkehrendes
  Training. Instanzen werden **materialisiert** (rollierend ~6–8 Wochen im
  Voraus), nicht on-the-fly berechnet — Zu-/Absagen hängen an konkreten
  Instanzen, Einzeltermine können abweichen (Halle belegt, Feiertag).
- **`termin_teilnahmen`** — `termin_id`, `mitglied_id`, `status`
  (`zusage`|`absage`|`unsicher`|`offen`), Kommentar/Absagegrund, geändert
  von/um. „Geändert von" ist wichtig: Trainer/Betreuer tragen stellvertretend
  ein (Jugend, Spieler ohne Account).

## Berechtigungen

Kader-Zugehörigkeit ist die ACL (analog `kasse_berechtigungen`/
`tresor_freigabe`): Spieler sehen/beantworten Termine ihrer Mannschaften; wer
im Kader `trainer`/`betreuer` ist, verwaltet deren Termine. Globale Keys
(z. B. `termine.verwalten`) nur für die übergreifende Verwaltung.

## Frontend

- **„Meine Termine"**-Sicht für Spieler: nächste Termine, Ein-Klick-Zusage/
  -Absage (der SpielerPlus-Kern).
- **Trainer-Sicht** pro Mannschaft: Teilnahme-Matrix (zugesagt/abgesagt/offen),
  stellvertretendes Eintragen. Als q-tabs im Mannschaften-Bereich.
- Erinnerungen über den Notification-Stack („noch nicht geantwortet, Spiel in
  3 Tagen"; Benachrichtigung bei Verlegung/Absage).

## DFBnet-/fussball.de-Übernahme

Kein offizielles öffentliches API. Optionen, aufsteigend nach Aufwand/Risiko:

1. **DFBnet-Vereinsspielplan-Export (CSV)** — *empfohlener Start.* SpielPLUS →
   Ergebnismeldung → Vereinsspielplan liefert **alle Spiele aller Mannschaften
   des Vereins** für einen Zeitraum als `spielplan.csv` (Bildschirmansicht max.
   3 Monate; ob der CSV-Export die ganze Saison kann, praktisch prüfen —
   rollierender 2–3-Monats-Export ist fürs Aktualisieren ohnehin das
   realistische Muster). Import matcht über `extern_ref`, zeigt Verlegungen als
   Diff. Mapping DFBnet-Mannschaftsname → Mannschaft einmalig bestätigen,
   danach automatisch; Unbekanntes wird übersprungen und gelistet (wie
   SPG-Import).
2. **Unofficial APIs/Scraper** für fussball.de (api-fussball.de, selbst
   gehostete Scraper wie Zetabytes/fussball_de_api) für automatischen
   nächtlichen Sync pro Mannschaft. Risiken: TOS, Bruchgefahr bei Seitenumbau;
   Ergebnisse sind font-obfuskiert (Anstoßzeiten/Termine nicht — und die
   brauchen wir primär).
3. fussball.de-**Widgets** sind reine Anzeige-Embeds — keine Datenquelle.

Import-Service mit **normalisiertem Spiel-Datensatz** bauen, damit die Quelle
(CSV heute, Scraper später) austauschbar bleibt.

## Etappen

1. **Termine + Teilnahme**: Tabellen, Migration, API, Trainer-Ansicht.
2. **Spieler-Sicht + Benachrichtigungen**: Meine Termine, Zu-/Absage,
   Erinnerungen. Ab hier SpielerPlus-Charakter.
3. **Spielplan-Import (DFBnet-CSV)** mit Verlegungs-Diff.
4. Optional: automatischer fussball.de-Sync, Aufgaben (Fahrdienst,
   Trikotwäsche), Aufstellungen.

## Offene Fragen

- **Jugend/Eltern:** Reicht stellvertretendes Eintragen durch Trainer, oder
  Eltern-Zugang über die Kontakt-E-Mail des Mitglieds? (Größte Auswirkung aufs
  Konzept.)
- **Antwortfristen/Strafenkatalog** (SpielerPlus-Features): gewünscht oder
  reicht die Erinnerung?
- **Gastspieler/Probetraining:** nur Kader, oder ad hoc mannschaftsfremde
  Mitglieder einladbar?
- **Kritische Masse an Spieler-Logins:** ohne Accounts bleibt Stufe 2
  wirkungslos — ggf. Onboarding-Aktion (Magic-Link-Einladung an den Kader)
  einplanen.
