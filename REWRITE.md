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
./venv/bin/python -m uvicorn backend.main:app --reload --port 8000

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

### Roadmap (in dieser Reihenfolge)

| # | Schritt | Aufwand | Hinweis |
|---|---------|---------|---------|
| 1 | ~~Abteilungen~~ | — | ✅ fertig |
| 2 | **PostgreSQL-Migration** | groß | Vor Kassenbuch, damit alle neuen Module direkt auf PG laufen |
| 3 | Mitglied-Abteilung-Zuordnung | mittel | Hängt von Abteilungen ab |
| 4 | PWA aktivieren | klein | `quasar.config.js` auf PWA-Modus, manifest, Icons |
| 5 | Kassenbuch | groß | Mehrere Kassen, Buchungen, CSV/PDF-Export, kassenspez. Berechtigungen, Anhänge |
| 6 | Tickets | groß | Bereiche, Kategorien, Kommentare, Anhänge, Benachrichtigungen |

---

## Schritt 2 im Detail: PostgreSQL-Migration

### Was sich ändert

| SQLite (jetzt) | PostgreSQL |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| `date('now')`, `datetime('now')` | `CURRENT_DATE`, `CURRENT_TIMESTAMP` |
| `last_insert_rowid()` | `RETURNING id` |
| Trigger-Syntax (SQLite) | PL/pgSQL-Trigger (komplett anders) |
| `PRAGMA`-Befehle | entfällt |
| Eigenes Migrations-System | → Alembic |

### Technische Entscheidungen
- **Treiber:** `psycopg3` (`psycopg[binary]`) – modernes Interface, ähnlich wie sqlite3
- **Migrations:** Alembic ersetzt das hand-gerollte Versions-System in `database.py`
- **Connection:** `DATABASE_URL` als Umgebungsvariable (`postgresql://user:pw@host/db`)
- **History-Trigger:** Müssen für PL/pgSQL komplett neu geschrieben werden

### Docker-Setup (lokal testen)
```bash
# PostgreSQL lokal starten (alternativ: sudo apt install postgresql)
docker run -d --name vtb-pg \
  -e POSTGRES_USER=vtb \
  -e POSTGRES_PASSWORD=vtb \
  -e POSTGRES_DB=verein \
  -p 5432:5432 postgres:16

# .env anpassen
DATABASE_URL=postgresql://vtb:vtb@localhost:5432/verein
```

### Schritte
1. `psycopg[binary]` + `alembic` zu `backend/requirements.txt`
2. `backend/core/db.py` auf psycopg3-Connection umschreiben
3. `database.py` portieren: Schema-SQL auf PostgreSQL-Syntax
4. Trigger neu schreiben (PL/pgSQL)
5. Repositories: `lastrowid` → `RETURNING id`, SQLite-Datumsfunktionen ersetzen
6. Alembic initialisieren, erste Migration aus bestehendem Schema generieren
7. `docker-compose.v2.yml` um `postgres`-Service erweitern

---

## Konventionen (für diesen Branch)

- Branch: `rewrite_test`
- Commits: Deutsch, beschreibend
- API-Präfix: `/api/`
- Berechtigungen: immer per `user.has_permission(Permission.XYZ)` prüfen
- Soft-Delete: `mark_*_deleted()` — niemals echtes DELETE
- Versionierung: `expected_version` bei allen PUT-Requests mitschicken
