# Tests für vtb-verein

## Tests ausführen

### Alle Tests
```bash
pytest
```

### Spezifische Test-Datei
```bash
pytest vtb_verein/tests/test_user_service.py
```

### Mit Coverage-Report
```bash
pytest --cov=vtb_verein --cov-report=html
```

## Test-Struktur

- `test_user_service.py` - Tests für UserService, insbesondere Schutz des letzten Admins

## Implementierte Test-Szenarien

### Schutz des letzten aktiven Administrators

1. **Rollenwechsel blockiert**: Wenn nur 1 aktiver Admin existiert, kann seine Rolle nicht zu "user" oder "readonly" geändert werden
2. **Deaktivierung blockiert**: Der letzte aktive Admin kann nicht deaktiviert werden
3. **Mit 2 Admins erlaubt**: Wenn mindestens 2 aktive Admins existieren, kann einer herabgestuft oder deaktiviert werden
4. **Kombinierte Änderungen**: Gleichzeitige Änderung von Rolle UND Status wird korrekt behandelt
5. **Nicht-Admins unberührt**: Änderungen an normalen Benutzern sind immer erlaubt
6. **Inaktive Admins**: Inaktive Admins können geändert werden ohne den Schutz zu triggern
