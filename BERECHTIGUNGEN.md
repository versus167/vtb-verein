# Berechtigungskonzept – funktionsbasierte Rechte (Ticket #22)

> Zielbild und Stufenplan für den Umbau des Berechtigungssystems.
> Stand: Stufe A umgesetzt (Datenmodell + Berechnung, Schema v35).

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

**Übergangs-Semantik „lenient"** (bewusste Entscheidung): Bis die
Endpoint-Filterung umgesetzt ist (Stufe E), erfüllt auch ein nur
abteilungsgebunden geerbtes Recht die globale Prüfung `has_permission()` –
es wirkt also übergangsweise vereinsweit. Kein Sicherheitsverlust gegenüber
vorher (Funktionsrechte sind eine bewusste Admin-Vergabe), muss aber in der
Funktions-Matrix-UI als Hinweis stehen. Für die spätere Durchsetzung stehen
bereit: `has_permission_global()`, `has_permission_for_abteilung()`,
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
- **Admin-Vergabe** (geplant, Stufe D): Heute kann `personen.write` über
  `PUT /api/users/{id}` jede Rolle setzen – künftig darf das Admin-Flag nur
  von Admins gesetzt/entzogen werden (Letzter-Admin-Schutz bleibt).
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
| **B** | Funktions-Matrix-UI: GET/PUT `/api/funktionen/{id}/permissions` (PUT hart Admin), Matrix-Komponente aus UserPermissionsPage extrahieren, Dialog im Einstellungen-Tab „Funktionen". | offen |
| **C** | Persönlicher Berechtigungsscreen mit Herkunftsanzeige („geerbt von Funktion X (Abteilung Y)" / „Sockel") und Tri-State-Bedienung (Grant/Deny); PUT-Format `{grants, denies}`. | offen |
| **D** | Rollen-Ablösung (v36): nur noch `admin`/`mitglied`; `defaults_for_role` entfällt (Bestand bleibt als Grants erhalten – Permissions wurden schon immer beim Anlegen materialisiert, es gibt keinen Rollen-Fallback zur Laufzeit). Harte `role=='admin'`-Checks ersetzen: `funktionen.verwalten`, `kassen.verwalten`, Ticket-Bereiche/Kategorien → `tickets.bereiche_verwalten`. Admin-Flag-Vergabe nur durch Admins. | offen |
| **E** | Scoping-Durchsetzung, Pilot Personen-/Mitgliederliste: bei nur-scoped `personen.read` Filterung auf Mitglieder der erlaubten Abteilungen via `allowed_abteilungen()`. | offen |

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
