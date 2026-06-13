# Berechtigungskonzept – funktionsbasierte Rechte (Ticket #22)

> Zielbild und Stufenplan für den Umbau des Berechtigungssystems.
> Stand: Stufen A–E umgesetzt (Schema v36, funktionsbasierte Rechte, Funktions-
> und persönliche Matrix, Rollen-Ablösung, Scope-Durchsetzung am Pilot
> Personen-/Mitgliederliste). Der Umbau aus Ticket #22 ist damit abgeschlossen.

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
**Durchgesetzt wird der Scope seit Stufe E am Pilot Personen-/Mitgliederliste**
(`GET /api/personen`, `GET /api/mitglieder`): Wer `personen.read` nur scoped
besitzt, sieht dort ausschließlich Mitglieder der erlaubten Abteilungen
(`backend/core/scope.py::visible_mitglied_ids`). Andere Endpunkte (Detail-/
Schreibzugriffe) bleiben vorerst lenient – schrittweise Ausweitung möglich.
Bausteine: `has_permission_global()`, `has_permission_for_abteilung()`,
`allowed_abteilungen()` (alle in `app/models/user.py`).

### Was NICHT über dieses System läuft

- **Kassen**: objektbezogen über `kasse_berechtigungen` (pro Kasse).
- **Ticket-Bereiche**: objektbezogen über `ticket_bereich_berechtigungen`.
  Beide bleiben bewusst eigenständig.

### Bekannte, akzeptierte Punkte

- **Selbst-Eskalation über Funktions-Zuweisung**: Wer `personen.write` hat,
  kann Mitgliedern (auch sich selbst) Funktionen zuweisen und erbt deren
  Rechte. Bewusst akzeptiert; die Funktions-Matrix selbst pflegt nur der
  Admin. Gegenmaßnahme bei Bedarf: Zuweisung rechte-tragender Funktionen an
  `personen.permissions` knüpfen.
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
| **E** | Scoping-Durchsetzung, Pilot Personen-/Mitgliederliste: bei nur-scoped `personen.read` Filterung auf Mitglieder der erlaubten Abteilungen via `allowed_abteilungen()`. | ✅ umgesetzt |

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
- **Eingehängt** in `GET /api/mitglieder` und `GET /api/personen`. In der
  Personenliste werden auch reine Benutzerkonten ohne Mitglied (keine Abteilung)
  für scoped Leser verborgen.
- **Sichtbarkeit knüpft an die Abteilungs-Mitgliedschaft des Ziels**, nicht an
  die des Lesers: Ein Abteilungsleiter Fußball sieht die Fußball-Mitglieder,
  unabhängig davon, ob er selbst Fußball-Mitglied ist.
- **Kein Regress**: Bestehende Bearbeiter haben `personen.read` als globalen
  Grant (`abteilung_id` NULL) → `allowed_abteilungen` = None → sehen weiterhin
  alle. Eingeschränkt wird nur, wessen `personen.read` ausschließlich aus einer
  abteilungsgebundenen Funktion stammt.
