# Tests für vtb-verein

Immer über das venv ausführen (nicht system-python).

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

## Aktuelle Tests

- `test_anhang_service.py` – Anhang-/Upload-Service (Dateinamen, Validierung)
- `test_notification_services.py` – Benachrichtigungs-/Kanal-Logik

> Die früheren SQLite-basierten Tests (z.B. `test_user_service.py`) wurden mit dem
> Umstieg sqlite → PostgreSQL und der Entfernung der NiceGUI-Schicht gelöscht.

## DB-nahe Tests

Es gibt (noch) keine PostgreSQL-Test-Fixture/`conftest.py`. Repository-/Service-Tests, die
eine echte DB brauchen, werden derzeit ad hoc gegen einen **Wegwerf-PostgreSQL-Container**
gefahren (z.B. `docker run … postgres:18`), ggf. mit einem `pg_restore` eines Dev-Dumps, um
Migrationen gegen echte Daten zu prüfen. Eine wiederverwendbare Fixture wäre ein sinnvoller
nächster Schritt.
