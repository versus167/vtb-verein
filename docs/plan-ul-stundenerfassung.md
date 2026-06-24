# Plan & Status: Übungsleiter-Stundenerfassung

Stand: 2026-06-24 · Branch `feature/ul-stundenerfassung` · Schema **v54**

## Ziel
Übungsleiter (ÜL) erfassen ihre geleisteten Trainingsstunden selbst, der
Abteilungsleiter (AL) bestätigt, anschließend Fibu-Export (FBASC) + PDF-Beleg
(„Übungsleiter-Stundennachweis"). Vorlage: `2. Quartal 2026 FÜL Aerobic_Annett Wagner.pdf`
(liegt nur lokal, nicht im Repo).

## Status-Überblick
- ✅ **Phase 1 (MVP):** Erfassung (ÜL) + Bestätigung (AL) + Sperr-Logik — fertig & getestet
- ✅ **Phase 2:** PDF-Beleg (A4 quer) + Lizenz-Stammdaten am Mitglied — fertig & getestet
- ⬜ **Phase 3:** Fibu-Anbindung (Kreditor je ÜL) — offen (Detailplan unten)
- ⬜ **Vergütungssätze-UI:** Backend fertig, Frontend-Verwaltungsseite fehlt noch

Beides committet in `4188bf3` (Phase 1+2). Verifikation lief gegen lokale PG14
(Port 5434, DB `vtb_test`): Schema beide Pfade, Workflow, Sperr-Logik, PDF, HTTP-Flow.

## Entscheidungen (mit Auftraggeber abgestimmt)
- Auslieferung **stufenweise** (MVP zuerst).
- **Flexibler Abrechnungszeitraum** (freie von/bis-Spanne, nicht fix Monat/Quartal).
- **Sperre nach Einreichen/Bestätigen:** Zeitraum bis `zeitraum_bis` für weitere
  Erfassungen gesperrt (Wasserzeichen analog `mitglied.abgerechnet_bis`).
- **Vergütungssatz:** primär pro Abteilung + Lizenz; zusätzlich optionaler
  ÜL-individueller Satz. Beim Einreichen als Snapshot eingefroren.
- **Fibu-Buchung: Kreditor je ÜL** (Aufwand Soll / Kreditor Haben, NICHT Forderung wie Beiträge).
- **Lizenzdaten als Mitglied-Stammdaten** (`trainerlizenz_nr`, `qualifikation`) — umgesetzt in Phase 2.

## Datenmodell (umgesetzt, Schema v53/v54)
Tabellen je + `_history` + Audit-Trigger (Muster `gebuehr_forderung`); geteilte
Modul-Konstanten in [database.py](../vtb_verein/app/db/database.py) halten Fresh-Schema
und Migrationen synchron.

- **`ul_abrechnung`** (Header, 1 je ÜL+Abteilung+Zeitraum): `mitglied_id`, `abteilung_id`,
  `zeitraum_von`/`zeitraum_bis` (TEXT-ISO), `status` (entwurf→eingereicht→bestaetigt/abgelehnt),
  `lizenz_klassifikation` (mit_lizenz/ohne_lizenz), `foerder_klassifikation` (LSBS/Spofoe_3_3),
  `verguetung_pro_stunde` (Snapshot), `eingereicht_am/von`, `bestaetigt_am/von`,
  `abgelehnt_grund`, `exportiert_in_export_id`, `storno_exportiert_in_export_id`.
- **`ul_stunde`** (Detail): `abrechnung_id`, `datum`, `stunden` (REAL), `wochentag`, `angebot`, `bemerkung`.
- **`ul_satz`** (konfigurierbare Sätze): `mitglied_id` (NULL=alle), `abteilung_id` (NULL=vereinsweit),
  `lizenz_klassifikation`, `satz`, `gueltig_ab`. Auflösung: ÜL-individuell → Abteilung+Lizenz → vereinsweit+Lizenz.
- **`mitglied`** (v54): + `trainerlizenz_nr`, `qualifikation` (für Beleg-Kopf).
- **`ul_einstellungen`** (Single-Row, **erst Phase 3**): `aufwand_konto`, `kreditor_konto_basis`, `default_kostentraeger`.

**Sperr-Logik** in [ul_stunden_service.py](../vtb_verein/app/services/ul_stunden_service.py):
`erfassbar_ab(mitglied, abteilung) = MAX(zeitraum_bis WHERE status IN (eingereicht,bestaetigt)) + 1 Tag`.
Neue Abrechnung/Termin nur ≥ diesem Datum; Überlappungsschutz via `has_overlap`. Abgelehnt gibt frei.

## Permissions
[permission.py](../vtb_verein/app/models/permission.py): `ulstunden.erfassen` (ÜL),
`ulstunden.bestaetigen` (AL, abteilungs-scoped via `User.has_permission_for_abteilung`),
`ulstunden.verwalten` (Admin/Fibu). An Funktionen `uebungsleiter`/`abteilungsleiter`
geseedet (Fresh-Schema + Migration).

## Umgesetzte Bausteine
**Backend**
- Models [ul_stunden.py](../vtb_verein/app/models/ul_stunden.py)
- Repos [ul_abrechnung_repository.py](../vtb_verein/app/db/ul_abrechnung_repository.py), [ul_satz_repository.py](../vtb_verein/app/db/ul_satz_repository.py) (+ Registrierung in [datastore.py](../vtb_verein/app/db/datastore.py))
- Service [ul_stunden_service.py](../vtb_verein/app/services/ul_stunden_service.py)
- PDF [ul_stundennachweis_pdf_service.py](../vtb_verein/app/services/ul_stundennachweis_pdf_service.py)
- API [backend/api/ul_stunden.py](../backend/api/ul_stunden.py) (+ Registrierung [main.py](../backend/main.py))
- Migration v52→v53 (ul_* Tabellen) + v53→v54 (mitglied-Lizenzfelder) in [database.py](../vtb_verein/app/db/database.py)
- Mitglied-Lizenzfelder durchgereicht: [mitglied.py](../vtb_verein/app/models/mitglied.py), [mitglied_repository.py](../vtb_verein/app/db/mitglied_repository.py), [mitglieder.py](../backend/api/mitglieder.py), [personen.py](../backend/api/personen.py)
- Vereins-Kopfdaten konfigurierbar: [config.py](../backend/core/config.py) (`VTB_VEREIN_NAME` etc.)

**Frontend** (Vue 3 + Quasar)
- [UlStundenPage.vue](../frontend/src/pages/UlStundenPage.vue) (ÜL), [UlBestaetigungPage.vue](../frontend/src/pages/UlBestaetigungPage.vue) (AL)
- Routen [router/index.js](../frontend/src/router/index.js), Menü [MainLayout.vue](../frontend/src/layouts/MainLayout.vue)
- Lizenz-Stammdaten im [MitgliedEditDialog.vue](../frontend/src/components/MitgliedEditDialog.vue)

API-Endpunkte: `GET /api/ul-stunden/{meine|zu-bestaetigen|''}`, `POST/PUT/DELETE /ul-stunden[/{id}]`,
`.../stunden[/{sid}]`, `.../einreichen|bestaetigen|ablehnen|zuruecksetzen`, `GET .../{id}/beleg.pdf`,
`GET/POST/PUT/DELETE /ul-stunden/saetze[/{id}]`.

---

## Offen 1 — Vergütungssätze-UI (Frontend)
Backend (`/api/ul-stunden/saetze`, Recht `ulstunden.verwalten`) ist fertig — es fehlt nur die Seite.
- Neue Page `UlSaetzePage.vue` + Route (`meta.permission: 'ulstunden.verwalten'`) + Menüeintrag.
- Liste aller Sätze (Abteilung · mit/ohne Lizenz · €/h · ggf. ÜL-Override · gültig-ab), Anlegen/Bearbeiten/Löschen.
- Felder: `lizenz_klassifikation` (Pflicht), `satz` (Pflicht), `abteilung_id` (leer=vereinsweit), `mitglied_id` (leer=alle/sonst ÜL-Override), `gueltig_ab`.

## Offen 2 — Phase 3: Fibu-Export (Kreditor je ÜL)
Eigene Positions-Quelle `quelle_typ='ul_abrechnung'` in die **bestehende** Fibu-Pipeline
einhängen (Delta/Storno/Re-Download wiederverwenden), NICHT neuer Export-Lauf-Typ.
1. `ul_einstellungen` (Single-Row) + Repo + API `GET/PUT /ul-stunden/einstellungen` (Recht `ulstunden.verwalten`).
   Felder: `aufwand_konto` (Soll-Sachkonto ÜL-Honorar), `kreditor_konto_basis` (Kreditor = Basis + Mitgliedsnummer), `default_kostentraeger`.
2. [fibu.py-Model](../vtb_verein/app/models/fibu.py): `FibuExportPosition.quelle_typ` um `'ul_abrechnung'` erweitern (Doku).
3. [fibu_export_repository.py](../vtb_verein/app/db/fibu_export_repository.py): `_SQL_UL` analog `_SQL_BEITRAG`/`_SQL_GEBUEHR`
   (nur `status='bestaetigt'`, gleiche `_COND_NEU`/`_COND_STORNO`-Stempelspalten); `tables`-Map in
   `list_neue_positionen`/`list_gegenbuchungen`/`get_positionen_fuer_export`/`create_export`/`un_export` ergänzen.
4. [fibu_export_service.py](../vtb_verein/app/services/fibu_export_service.py): `_positionen_fuer_row` um Zweig
   `'ul_abrechnung'` — **Kreditor-Buchung, kein Debitor/keine Lastschrift**: eine Position je Abrechnung,
   `konto = kreditor_konto_basis + mitgliedsnummer`, `soll_haben='H'`, `gegenkonto = aufwand_konto`,
   `betrag = summe_stunden * verguetung_pro_stunde`, `kostenstelle = abteilung.kostenstelle`,
   Belegnummer-Präfix `U{id}`, Kreditor-Stammdaten aus `mitglied` (Name/IBAN/BIC/kontoinhaber). Storno spiegelt mit `'S'`.
   `_validieren` erweitern (Aufwandskonto + Kreditor-Basis gesetzt, Satz > 0).
5. **Kein neuer Endpunkt**: bestätigte Abrechnungen erscheinen automatisch in `GET /fibu/vorschau` und `POST /fibu/export`.
6. Migration v54→v55 für `ul_einstellungen` (+ Fresh-Schema spiegeln, Trigger-Registry, `_normalize_audit_timestamps`).

**Braucht vom Verein/Steuerberater:** konkretes Aufwandskonto + Kreditor-Konten-Basis. Bis dahin als konfigurierbare Felder mit Platzhaltern anlegen und testbar machen.

## Offen 3 — später
ÜL-individuelle Satz-Overrides im UI, Sportförder-Auswertungen, ggf. Korrektur-Workflows.

---

## Verifikation (Muster, lief lokal grün)
Testskripte lagen im Scratchpad (nicht im Repo). Vorgehen zum Reproduzieren:
- Schema beide Pfade: Fresh-Build (Tabellen droppen → `VereinsDB(url)` baut v54) **und** Migration
  (DB auf v52 setzen, ul_*-Tabellen droppen → erneut `Database(url)`); `schema_version`, Tabellen, Trigger, Permission-Seed prüfen.
- Workflow + Sperr-Logik über `ULStundenService` (anlegen→Termine→einreichen→bestätigen; gesperrter Zeitraum → ValueError).
- HTTP via `fastapi.testclient.TestClient`: Login (Cookie ist HttpOnly → JWT aus `client.cookies[settings.COOKIE_NAME]` als Bearer nutzen), dann ÜL/AL-Flow + `GET .../beleg.pdf` (200, `%PDF`).
- PDF visuell mit `pdftoppm` rendern und gegen die Vorlage vergleichen.

## Lokales Dev-Setup (wichtig für anderen Rechner)
- **Frontend braucht Node 22+** (`@quasar/app-vite` 2.6.0 laut Lockfile). Via nvm: `nvm install 22 && nvm use 22`.
  Bei „Cannot find native binding @rolldown/binding-linux-x64-gnu": unter npm 10 (Node 22) `rm -rf node_modules && npm ci`
  (npm-9-Optional-Deps-Bug überspringt das rolldown-Binding).
- **Quasar Dev-Proxy** zeigt `/api` → `http://localhost:8000` ([quasar.config.js](../frontend/quasar.config.js)).
  Backend im Dev daher mit `VTB_PORT=8000` starten; `VTB_COOKIE_SECURE=false` für http-Login-Cookie.
- **DB:** lokale PG14 auf Port 5434, funktionierende DB `vtb_test` (User/PW `vtb_test`).
  Start: `VTB_DATABASE_URL=postgresql://vtb_test:vtb_test@localhost:5434/vtb_test VTB_PORT=8000 ./venv/bin/python -m backend.main`
- **Python-Env:** `venv/` (nicht `.venv/`).
- **Demo-Logins** (in `vtb_test` geseedet, ggf. neu anlegen): `uebungsleiter`/`ul123`, `abteilungsleiter`/`al123`, `admin`/`admin123`. Abteilung „Aerobic (Demo)" mit Sätzen 30/20 €/h, eine bestätigte Beispiel-Abrechnung (Sept 2024).

## Konventionen (Repo)
- Migrationen über `_migrate_vXX`-Funktionen in `database.py` (NICHT Alembic); Fresh-Schema **und** Migration synchron halten.
- `*_am`-Spalten sind TIMESTAMPTZ → asdict-Endpunkte / datetime-tolerant (keine strikten Pydantic-`str`-Felder).
- VERSION (YYYY.MM.DD.N) erst **beim Merge auf master** bumpen, nicht auf dem Feature-Branch.
