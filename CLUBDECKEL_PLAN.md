# Plan: Clubdeckel — mannschaftsinterne Strichliste

> Status (2026-07-13): **Konzept, noch keine Umsetzung.** Grober Plan aus einer
> Diskussionsrunde (Vorbild: privates Repo `okram0815/Clubtresor`, eine
> PHP-Getränke-Strichliste). Zuschnitt und offene Fragen s. u.

## Kernidee

Ein **Clubdeckel** ist eine **mannschaftsinterne Strichliste** („Deckel") —
Getränke/Waren, die Mitglieder untereinander abrechnen. **Bewusst getrennt von
der Vereinskasse:** keine Verbindung zu Kassenbuch, FiBu oder Beiträgen, eigenes
schlankes Ledger.

Rollen-Logik:
- **Jedes Deckel-Mitglied** bucht seinen **eigenen Konsum** selbst (Tap-to-Buchen).
- **Nur mit Berechtigung** („Deckelwart") darf man
  1. **Transaktionen zwischen Membern** buchen (Umbuchen, Korrektur, Ausgleich) und
  2. den **Deckelinhalt** festlegen (Artikel-Katalog + Preise).

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

- **`clubdeckel`** — ein Deckel: `mannschaft_id` (i. d. R.), `name`, `aktiv`.
- **`clubdeckel_berechtigung`** — **ACL** (analog `kasse_berechtigungen`): welches
  Mitglied/welcher User ist „Deckelwart" für diesen Deckel.
- **`clubdeckel_artikel`** — der Deckelinhalt: `deckel_id`, `name`, `preis`,
  `aktiv`, ggf. Sortierung/Gruppe. Pflege nur durch Deckelwart.
- **`clubdeckel_buchung`** — das **Ledger** (ein Vorzeichen-Betrag pro Zeile, keine
  Doppik): `deckel_id`, `mitglied_id`, `artikel_id?`, `menge`, `betrag`, `typ`
  (`konsum` | `umbuchung` | `ausgleich`), `gebucht_von`, `gebucht_am`,
  Freitext/Notiz. **Saldo je Member = `SUM(betrag)`** über nicht gelöschte Zeilen.

Umbuchung zwischen zwei Membern = zwei Gegenbuchungen (oder eine Zeile mit
Ziel-Member) — Detail bei Umsetzung festlegen.

## Rechte-Logik

| Aktion                                    | Wer                                        |
|-------------------------------------------|--------------------------------------------|
| Eigenen Konsum buchen                     | jedes Deckel-Mitglied                      |
| Transaktion zwischen zwei Membern         | Wart (ACL) sowie ÜL/Betreuer implizit      |
| Artikel/Preise (Deckelinhalt) pflegen     | Wart (ACL) sowie ÜL/Betreuer implizit      |
| Teamtresor einschalten/Stammdaten pflegen | aktiver Kader-`uebungsleiter`/`betreuer`   |
| Wart ernennen (ACL vergeben)              | aktiver Kader-`uebungsleiter`/`betreuer`   |

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
- Repos: `clubdeckel_repository`, `clubdeckel_berechtigung_repository`,
  `clubdeckel_artikel_repository`, `clubdeckel_buchung_repository` — in
  `datastore.py` als `@property`.
- Kleiner Service für Saldo-Berechnung (Member-Salden, Deckel-Übersicht/Tabelle).
- Schema: `SCHEMA_VERSION` hochzählen, `_migrate_vN_to_vN+1`, DDL als geteilte
  `_DDL_*`-Konstanten aus Frisch- **und** Migrationspfad, am Ende
  `_normalize_audit_timestamps`. `PRUNE_REGISTRY` erweitern.

## Frontend (Skizze)

- Eine Seite mit in-page `q-tabs`:
  - **Tresen** — Tap-Grid der Artikel, bucht eigenen Konsum.
  - **Salden / Tabelle** — Saldo je Member (Rangliste), eigener Deckelstand.
  - **Katalog** (nur Deckelwart) — Artikel/Preise pflegen.
  - **Umbuchen** (nur Deckelwart) — Transaktion zwischen Membern, Ausgleich.
- Sichtbarkeit/Nav über geladene Deckel-Liste (analog `/api/kassen/`), Deckelwart-
  Tabs zusätzlich per ACL. Vereinsfarben (VTB-Blau `primary`, Gelb nur Akzent).

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

## Offene Fragen (Entscheidung erst bei Umsetzung)

- **Negativ-/Positiv-Saldo-Konvention** + evtl. Warnschwellen.
- **Umbuchung** genau ein oder zwei Zeilen (Modellierungsdetail).
- **Events/Push** (aus dem Vorbild) — später als Erweiterung oder ganz weglassen.

## Bezug

Ticket: **#98 „Integration Clubtresor in vtb-app"** (Verweis dort als interne
Bemerkung hinterlegt).

Vorbild: `okram0815/Clubtresor` (privat) — dortige Konzepte Artikel/Items,
Transaktions-Ledger, Salden-Tabelle, Events/Push. Für uns auf den mannschafts-
internen Kern reduziert und ins ACL-Ressourcen-Muster überführt.
