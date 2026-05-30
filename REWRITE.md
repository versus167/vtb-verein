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
│   │   ├── kassenbuch.py
│   │   ├── tickets.py
│   │   └── uploads.py  Auth-geschützter Datei-Download
│   └── Dockerfile      Multi-Stage: Quasar bauen + Python laufen lassen
├── frontend/           Vue 3 + Quasar SPA
│   ├── src/
│   │   ├── boot/       pinia.js · axios.js · auth.js
│   │   ├── stores/     auth.js (Pinia)
│   │   ├── components/ AnhangPanel.vue (geteilt)
│   │   ├── layouts/    MainLayout.vue
│   │   └── pages/      Eine Seite pro Modul
│   └── quasar.config.js
├── docker-compose.yml
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
- [x] Kassenbuch (Kassen-CRUD, Buchungen, CSV-Export, kassenspez. Berechtigungen)
- [x] Anhänge (Kassenbuch + Tickets): Upload, Download, Soft-Delete; `AnhangPanel.vue` geteilt
- [x] Tickets (vollständig): Bereiche, Kategorien, CRUD, Statuswechsel, Anhänge, Kommentare, Berechtigungen, Mobile
- [x] Mobile-Optimierung Kassenbuch: Karten-Liste, Bottom-Sheet-Dialoge, einklappbarer Filter
- [x] Mobile-Optimierung Tickets: Karten-Liste mit Status-Farbe + Prioritäts-Akzent
- [x] Kassenbuch PDF-Bericht: Zeitraumauswahl, reportlab, Zusammenfassung + Buchungstabelle
- [x] Kassenbuch Berechtigungen: `darf_schreiben`/`darf_exportieren` korrekt aus DB gelesen und in UI ausgewertet

### Roadmap (in dieser Reihenfolge)

| # | Schritt | Aufwand | Hinweis |
|---|---------|---------|---------|
| 1 | ~~Abteilungen~~ | — | ✅ fertig |
| 2 | ~~PostgreSQL-Migration~~ | — | ✅ fertig |
| 3 | ~~Mitglied-Abteilung-Zuordnung~~ | — | ✅ fertig |
| 4 | ~~PWA aktivieren~~ | — | ✅ fertig |
| 5 | ~~Kassenbuch~~ | — | ✅ fertig inkl. Anhänge |
| 6 | ~~Anhänge (Kassenbuch + Tickets)~~ | — | ✅ fertig |
| 7 | ~~Tickets (vollständig)~~ | — | ✅ fertig |
| 8 | ~~Kassenbuch PDF-Bericht~~ | — | ✅ fertig |
| 9 | ~~Benachrichtigungen (E-Mail + Matrix)~~ | — | ✅ fertig |
| 10 | ~~Mobile-Feinschliff~~ | — | ✅ fertig (Kassenbuch + Tickets) |

---

## PostgreSQL-Migration (✅ abgeschlossen 2026-05-18)

- Treiber: `psycopg[binary]>=3.1` + `sqlalchemy>=2.0` + `alembic>=1.13`
- `vtb_verein/app/db/database.py` komplett neu: psycopg3-Connection, konsolidiertes Schema v15, PL/pgSQL-Trigger
- Alle Repositories: `?` → `%s`, `lastrowid` → `RETURNING id`, SQLite-Datumsfunktionen ersetzt
- Verbindung via `VTB_DATABASE_URL` in `.env` (`postgresql://user:pw@host:port/db`)
- Alembic initialisiert (`backend/alembic/`), DB auf Baseline-Revision gestempelt
- `docker-compose.yml` um `db`-Service (postgres:16) erweitert

### Zukünftige Schema-Änderungen
```bash
./venv/bin/alembic revision -m "beschreibung"   # neue Migration anlegen
./venv/bin/alembic upgrade head                  # Migration ausführen
./venv/bin/alembic current                       # aktuelle Version prüfen
```

---

## Kassenbuch (✅ abgeschlossen 2026-05-29)

- **Backend**: `backend/api/kassenbuch.py` — FastAPI-Router mit Prefix `/api/kassen/`
- **Berechtigungen**: kassenspezifisch via `kasse_berechtigungen`-Tabelle; Admins haben immer vollen Zugriff; `darf_schreiben`/`darf_exportieren` werden in `list_kassen` mitgeliefert und in der UI ausgewertet (Buttons ausgeblendet)
- **Seiten**: `KassenbuchPage.vue` (Kacheln), `KassenverwaltungPage.vue` (Admin: CRUD + Berechtigungen), `KassenbuchDetailPage.vue` (Journal + Export + Anhänge + PDF)
- **Journal**: Neueste Buchung oben, laufender Bestand rückwärts vom Gesamtbestand berechnet
- **Bestandsprüfung**: am Buchungsdatum (`get_bestand_zum_datum_cent`) — verhindert Negativbuchungen in der Vergangenheit
- **CSV-Export**: sperrt Buchungen (`exportiert_in_export_id`), Re-Download alter Exporte möglich; Bis-Datum vorbelegt mit letztem Monatsletzten
- **PDF-Bericht**: `GET /api/kassen/{id}/bericht.pdf?von=…&bis=…`; reportlab; Zusammenfassung + Buchungstabelle (stornierte grau, exportierte blau); Von/Bis-Dialog vorbelegt mit Tag-nach-letztem-Export bis letzten Monatsletzten
- **Mobile**: Karten-Liste statt Tabelle auf kleinen Screens, Bottom-Sheet-Dialoge, Filter einklappbar

---

## Anhänge (✅ abgeschlossen 2026-05-27)

### Prinzip
Domain-isolierte Anhänge: Kassenbuch und Tickets haben jeweils eigene DB-Tabelle
(`kassenbuchung_anhaenge`, `ticket_anhaenge`) und eigene Datei-Präfixe (`kabu_`, `att_`).
Kein zentrales Attachment-Storage. Bilder werden serverseitig automatisch zu PDF konvertiert.

### Backend
- `backend/api/uploads.py` — `GET /api/uploads/{stored_name}`: JWT-Auth, Path-Traversal-Schutz, Bilder inline / PDFs als Attachment
- Kassenbuch-Anhang-Endpoints in `backend/api/kassenbuch.py`:
  - `GET /api/kassen/{id}/buchungen/{id}/anhaenge`
  - `POST /api/kassen/{id}/buchungen/{id}/anhaenge` (multipart)
  - `DELETE /api/kassen/{id}/buchungen/{id}/anhaenge/{id}`
- Ticket-Anhang-Endpoints analog in `backend/api/tickets.py`

### Frontend
- `frontend/src/components/AnhangPanel.vue` — geteilte Komponente für Upload, Galerie, Soft-Delete
  - Download via Axios (nicht `<a href>`), damit der Bearer-Token mitgeschickt wird
  - Props: `anhaenge`, `uploadUrl`, `canUpload`, `canDelete`
  - Events: `uploaded`, `deleted`

---

## Tickets (✅ abgeschlossen 2026-05-30)

- **Backend**: `backend/api/tickets.py` — Prefix `/api/tickets/`
- **Entitäten**: Bereiche, Kategorien, Tickets, Kommentare, Anhänge
- **Sichtbarkeit**: Alle eingeloggten User sehen alle Tickets; kein bereichsbasierter Leseschutz
- **Kommentare**: Alle User können Kommentare zu offenen Tickets schreiben; interne Kommentare nur mit Bearbeitungsrecht im Bereich; geschlossene Tickets (erledigt/abgelehnt) sind gesperrt
- **Statuswechsel**: `PATCH /api/tickets/{id}/status` mit Übergangsprüfung; Bearbeitungsrecht im Bereich erforderlich
- **Berechtigungen**: `ticket_bereich_berechtigungen` (darf_bearbeiten / darf_schliessen); Bearbeitungsrecht bestimmt auch die „Nur meine"-Zuständigkeit
- **`zugewiesen_an`**: DB-Spalte bleibt, aus UI und API entfernt; Zuständigkeit läuft über Bereichsberechtigungen
- **Frontend**: `TicketsPage.vue` — Filter (Bereich, Status, Nur meine, Abgeschlossene), Erstellen-Dialog, Detail-Dialog mit Inline-Edit, Statuswechsel, Kommentar-Thread, AnhangPanel
- **Mobile**: Karten-Liste mit dezenter Status-Hintergrundfarbe, farbigem Prioritäts-Akzent (linker Rand), Ersteller-Anzeige

---

## Benachrichtigungen (✅ abgeschlossen 2026-05-30)

- **Kanäle**: E-Mail (immer aktiv) + Matrix (optional); Telegram entfernt
- **Fallback**: Matrix → E-Mail wenn Matrix-Versand fehlschlägt
- **User-Konfiguration**: Profil-Seite (`/profile`) — Matrix-ID hinterlegen, bevorzugten Kanal wählen, Test-Nachricht senden
- **Backend**: `PATCH /api/auth/me/contact`, `POST /api/auth/me/contact/test`; `GET /api/auth/me` liefert `matrix_id` + `preferred_contact`
- **Ticket-Benachrichtigungen** (aktiv): Erstellen, Statuswechsel, Kommentar
- **Willkommens-Mail**: beim User-Anlegen ohne Magic-Link (z.B. wenn Admin direkt Passwort setzt)
- **Noch nicht verdrahtet**: Mitglied-Ereignisse, Kassenbuch-Vorgänge (bewusst zurückgestellt)

---

## Konventionen (für diesen Branch)

- Branch: `rewrite_test`
- Commits: Deutsch, beschreibend
- API-Präfix: `/api/`
- Berechtigungen: domainspezifisch (Kassen: `kasse_berechtigungen`, Tickets: `ticket_bereich_berechtigungen`)
- Soft-Delete: `mark_*_deleted()` — niemals echtes DELETE
- Versionierung: `expected_version` bei allen PUT-Requests mitschicken
- Datei-Downloads: immer via Axios (nicht `<a href>`), damit JWT-Token übertragen wird
