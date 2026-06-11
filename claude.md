Du hilfst mir, ein Webprojekt für Vereinsverwaltung zu entwickeln.
Repository: https://github.com/versus167/vtb-verein

## Projekt-Kontext
- **Stack:** Quasar/Vue (Frontend, PWA) · FastAPI (Backend) · PostgreSQL via psycopg3 (rohes SQL, kein ORM)
- Fokus auf Mitglieder-/Personenverwaltung, Abteilungen, Mannschaften, Beiträge, Gebühren
  und Vereins-Tools (Kasse, Tickets, …)
- Die frühere NiceGUI/SQLite-Variante wurde abgelöst (siehe `REWRITE.md` für die Historie).

## Architektur (geschichtet)
```
Frontend (Quasar/Vue, PWA)   frontend/src/           – SPA, ruft /api
        │ HTTP /api
API (FastAPI)                backend/api/            – Router je Domäne, JWT-Auth, Permissions
        │
Service-Layer                vtb_verein/app/services/ – Business-Logik, Orchestrierung
        │
Repository-Layer             vtb_verein/app/db/      – CRUD, SQL, Mapping → Models
        │
PostgreSQL (psycopg3)        vtb_verein/app/db/database.py – Schema + Migrationen
```
- Das Backend importiert den Service-/Repository-Layer aus `vtb_verein/app/` über
  `PYTHONPATH=vtb_verein`. Kein Code-Duplikat — nur eine neue API-Schicht über dem alten Kern.
- **Patterns:** Repository (`*_repository.py`) · Facade (`VereinsDB`/`datastore.py` delegiert an
  Repositories) · Service-Layer (Business-Logik in `services/`, nicht in Repositories).

## Datenbank-Prinzipien (WICHTIG – immer beachten!)

### Soft-Delete
- **Ausschließlich** Soft-Delete über `deleted_at`/`deleted_by`; niemals hart löschen
  (weder DB-Einträge noch Dateien).
- Repository-Methoden heißen `mark_*_deleted()`, nicht `delete_*()`.
- Hard-Delete nur für künftige Prune-/Cleanup-Jobs vorgesehen (noch nicht implementiert).

### History-Tracking
- Jede Haupttabelle hat eine `*_history`-Tabelle, automatisch befüllt über **PL/pgSQL-Trigger**
  (definiert in `database.py`).
- INSERT-Trigger: neuer Record sofort in History. UPDATE-Trigger: nur bei `version`-Änderung.
- Bei Soft-Delete wird der letzte Stand mit `deleted_at`/`deleted_by` in die History geschrieben.

### Versionierung (Optimistic Locking)
- Jede Entität hat ein `version`-Feld, das bei jedem UPDATE erhöht wird.
- Bei PUT/Update vom Client immer `expected_version` mitschicken.

### Beträge
- Geldbeträge (Kassenbuch, Beiträge, Gebühren) durchgängig in **Cent (Integer)** — kein Float.

### Migrationen
- **KEIN Alembic.** Das Schema wird über eine eigene versionierte Pipeline in
  `vtb_verein/app/db/database.py` verwaltet.
- Neue Migration = neue `_migrate_vX_to_vY()`-Funktion + Eintrag in `migration_map` +
  `SCHEMA_VERSION` erhöhen. Frisch-Schema (`_create_tables`/`_create_trigger_functions`/
  `_create_triggers`/`_create_indexes`) parallel pflegen.
- Migration läuft beim Backend-Start automatisch (`Database._init_schema()`).

### Anhänge
- Domänen-isoliert: jede Domäne hat eigene Tabelle + eigenes Datei-Präfix
  (z.B. `kassenbuchung_anhaenge`/`kabu_`, `ticket_anhaenge`/`att_`). Kein zentrales Storage.

## Datumsberechnungen
- Relative Datumslogik und berechnete Flags möglichst direkt im SQL (Performance), z.B.
  `now() - interval '6 months'` statt Python-Loops.

## Tests
- pytest **immer** über das venv ausführen (`./venv/bin/pytest`), nie system-python.

## Branches, Commits & Pull Requests
- **Niemals selbstständig committen** — immer erst fragen und auf Bestätigung warten.
- Niemals direkt auf `master` arbeiten/committen. Immer einen Entwicklungsbranch verwenden;
  vor dem Tätigwerden prüfen, ob der aktuelle Branch passt.
- Alle Änderungen per Pull Request auf `master`.
- Branch-Namen: `kategorie/kurze-beschreibung` (lowercase, hyphens), Kategorien
  `feature/` `fix/` `refactor/` `docs/`. Beispiel: `feature/member-list-filter`.
- Commit-Messages: Deutsch, beschreibend, mit Kontext.
- Vor PR: lokal testen, Edge Cases prüfen.

## Dev starten
```bash
# Terminal 1 – Backend (Port 8000); Schema migriert beim Start automatisch
PYTHONPATH=vtb_verein ./venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 – Frontend (Quasar-Dev, Proxy /api → :8000)
cd frontend && npx quasar dev
```
API-Doku: http://localhost:8000/api/docs

---
Erinnere mich, wenn in einem Thread eine Anweisung/Regel auftritt, die hier in die Instruction
passt, dass ich das hier ändere.
