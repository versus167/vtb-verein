# Berechtigungskonzept – funktionsbasierte Rechte (Ticket #22)

> Zielbild und Stufenplan für den Umbau des Berechtigungssystems.
> Stand: Stufen A–E umgesetzt (Schema v36, funktionsbasierte Rechte, Funktions-
> und persönliche Matrix, Rollen-Ablösung, Scope-Durchsetzung im gesamten
> Personenbereich). Der Umbau aus Ticket #22 ist damit abgeschlossen; später
> ergänzt um die Delegationsregel (niemand vergibt, was er selbst nicht hat).

## Zielbild

Berechtigungen hängen primär an **Vereins-Funktionen** (Übungsleiter,
Abteilungsleiter, Kassenwart, …) statt an festen Rollen:

```
effektiv = (Sockel ∪ Funktionsrechte ∪ individuelle Grants) − individuelle Denies
```

- **Sockel**: festes Grundpaket im Code (`BASE_PERMISSIONS` in
  `app/models/permission.py`, aktuell `tickets.access`) – gilt für jeden
  aktiven eingeloggten User, nicht editierbar, wird nie in der DB materialisiert.
- **Funktionsrechte**: pro Katalog-Funktion (`funktion`) wird in der Tabelle
  `funktion_permission` eine Berechtigungsmenge gepflegt (gleiche Matrix wie
  beim User). Ein User erbt die Rechte aller **am heutigen Tag gültigen**
  Funktions-Zuordnungen seines verknüpften Mitglieds
  (`users ← mitglied.user_id → mitglied_funktion → funktion → funktion_permission`).
  Mehrere Funktionen kumulieren **positiv** (Union).
- **Individuelle Overrides** (`user_permissions`, Tri-State über Spalte
  `effect`): kein Eintrag = geerbt; `grant` = individuell zusätzlich;
  `deny` = individuell entzogen. **Deny schlägt alles**, auch den Sockel.
  Overrides sind **sticky**: sie überleben Funktionswechsel, bis sie explizit
  entfernt werden.
- **Admin bleibt uneingeschränkt**: `has_permission()` liefert für
  `role='admin'` immer True (unverändert).

### Automatischer Rechteverlust (Feature)

Funktions-Zuordnungen haben `von`/`bis`. Die Berechnung wertet sie **pro
Request zum heutigen Datum** aus: Endet eine Funktion, erlöschen die geerbten
Rechte automatisch am Folgetag – ohne Admin-Eingriff. Individuelle Grants
bleiben davon unberührt (sticky).

### Scoping (Abteilungs-Bezug)

Funktions-Zuordnungen sind optional abteilungsgebunden
(`mitglied_funktion.abteilung_id`, NULL = vereinsweit). Rechte aus einer
abteilungsgebundenen Zuordnung tragen den Abteilungs-Scope durch die gesamte
Berechnung (`EffectivePermissions.scoped`).

**Semantik „lenient" vs. „strict":** Die globale Prüfung `has_permission()`
ist weiterhin lenient – auch ein nur abteilungsgebunden geerbtes Recht erfüllt
sie (kein Sicherheitsverlust, Funktionsrechte sind bewusste Admin-Vergabe).
**Durchgesetzt wird der Scope seit Stufe E im gesamten Personenbereich** – erst
nur auf den Listen (`GET /api/personen`, `GET /api/mitglieder`), seit dem Ausbau
auch auf **jedem ID-adressierten Endpunkt** der fünf Personen-Router (Personen,
Mitglieder, Kontakte, Abteilungs- und Funktionszuordnungen). Wer `personen.read`
nur scoped besitzt, sieht ausschließlich Mitglieder der erlaubten Abteilungen –
und kommt an die übrigen auch nicht mehr über deren ID heran. Ohne diesen zweiten
Schritt wäre die Listenfilterung bloß Kosmetik gewesen: Die ausgeblendeten
Datensätze blieben einzeln abrufbar und änderbar, samt Änderungshistorie mit
Adresse, Geburtsdatum und Bankverbindung.
Bausteine: `has_permission_global()`, `has_permission_for_abteilung()`,
`allowed_abteilungen()` (alle in `app/models/user.py`).

### Delegationsregel: Niemand vergibt, was er selbst nicht hat

Vier Türen verändern die Rechte eines anderen Users. Zwei sind seit jeher
Admin-only — die **Funktions-Berechtigungsmatrix**
(`PUT /funktionen/{id}/permissions`) und die **Admin-Rolle**
(`authorize_role_assignment`). Die beiden übrigen bewacht
`backend/core/authz.py::authorize_permission_delegation`:

- **Individuelle Grants** (`PUT /users/{id}/permissions`, Gate
  `personen.permissions`): Ein Grant wirkt vereinsweit, also muss der Handelnde
  das Recht **vereinsweit** besitzen. Geprüft wird nur, was *hinzukommt* — sonst
  wäre ein User mit einem höheren Bestands-Grant für jeden Bearbeiter
  unspeicherbar, auch bei einer ganz anderen Änderung. **Denies** fallen nicht
  unter die Regel: Wer Rechte entzieht, verschafft sich keine.
- **Funktionszuordnung** (`POST/PUT /mitglieder/{id}/funktionen`, Gate
  `personen.write`): Eine Funktion reicht ihre Rechte an den Träger weiter,
  vergeben darf sie deshalb nur, wer sie selbst hat. Bei abteilungsgebundener
  Zuordnung genügt das Recht für **diese** Abteilung, bei vereinsweiter braucht
  es das vereinsweite.

Zwei Eigenschaften fallen dabei von selbst ab: **Admins** bestehen die Prüfung
ohne Sonderfall (sie haben jedes Recht), und **Funktionen ohne hinterlegte
Rechte** bleiben frei zuordenbar (leere Menge). Rein beschreibende Funktionen —
Vorstand, Kampfrichter, Platzwart — kosten also nichts.

Der Preis: Wer Rechte verteilen soll, die er selbst nicht braucht, muss sie
trotzdem haben oder Admin sein. Das ist bewusst so gewählt — die Alternative
wäre eine Rolle, die unbegrenzt Rechte erzeugt, ohne selbst welche zu tragen.

### Was NICHT über dieses System läuft

- **Kassen**: objektbezogen über `kasse_berechtigungen` (pro Kasse).
- **Termine**: der Regelfall läuft über den Kader (`mitglied_mannschaft`) –
  Betreuer/ÜL verwalten die Termine *ihrer* Mannschaft, aktive Kader-Mitglieder
  lesen sie. Der globale Key `termine.verwalten` ist die vereinsweite Ausnahme
  (alle Mannschaften, dazu der DFBnet-Spielplan-Import) und steht seit
  v2026.08.03.159 als eigene Gruppe „Termine" in der Matrix; davor war er nur
  per SQL vergebbar. In derselben Gruppe liegt `spielstaetten.verwalten`
  (Schema v86): Die Spielstätten-Pflege hing vorher an `system.config` und kam
  damit nur zusammen mit Datenbereinigung und Mitglieder-Import — für einen
  Platzwart deutlich zu viel. `system.config` bleibt als Obermenge zulässig,
  damit beim Aufteilen niemand Zugriff verliert. Ebenfalls dort:
  `termine.gaeste_vereinsweit` (Schema v102) — es erlaubt, Gäste über die
  Abteilung der Mannschaft hinaus einzuladen, **nicht** Termine zu verwalten.
  Wer den Termin verwalten darf, entscheidet weiterhin die Kader-ACL bzw.
  `termine.verwalten`.
- **Ticket-Bereiche**: objektbezogen über `ticket_bereich_berechtigungen`.
  Beide bleiben bewusst eigenständig.
  Daraus abgeleitet der Aufgaben-Hinweis (#133,
  `TicketService.anzahl_zustaendig`): zuständig ist der konkret Zugewiesene –
  und **nur solange niemand zugewiesen ist** jeder Bereichs-Bearbeiter/
  -Schließer. Ein Admin darf zwar überall, bekommt aber keine
  Bereichs-Berechtigung und zählt darum nur seine direkten Zuweisungen.

### Bekannte, akzeptierte Punkte

- **Selbst-Eskalation über Funktions-Zuweisung** (behoben, s. Delegationsregel
  oben): War lange bewusst akzeptiert — wer `personen.write` hatte, konnte
  Mitgliedern und sich selbst Funktionen zuweisen und deren Rechte erben. Seit
  `authorize_permission_delegation` geht das nur noch für Rechte, die der
  Handelnde selbst besitzt; Funktionen ohne Rechte bleiben frei zuordenbar.
- **Admin-Vergabe** (umgesetzt, Stufe D): Das Admin-Flag darf nur noch von
  Admins gesetzt oder entzogen werden (`backend/core/authz.py::authorize_role_assignment`,
  eingehängt in alle User-Create/Update-Endpoints). Reine Daten-Änderungen an
  einem Account ohne Flag-Wechsel bleiben für `personen.write` erlaubt.
  Letzter-Admin-Schutz (`user_service`) bleibt.
- **Deny-Stickyness-Falle**: Ein vergessenes Deny blockiert auch später neu
  geerbte Funktionsrechte. Der persönliche Berechtigungsscreen (Stufe C)
  zeigt Denies deshalb immer an, auch ohne aktuell Geerbtes dagegen.
- **Kein FK** `mitglied_funktion.funktion → funktion.key` möglich (partieller
  Unique-Index). Migration v35 loggt verwaiste Keys als WARN; sauberer Fix
  wäre die Umstellung auf `funktion_id` (eigenes Refactoring, s. TODO).
- **Key-Reuse**: Wird eine Katalog-Funktion gelöscht und ihr Key später neu
  angelegt, entsteht eine neue `funktion.id` → der neue Eintrag startet ohne
  Rechte (keine stille Wiederbelebung alter Berechtigungen).

## Stufenplan

| Stufe | Inhalt | Status |
|-------|--------|--------|
| **A** | Datenmodell (v35: `funktion_permission`, `user_permissions.effect/abteilung_id`) + effektive Berechnung in `PermissionRepository.get_effective_permissions` + Sockel. Verhalten feature-gleich; einzige Änderung: alle User haben `tickets.access`. | ✅ umgesetzt |
| **B** | Funktions-Matrix-UI: GET/PUT `/api/funktionen/{id}/permissions` (PUT hart Admin), Matrix-Komponente aus UserPermissionsPage extrahieren, Dialog im Einstellungen-Tab „Funktionen". | ✅ umgesetzt |
| **C** | Persönlicher Berechtigungsscreen mit Herkunftsanzeige („geerbt von Funktion X (Abteilung Y)" / „Sockel") und Tri-State-Bedienung (Grant/Deny); PUT-Format `{grants, denies}`. | ✅ umgesetzt |
| **D** | Rollen-Ablösung (v36): nur noch `admin`/`mitglied`; `defaults_for_role` entfällt (Bestand bleibt als Grants erhalten – Permissions wurden schon immer beim Anlegen materialisiert, es gibt keinen Rollen-Fallback zur Laufzeit). Harte `role=='admin'`-Checks ersetzt: `funktionen.verwalten`, `kassen.verwalten`, Ticket-Bereiche/Kategorien → `tickets.bereiche_verwalten`, Fremdkommentar-Delete → `tickets.delete`. Admin-Flag-Vergabe nur durch Admins. | ✅ umgesetzt |
| **E** | Scoping-Durchsetzung: erst Pilot Personen-/Mitgliederliste (Filterung via `allowed_abteilungen()`), dann Ausbau auf **alle ID-adressierten Endpunkte** der fünf Personen-Router (`require_mitglied`/`require_person`/`require_abteilung`) — ohne den zweiten Schritt war die Listenfilterung über die ID umgehbar. | ✅ umgesetzt |

## Technische Referenz (Stufe A)

- **Berechnung**: `app/models/permission.py::compute_effective_permissions`
  (pure, DB-frei, getestet in `vtb_verein/tests/test_effective_permissions.py`);
  DB-Anbindung in `app/db/permission_repository.py::get_effective_permissions`
  (2 konstante Queries, +1 Query/Request gegenüber vorher).
- **Einhängepunkt**: `UserRepository._load_permissions` befüllt bei jedem
  User-Load `user.effective` + `user.permissions` (= `effective.keys()`,
  lenient). Dadurch konsistent in Login, `/me`, Magic-Link und CurrentUser –
  Matrix-/Funktions-Änderungen wirken ab dem nächsten Request.
- **Alt-API stabil**: `get_permissions_for_user` liefert nur noch
  `effect='grant'`-Zeilen (= bisherige Semantik der UserPermissionsPage);
  Reaktivierung setzt explizit `effect='grant'`.
- **Migration**: v35 in `app/db/database.py` (`_migrate_v34_to_v35`),
  Frischaufbau-Pfad synchron (`_create_tables`, Trigger, Indizes).

## Technische Referenz (Stufe D)

- **Migration v36** (`_migrate_v35_to_v36`): `UPDATE users SET role='mitglied'
  WHERE role <> 'admin'`, CHECK-Constraint auf `('admin','mitglied')` reduziert.
  `users_history` bleibt unangetastet (immutable Audit). Verlustfrei, weil
  Rollen-Defaults seit jeher beim Anlegen in `user_permissions` materialisiert
  wurden – diese bleiben als Grants erhalten. `defaults_for_role` entfernt;
  `user_service.create` materialisiert keine Defaults mehr.
- **Ersetzte Hard-Checks** (Admin → Permission; Admin behält Zugriff, da
  `has_permission` für `role='admin'` immer True liefert):
  - Funktionskatalog (`backend/api/funktionen.py`): `funktionen.verwalten`.
    Die Funktions-Berechtigungsmatrix (PUT `…/permissions`) bleibt hart Admin-only.
  - Kassen (`backend/api/kassenbuch.py`): `kassen.verwalten` – sowohl für
    Kassen-/Berechtigungsverwaltung als auch als Bypass der per-Kasse-ACL.
    Die per-Kasse-`kasse_berechtigungen` bleiben als Insel bestehen.
  - Tickets (`backend/api/tickets.py`): Bereiche/Kategorien →
    `tickets.bereiche_verwalten`, fremde Kommentare löschen → `tickets.delete`.
    Der per-Bereich-Admin-Bypass (`ticket_bereich_berechtigungen`) bleibt
    role-basiert (Insel).
- **Admin-Flag**: `backend/core/authz.py::authorize_role_assignment` normalisiert
  die Rolle und erlaubt das Setzen/Entziehen von `admin` nur Admins (Flag-Wechsel-
  Prüfung). Eingehängt in `users.py` (POST/PUT) und `personen.py`
  (create_person, update_person_user, create_nutzer_fuer_mitglied).
- **Frontend**: Rollen-Auswahl → Administrator-Schalter (nur für Admins sichtbar,
  `PersonenPage.vue`); Nav-/Route-Gates `kassenverwaltung` → `kassen.verwalten`,
  `einstellungen` → `funktionen.verwalten`; `KassenbuchDetailPage` nutzt
  `kassen.verwalten` statt `role==='admin'`.

## Technische Referenz (Stufe E)

- **Scope-Helper** `backend/core/scope.py::visible_mitglied_ids(user, db, perm)`:
  liest `user.allowed_abteilungen(perm)` → `None` (vereinsweit/Admin → keine
  Einschränkung) oder eine Abteilungsmenge; im scoped Fall eine Query auf
  `mitglied_abteilung` (aktive Zuordnungen) → Menge sichtbarer `mitglied_id`s.
- **Eingehängt** in `GET /api/mitglieder`, `GET /api/personen` und den Papierkorb
  `GET /api/personen/deleted`. In der Personenliste werden auch reine
  Benutzerkonten ohne Mitglied (keine Abteilung) für scoped Leser verborgen.
- **Wächter für ID-adressierte Endpunkte** (gleiche Datei):
  `require_mitglied(user, db, mitglied_id, perm)` und `require_person(…, user_id, …)`
  werfen 403, wenn das Ziel außerhalb des Scope liegt; `darf_mitglied` ist die
  Prädikat-Variante mit gezielter EXISTS-Abfrage statt voller ID-Menge. Jeder
  ID-Endpunkt der fünf Personen-Router trägt einen davon, jeweils mit *dem*
  Recht, das er ohnehin verlangt (read/write/delete/permissions) — ein Test
  wacht darüber, dass kein neuer Endpunkt ohne Prüfung dazukommt.
- **Zuordnungen prüfen die Abteilung, nicht das Mitglied**
  (`require_abteilung`, eingehängt in `POST/PUT/DELETE
  /mitglieder/{id}/abteilungen`): Ein Neuzugang hängt noch an keiner Abteilung
  und wäre sonst für jeden Abteilungsleiter unerreichbar — auch für den, der ihn
  aufnehmen soll. Umgekehrt verhindert die Prüfung das Verschieben in fremde
  Abteilungen.
- **Der Soft-Delete ändert den Scope nicht**: Abteilungs-Zuordnungen überleben
  das Löschen (s. `PersonService.delete_person`), deshalb greift derselbe Filter
  auch für Papierkorb und Wiederherstellen.
- **Sichtbarkeit knüpft an die Abteilungs-Mitgliedschaft des Ziels**, nicht an
  die des Lesers: Ein Abteilungsleiter Fußball sieht die Fußball-Mitglieder,
  unabhängig davon, ob er selbst Fußball-Mitglied ist.
- **Kein Regress**: Bestehende Bearbeiter haben `personen.read` als globalen
  Grant (`abteilung_id` NULL) → `allowed_abteilungen` = None → sehen weiterhin
  alle. Eingeschränkt wird nur, wessen `personen.read` ausschließlich aus einer
  abteilungsgebundenen Funktion stammt.

## Rechnungen einreichen & freigeben (Schema v78)

Drei Keys, zweiter davon **strict scoped** durchgesetzt:

| Key | Wirkung |
|---|---|
| `rechnungen.einreichen` | eigene Rechnungen anlegen, Belege hochladen, einreichen |
| `rechnungen.freigeben` | eingereichte Rechnungen freigeben/ablehnen – **nur für die Abteilungen, aus denen das Recht stammt** |
| `rechnungen.verwalten` | Geschäftsstelle: alle Rechnungen sehen, Kategorien pflegen, exportieren, Vereinsrechnungen (ohne Abteilung) freigeben, **Erstattung an ein anderes Mitglied** erfassen |

- Seed: `rechnungen.einreichen` + `rechnungen.freigeben` hängen an der Funktion
  `abteilungsleiter` (`_RECHNUNG_FUNKTION_PERMISSIONS` in `database.py`, aus
  Frischaufbau **und** Migration v77→v78 aufgerufen). Wer sonst einreichen darf,
  bekommt den Key individuell.
- Durchsetzung wie bei den ÜL-Stunden über `has_permission_for_abteilung()`:
  `backend/api/rechnungen.py::_darf_freigeben`. Die Freigabe-Liste filtert über
  `allowed_abteilungen('rechnungen.freigeben')` (`None` = alle).
- Eine Rechnung **ohne** Abteilung (`abteilung_id IS NULL`) kann nur mit
  `rechnungen.verwalten` freigegeben werden – ein Abteilungs-Scope greift dort
  per Definition nicht.
- Der Ersteller sieht seine eigenen Rechnungen immer, unabhängig vom Scope.
- Erstattet wird an den Einreicher. Ein **anderes** Mitglied als Empfänger nimmt
  `RechnungService._aufloesen_empfaenger_mitglied` nur von `rechnungen.verwalten`
  an – die Geschäftsstelle erfasst Belege auch für Leute ohne App-Zugang; für
  alle anderen wäre es der kurze Weg zu einer fremden Bankverbindung. Für
  Verwalter wird der Empfänger **nicht** vorbelegt (sonst zahlte ein übersehener
  Vorschlag an den Erfasser); die Auswahlliste liefert
  `GET /api/rechnungen/empfaenger-mitglieder`.
