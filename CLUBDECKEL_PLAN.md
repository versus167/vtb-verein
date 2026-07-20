# Plan: Teamtresor (Clubdeckel) — mannschaftsinterne Strichliste

> Status (2026-07-20): **Umgesetzt auf Branch `feature/teamtresor`** (Schema v75,
> Fachmodell nach Abgleich mit dem Original korrigiert, s. „Buchungsmodell").
> Vorbild: privates Repo `okram0815/Clubtresor` (PHP-Getränke-Strichliste).

## Kernidee

Ein **Clubdeckel** ist eine **mannschaftsinterne Strichliste** („Deckel") —
Getränke/Waren, die Mitglieder untereinander abrechnen. **Bewusst getrennt von
der Vereinskasse:** keine Verbindung zu Kassenbuch, FiBu oder Beiträgen, eigenes
schlankes Ledger.

Rollen-Logik:
- **Jedes Deckel-Mitglied** bucht seinen **eigenen Konsum** selbst (Tap-to-Buchen).
- **Nur mit Berechtigung** („Wart") darf man
  1. **Zahlungen und Einkäufe** buchen (Geld wurde real übergeben / Team kauft
     vom Mitglied) und
  2. den **Deckelinhalt** festlegen (Gruppen + Artikel + Preise).

Das Recht ist **ressourcen-genau pro Deckel**, kein globales Recht — exakt das
ACL-Muster von **Kassen** (`kasse_berechtigungen`) und **Tresor**
(`tresor_freigabe`).

## Vorhandene Bausteine (werden wiederverwendet)

- **Mannschaften + Kader** (`backend/api/mannschaften.py`, `mitglied_mannschaft`)
  — der Deckel hängt an einer Mannschaft; die Mitgliedermenge kommt von dort.
- **ACL-Ressourcen-Muster** (Kassen/Tresor): eigene Berechtigungstabelle je
  Ressource, Frontend lädt eine Liste zur Sichtbarkeitssteuerung.
- Etablierte Muster: **Soft-Delete + History + Prune**, **Permission-Keys**
  (`permission.py` + Admin-Seed + Migration), Fresh == Migriert.
- **Web-Push** (#96) — falls Event-/Erinnerungs-Benachrichtigungen später dazukommen.
- Mitglieder als „Konten" (`mitglieder`).

## Datenmodell (Skizze)

Alle Tabellen mit Soft-Delete (`deleted_at`/`deleted_by`, `version`) + Audit-Trigger
in `*_history` **und Eintrag ins `PRUNE_REGISTRY`** (Reihenfolge Kinder-vor-Eltern).

- **`clubdeckel`** — ein Deckel: `mannschaft_id` (UNIQUE auf aktive Zeilen),
  `name`, `aktiv`; **Stammdaten**: `beitrag` (Monatspauschale) + `beitrag_ab`,
  `zahlungsempfaenger_mitglied_id` und Zahlwege `zahlweg_iban`/`_wero`/`_paypal`.
- **`clubdeckel_berechtigung`** — **Wart-ACL** (mitglied-basiert wie der Kader).
- **`clubdeckel_gruppe`** — Artikel-Gruppe („Getränke"/„Essen") mit **Verkäufer**:
  Team (`verkaeufer_mitglied_id NULL`) oder ein Mitglied (verkauft z. B. die
  Roster selbst).
- **`clubdeckel_artikel`** — der Deckelinhalt: `gruppe_id?`, `name`, `preis`,
  `aktiv`, `sortierung`. Pflege nur durch Wart.
- **`clubdeckel_beitrag_befreiung`** — vom Monatsbeitrag befreite Mitglieder.
- **`clubdeckel_buchung`** — das **Ledger** (ein Vorzeichen-Betrag pro Zeile,
  keine Doppik). **Saldo je Mitglied = `SUM(betrag)`**, **Team-Saldo = −Σ aller
  Mitgliedssalden** (keine eigene Team-Buchhaltung).

## Buchungsmodell (korrigiert nach Abgleich mit dem Original, 19./20.07.2026)

| Typ       | Vorgang                                   | Wirkung                                     |
|-----------|-------------------------------------------|---------------------------------------------|
| `konsum`  | Mitglied kauft Artikel                    | Käufer −Betrag (Preis-Snapshot). Verkauft die Gruppe über ein **Mitglied**, entsteht die Gegenzeile `verkauf` (+Betrag) beim Verkäufer — Nullsummen-Paar via `paar_ref`, Team unberührt. |
| `verkauf` | Verkäufer-Gegenzeile (nie allein)         | Verkäufer +Betrag                           |
| `einkauf` | Team kauft vom Mitglied (Kasten geliefert)| Mitglied +Betrag (Team −)                   |
| `zahlung` | Mitglied zahlt an Mitglied (bar/PayPal/…) | Zahler +, Empfänger − (Nullsummen-Paar via `paar_ref`); deckt Einzahlung beim Wart wie Direktzahlung ab |
| `beitrag` | Mannschaftsbeitrag (Monatspauschale)      | Mitglied −Betrag, `beitrag_monat` 'YYYY-MM' |

- **Beitragslauf automatisch** (lazy beim Zugriff, Muster „rollierend
  materialisieren" wie Terminserien): beitragspflichtig für Monat M ist, wer am
  Monatsersten aktiv im Kader steht und nicht befreit ist; ein Monat mit
  vorhandener Beitragszeile — **auch storniert** — gilt als erledigt
  (Storno = „erlassen").
- **Storno** einer Paar-Zeile löscht immer das ganze Paar; eigenen Konsum darf
  das Mitglied selbst stornieren (Fehltipp), alles andere der Wart.
- **Zahlungsempfänger + Zahlwege** werden am Tresen als „Zahlung an …"-Karte
  angezeigt (WERO-Link, IBAN kopieren, PayPal.me) — gebucht gilt erst, wenn der
  Wart die Zahlung erfasst.

## Rechte-Logik

| Aktion                                     | Wer                                        |
|--------------------------------------------|--------------------------------------------|
| Eigenen Konsum buchen/stornieren           | jedes Deckel-Mitglied                      |
| Zahlungen/Einkäufe buchen, Storno gesamt   | Wart (ACL) sowie ÜL/Betreuer implizit      |
| Gruppen/Artikel/Preise pflegen             | Wart (ACL) sowie ÜL/Betreuer implizit      |
| Einschalten/Stammdaten (Beitrag, Zahlwege) | aktiver Kader-`uebungsleiter`/`betreuer`   |
| Warte ernennen, Beitragsbefreiungen        | aktiver Kader-`uebungsleiter`/`betreuer`   |

**Kein neuer globaler Permission-Key** — die Verantwortung kommt vollständig aus
dem Kader (`mitglied_mannschaft`, Rollen `uebungsleiter`/`betreuer`, von/bis
aktiv), darunter die Wart-ACL, darunter die Kader-Mitgliedschaft. Das ist das
„Kader = ACL"-Muster aus dem Spielbetrieb-Plan (#95). **Der Vorstand hat keinen
Einblick** in Teamtresore (bewusst entschieden — kein Übersichts-/Lese-Key).
Einzige Ausnahme bleibt der app-weite Admin-Durchgriff (`role == 'admin'` hat
technisch immer alles) als Notfall-Fallback, z. B. wenn ein Team keinen ÜL im
Kader gepflegt hat; in der UI wird das nicht beworben.

## Backend (Skizze)

- Router `backend/api/clubdeckel.py`, in `main.py` mit `prefix="/api"` registriert.
- Repos: `clubdeckel_repository` (inkl. Kader-Rechteableitung, CTE aus dem
  Termine-Muster kopiert), `clubdeckel_berechtigung_repository`,
  `clubdeckel_gruppe_repository`, `clubdeckel_artikel_repository`,
  `clubdeckel_befreiung_repository`, `clubdeckel_buchung_repository` (inkl.
  Salden + Beitragslauf) — in `datastore.py` als `@property`.
- Schema v75: DDL als geteilte `_DDL_*`-Konstanten aus Frisch- **und**
  Migrationspfad, am Ende `_normalize_audit_timestamps`; `PRUNE_REGISTRY` um die
  fünf Entities plus ChildRefs bei `mannschaft` und `mitglied` erweitert.

## Frontend (Skizze)

- Eine Seite (`TeamtresorPage.vue`) mit in-page `q-tabs`:
  - **Tresen** — Tap-Grid der Artikel nach Gruppen (Tap bucht 1×, Notify mit
    Rückgängig), eigener Deckelstand + Team-Saldo, „Zahlung an …"-Karte mit den
    Zahlwegen, eigene letzte Buchungen mit Storno.
  - **Salden** — Team-Saldo + Rangliste je Mitglied.
  - **Katalog** (ab Wart) — Gruppen (inkl. Verkäufer) und Artikel pflegen.
  - **Verwalten** (ab Wart) — Zahlung/Einkauf buchen, alle Buchungen mit Storno;
    nur ÜL/Betreuer: Warte, Beitragsbefreiungen, Stammdaten, Ausschalten.
- Sichtbarkeit/Nav über die geladene Team-Liste (`/api/clubdeckel/teams`,
  analog `/api/kassen/`). Vereinsfarben (VTB-Blau `primary`, Gelb nur Akzent).

## Entschieden

- **Ausgleich** („Deckel bezahlt"): **nur innerhalb des Teamdeckels** — reine
  Gegenbuchung im Ledger, keine Brücke in eine Kasse (Volker, 19.07.2026).
- **Name** (Volker, 19.07.2026): Im **UI heißt das Feature „Teamtresor"** — das
  Team kennt den Begriff vom Vorbild Clubtresor. Im **Code/Schema bleibt durchgängig
  `clubdeckel_*`** (Tabellen, Permission-Keys, Router), damit keine Verwechslung mit
  dem bestehenden Passwort-/Kontakte-Tresor (`tresor_*`) entsteht. Zur Abgrenzung
  bekommt der bestehende Tresor-Bereich bei der Umsetzung einen präzisierenden
  Untertitel (z. B. „Passwörter & wichtige Kontakte"), und dessen Button
  „Neuer Tresor" wird umbenannt (z. B. „Neuer Container").
- **Berechtigungen** (Volker, 19.07.2026): Der Teamtresor ist eine **teaminterne
  Entscheidung** — einschalten und verwalten darf, wer im Kader der Mannschaft
  aktiv `uebungsleiter`/`betreuer` ist; diese ernennen auch die Warte (ACL, auch
  Spieler möglich). **Kein globaler Permission-Key, kein Vorstands-Einblick.**
  Details in „Rechte-Logik".
- **Genau ein Teamtresor pro Mannschaft** (Volker, 19.07.2026) — 1:1-Beziehung,
  `mannschaft_id` in `clubdeckel` entsprechend UNIQUE (auf nicht gelöschte
  Zeilen bezogen).
- **Fachmodell aus dem Original übernommen** (Volker, 19./20.07.2026): kein
  frei erfundener „Ausgleich" — die Buchungsarten sind konsum/verkauf/einkauf/
  zahlung/beitrag (Tabelle oben); Team-Saldo ist immer die Gegensumme der
  Mitgliedssalden. Saldo-Konvention: negativ = schuldet.
- **Mannschaftsbeitrag: Automatik + Ausnahmen** (Volker, 19.07.2026) —
  monatliche Pauschale aus den Stammdaten, automatisch gebucht, Befreiungen je
  Mitglied durch ÜL/Betreuer.
- **Zahlungen/Einkäufe bucht nur der Wart** (Volker, 19.07.2026) — wie an der
  Theke: Geld wird real übergeben, der Wart quittiert per Buchung.
- **Zahlwege des Zahlungsempfängers** (Volker, 19.07.2026): IBAN (kopieren),
  WERO-Link, PayPal.me-Link — wie im Original.
- **Gruppen mit Verkäufer** (Volker, 20.07.2026): Artikel hängen in Gruppen;
  Verkäufer je Gruppe ist das Team oder ein Mitglied (z. B. Roster) — beim
  Konsum entsteht dann ein Nullsummen-Paar Käufer/Verkäufer.

## Offene Fragen (Entscheidung erst bei Bedarf)

- **Warnschwellen** bei hohem Negativ-Saldo (Anzeige/Benachrichtigung).
- **Events/Push** (aus dem Vorbild) — später als Erweiterung oder ganz weglassen.

## Bezug

Ticket: **#98 „Integration Clubtresor in vtb-app"** (Verweis dort als interne
Bemerkung hinterlegt).

Vorbild: `okram0815/Clubtresor` (privat) — dortige Konzepte Artikel/Items,
Transaktions-Ledger, Salden-Tabelle, Events/Push. Für uns auf den mannschafts-
internen Kern reduziert und ins ACL-Ressourcen-Muster überführt.
