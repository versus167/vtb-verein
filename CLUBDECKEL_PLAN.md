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

| Aktion                                   | Wer                                   |
|------------------------------------------|---------------------------------------|
| Eigenen Konsum buchen                    | jedes Deckel-Mitglied                 |
| Transaktion zwischen zwei Membern        | nur ACL-„Deckelwart" des Deckels      |
| Artikel/Preise (Deckelinhalt) pflegen    | nur ACL-„Deckelwart" des Deckels      |
| Deckel anlegen/verwalten                 | global `clubdeckel.verwalten`         |

Neue Permission-Keys nur fürs Verwalten global (`clubdeckel.verwalten`); die
eigentliche Nutzung läuft über Mannschafts-Zugehörigkeit + Deckel-ACL, **nicht**
über globale Permissions.

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

## Offene Fragen (vor Umsetzung klären)

- **Ausgleich** („Deckel bezahlt"): rein als Gegenbuchung im Ledger, oder optional
  doch als *Brücke* in eine Kasse buchbar? (Default: nur Ledger, entkoppelt.)
- **Negativ-/Positiv-Saldo-Konvention** + evtl. Warnschwellen.
- **Umbuchung** genau ein oder zwei Zeilen (Modellierungsdetail).
- **Events/Push** (aus dem Vorbild) — später als Erweiterung oder ganz weglassen.
- Mehrere Deckel je Mannschaft nötig, oder 1:1 Mannschaft↔Deckel?

## Bezug

Vorbild: `okram0815/Clubtresor` (privat) — dortige Konzepte Artikel/Items,
Transaktions-Ledger, Salden-Tabelle, Events/Push. Für uns auf den mannschafts-
internen Kern reduziert und ins ACL-Ressourcen-Muster überführt.
