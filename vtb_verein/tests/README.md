# Tests für vtb-verein

Immer über das venv ausführen (nie System-Python). Konfiguration steht in
[`pytest.ini`](../../pytest.ini) im Repo-Wurzelverzeichnis.

## Tests ausführen

### Alle Tests
```bash
./venv/bin/python -m pytest vtb_verein/tests/ -q
```

### Spezifische Test-Datei
```bash
./venv/bin/python -m pytest vtb_verein/tests/test_notification_services.py -q
```

### Mit Coverage-Report
```bash
./venv/bin/python -m pytest vtb_verein/tests/ --cov=vtb_verein --cov-report=html
```

**Warnungen gelten als Fehler** (`filterwarnings = error`). Eine neu auftauchende
`DeprecationWarning` lässt die Suite rot werden — das ist Absicht und kein Anlass,
die Regel zu lockern.

## Was in der Suite steckt

Rund **96 Testdateien**. Drei Sorten, die sich in dem unterscheiden, was sie brauchen:

1. **Reine Unit-Tests** — pure Logik ohne DB und ohne HTTP. Hier liegt der Kern der
   Fachlichkeit: `test_iban`, `test_effective_permissions`, `test_beitrags_service`,
   `test_gebuehren_service`, `test_kassen_kategorie`, `test_ul_stunden_service`,
   `test_vault_crypto`, `test_anhang_service`, `test_notification_services`.
2. **Endpunkt-Tests mit Stubs** — der Router wird direkt aufgerufen, DB und User sind
   `SimpleNamespace`-Attrappen (Muster: `test_tresor_api`). Damit lassen sich
   Berechtigungs- und Scope-Fragen prüfen, ohne eine Datenbank zu brauchen:
   `test_personen_scope_api`, `test_delegation_api`, `test_login_bremse_api`,
   `test_anhang_download_api`, `test_magic_link_protokoll`, `test_security_headers`.
3. **DB-nahe Integrationstests** (~32 Dateien) — echtes PostgreSQL, echtes Schema:
   `test_tresor_integration`, `test_prune_integration`,
   `test_schloss_status_log_integration`, `test_ticket_bereich_berechtigung_integration`
   und weitere.

Die dritte Sorte **skippt automatisch**, solange `VTB_TEST_DATABASE_URL` nicht gesetzt
ist. Ohne die Variable läuft die Suite also durch, prüft aber deutlich weniger — wer
etwas am Schema ändert, muss die DB-Tests fahren.

## DB-nahe Tests fahren

Es gibt (noch) **keine gemeinsame `conftest.py`/Fixture**: Jede Integrationstest-Datei
baut ihre Anbindung selbst auf und skippt einzeln. Eine wiederverwendbare Fixture steht
im [`TODO.md`](../../TODO.md) unter Tech-Debt.

Der bewährte Weg ist ein **leerer Wegwerf-Container**:

```bash
docker run -d --name vtb-pg-test -p 5432:5432 \
  -e POSTGRES_USER=vtb -e POSTGRES_PASSWORD=vtb -e POSTGRES_DB=verein postgres:18
docker exec vtb-pg-test psql -U vtb -d verein -c 'CREATE DATABASE vtb_test'
export VTB_TEST_DATABASE_URL=postgresql://vtb:vtb@localhost:5432/vtb_test
./venv/bin/python -m pytest vtb_verein/tests/ -q
```

Erwartung: **1540 bestandene Tests** (Stand 2026-08-18). Ohne die Variable sind es
1126 bestandene und **414 übersprungene** — mehr als ein Viertel der Suite läuft dann
also gar nicht. Für einen zweiten
Durchgang die Datenbank wegwerfen und neu anlegen (`DROP DATABASE vtb_test` /
`CREATE DATABASE vtb_test`), sonst prüft der Lauf nicht mehr den Frischaufbau.

`VereinsDB` legt das Schema beim Connect selbst an — kein Migrationsbefehl nötig.
Wichtig ist die **leere** Datenbank: Die Tests prüfen beide Schema-Pfade, den
**Frischaufbau** und die **Migration**, und der Frischaufbau setzt eine jungfräuliche
DB voraus. Für Migrationen gegen echte Daten stattdessen einen Dev-Dump per
`pg_restore` einspielen und von dort hochmigrieren.

> Die früheren SQLite-basierten Tests (z. B. `test_user_service.py`) wurden mit dem
> Umstieg SQLite → PostgreSQL und der Entfernung der NiceGUI-Schicht gelöscht. In der
> Anwendung gibt es kein SQLite mehr.
