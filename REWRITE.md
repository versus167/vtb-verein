# Neuschreib: FastAPI + Vue 3/Quasar

Ziel: Ablösung von Python/NiceGUI durch eine saubere Trennung von
REST-Backend (FastAPI) und mobilfähigem SPA-Frontend (Vue 3 + Quasar).

## Architektur

```
/
├── backend/            FastAPI-App (Python)
│   ├── main.py         Einstiegspunkt, CORS, Router-Registrierung
│   ├── core/           config.py · security.py · db.py · deps.py
│   ├── api/            Ein Router pro Domain
│   └── Dockerfile      Multi-Stage: Quasar bauen + Python laufen lassen
├── frontend/           Vue 3 + Quasar SPA
│   ├── src/
│   │   ├── boot/       pinia.js · axios.js · auth.js
│   │   ├── stores/     auth.js (Pinia)
│   │   ├── layouts/    MainLayout.vue
│   │   └── pages/      Eine Seite pro Modul
│   └── quasar.config.js
├── docker-compose.v2.yml
└── vtb_verein/         Alter Code (Repositories + Services weiter genutzt)
```

Das Backend importiert direkt aus `vtb_verein/app/db/` und
`vtb_verein/app/services/` — kein Code-Duplikat, nur neue API-Schicht.

### Dev starten

```bash
# Terminal 1 – Backend (Port 8000)
PYTHONPATH=vtb_verein ./venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 – Frontend (Port 9000, Proxy auf :8000)
cd frontend && npx quasar dev
```

API-Dokumentation: http://localhost:8000/api/docs

---

## Fortschritt

### Fertig
- [x] FastAPI-Grundgerüst (JWT-Auth, CORS, OpenAPI)
- [x] Login / Logout / Eigenes Profil + Passwort ändern
- [x] Mitglieder (CRUD)
- [x] Abteilungen (CRUD + Soft-Delete + Papierkorb/Restore)
- [x] Benutzerverwaltung (CRUD + Berechtigungs-Matrix)
- [x] Quasar SPA: Login, Dashboard, Navigation, alle obigen Seiten
- [x] PostgreSQL-Migration (psycopg3, PL/pgSQL-Trigger, Alembic)

### Roadmap (in dieser Reihenfolge)

| # | Schritt | Aufwand | Hinweis |
|---|---------|---------|---------|
| 1 | ~~Abteilungen~~ | — | ✅ fertig |
| 2 | ~~PostgreSQL-Migration~~ | — | ✅ fertig |
| 3 | ~~Mitglied-Abteilung-Zuordnung~~ | — | ✅ fertig |
| 4 | ~~PWA aktivieren~~ | — | ✅ fertig |
| 5 | Kassenbuch | groß | Mehrere Kassen, Buchungen, CSV/PDF-Export, kassenspez. Berechtigungen, Anhänge |
| 6 | Tickets | groß | Bereiche, Kategorien, Kommentare, Anhänge, Benachrichtigungen |

---

## PostgreSQL-Migration (✅ abgeschlossen 2026-05-18)

- Treiber: `psycopg[binary]>=3.1` + `sqlalchemy>=2.0` + `alembic>=1.13`
- `vtb_verein/app/db/database.py` komplett neu: psycopg3-Connection, konsolidiertes Schema v15, PL/pgSQL-Trigger
- Alle Repositories: `?` → `%s`, `lastrowid` → `RETURNING id`, SQLite-Datumsfunktionen ersetzt
- Verbindung via `VTB_DATABASE_URL` in `.env` (`postgresql://user:pw@host:port/db`)
- Alembic initialisiert (`backend/alembic/`), DB auf Baseline-Revision gestempelt
- `docker-compose.v2.yml` um `db`-Service (postgres:16) erweitert

### Zukünftige Schema-Änderungen
```bash
./venv/bin/alembic revision -m "beschreibung"   # neue Migration anlegen
./venv/bin/alembic upgrade head                  # Migration ausführen
./venv/bin/alembic current                       # aktuelle Version prüfen
```

---

## Konventionen (für diesen Branch)

- Branch: `rewrite_test`
- Commits: Deutsch, beschreibend
- API-Präfix: `/api/`
- Berechtigungen: immer per `user.has_permission(Permission.XYZ)` prüfen
- Soft-Delete: `mark_*_deleted()` — niemals echtes DELETE
- Versionierung: `expected_version` bei allen PUT-Requests mitschicken
