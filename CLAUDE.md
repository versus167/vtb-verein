# CLAUDE.md — Grundlegende Konventionen der Vereinsverwaltung

Diese Datei bündelt die verbindlichen Projekt-Konventionen für alle, die am Code arbeiten
(inkl. KI-Assistenten). Sie beschreibt *wie* hier gebaut wird; Details stehen im jeweiligen
Code.

## Architektur / Verzeichnisse
- **`backend/`** — aktives FastAPI-Backend. Router unter `backend/api/*`, in `main.py` via
  `app.include_router(..., prefix="/api")` registriert. Querschnitt in `backend/core/`
  (`deps.py`: `CurrentUser`/`DB`-Dependencies, `config.py`: `settings` aus Env, `db.py`:
  `get_db()`-Singleton). Konfiguration ausschließlich über Env/`.env` (`load_dotenv()` in
  `main.py`) — Beispiele in `.env.example`.
- **`vtb_verein/app/`** — Domänen-/DB-Schicht: `models/` (Dataclasses + `permission.py`),
  `db/` (Repositories, `datastore.py` als Fassade, `database.py` mit Schema+Migrationen),
  `services/` (Geschäftslogik). Das frühere NiceGUI-UI ist entfernt.
- **`frontend/`** — Quasar/Vue-3-SPA (`<script setup>`, Pinia, vue-router).

## Datenbank, Migrationen, Repositories
- PostgreSQL. **Kein Alembic zur Laufzeit.** Schema und Migrationen leben in
  `vtb_verein/app/db/database.py`: `SCHEMA_VERSION` hochzählen, Migrationsmethode
  `_migrate_vN_to_vN+1` schreiben und in der `migration_map` registrieren.
- **Fresh == Migriert:** DDL für neue Tabellen als geteilte Modul-Konstante (`_DDL_*`,
  `_FN_*`, `_*_TRIGGERS`, `_*_INDEXES`) definieren und aus *beiden* Pfaden aufrufen —
  dem Frischaufbau (`_create_tables`/`_create_trigger_functions`/`_create_triggers`/
  `_create_indexes`) **und** der Migration. Migrationen rufen am Ende
  `_normalize_audit_timestamps`, damit Zeitstempel überall `TIMESTAMPTZ` sind.
- Repositories erben von `BaseRepository` und nutzen `with self.cursor() as cur:`
  (auto-commit/rollback), rohes psycopg-SQL. Neue Repos in `datastore.py` instanziieren
  und als `@property` exponieren.

## Soft-Delete, History, Prune (WICHTIG)
- **Niemals hart löschen** — weder DB-Zeilen noch Dateien. Löschen heißt `deleted_at`/
  `deleted_by` setzen und `version` erhöhen; jede Änderung mit `version`-Bump wird per
  Audit-Trigger in die zugehörige `*_history`-Tabelle geschrieben.
- **Bei jeder neuen Soft-Delete-Tabelle IMMER auch das `PRUNE_REGISTRY` in
  `vtb_verein/app/services/prune_service.py` erweitern** (`PruneEntity` mit `history_table`,
  `ChildRef`s, Reihenfolge Kinder-vor-Eltern). Sonst wachsen soft-gelöschte Zeilen
  unbegrenzt und werden nie bereinigt. Append-only Logs (kein `deleted_at`/keine History,
  z. B. `*_zugriff_log`) sind *keine* `PruneEntity`, sondern höchstens `ChildRef` bzw.
  bekommen bei Bedarf einen eigenen zeitbasierten Prune (analog `access_log`).

## Berechtigungen
- Effektive Rechte = **Sockel ∪ Funktionsrechte ∪ individuelle Grants − Denies**
  (`permission.py::compute_effective_permissions`). Admins (`role == 'admin'`) haben immer
  alles; `user.has_permission(...)` respektiert das.
- **Ressourcen-genaue Rechte laufen NICHT über globale Permissions**, sondern über eigene
  ACL-Tabellen — Kassen via `kasse_berechtigungen`, Tresor via `tresor_freigabe`. Globale
  Rechte gibt es dort nur fürs Verwalten (z. B. `kassen.verwalten`, `tresor.verwalten`).
- Neue Permission-Keys als Konstante in `permission.py` ergänzen, im Admin-Seed (`_seed_data`)
  aufnehmen und für Bestands-Admins in der Migration nachziehen (Fresh == Upgrade).

## Tests
- **Immer über das venv** ausführen: `./venv/bin/python -m pytest vtb_verein/tests/ -q`
  (nie System-Python). Warnungen sind Fehler (`filterwarnings = error`).
- DB-nahe Integrationstests skippen ohne `VTB_TEST_DATABASE_URL` und laufen gegen einen
  **leeren Wegwerf-Postgres** (z. B. `docker run … postgres:18`); `VereinsDB` legt das
  Schema beim Connect an. Beide Schema-Pfade (Frischaufbau *und* Migration) prüfen.

## Frontend-Konventionen
- Navigation und Dashboard-Kacheln sind rechte-/ACL-gesteuert (`auth.hasPermission(...)`;
  für ACL-Ressourcen zusätzlich eine Liste laden, z. B. `/api/kassen/`, `/api/tresor`).
- Bereichsinterne Unterteilung über in-page `q-tabs`, nicht über verschachtelte Nav-Punkte.
  Auto-Refresh via `usePageRefresh(handler)`. Router-Guard (`boot/auth.js`) behandelt
  `meta.permission` als ODER bei Array; Admins umgehen alle Checks.

## Release-/Commit-Workflow
- **Nur nach ausdrücklicher Rücksprache committen** — nie selbstständig. Auf `master` erst
  einen Feature-Branch anlegen.
- Merge nach `master` per `git merge --no-ff` mit Titel `Merge: <Beschreibung> (#NN) (vVERSION)`.
- Bei jedem master-Merge die `VERSION`-Datei auf `YYYY.MM.DD.N` bumpen (laufende Nr. `N`
  hochzählen). Anzeige `v.…` über `/api/app-info`.
- Commit-Messages enden mit dem Trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
