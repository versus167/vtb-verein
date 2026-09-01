---
name: schema-migration
description: Verwende diesen Skill bei jeder Änderung am Datenbankschema von vtb-verein – neue Spalten, Tabellen, SCHEMA_VERSION-Erhöhungen oder Migrationsfunktionen in database.py.
---

# Schema-Migrations-Workflow

Bei jeder Schema-Änderung IMMER alle vier Schritte ausführen, nie nur einzelne:

1. `SCHEMA_VERSION` in database.py um 1 erhöhen
2. Neue Funktion `_migrate_vX_to_vY()` schreiben (X = alte, Y = neue Version)
3. Eintrag in `migration_map` ergänzen, der auf die neue Funktion zeigt
4. Passende DDL-Konstanten für Fresh-Installs parallel anpassen

Regel: "Fresh == Migriert" – eine frische Installation mit aktuellem
Schema muss exakt dasselbe Ergebnis liefern wie eine bestehende DB,
die durch alle Migrationen gelaufen ist. Nach jeder Änderung beide
Pfade gedanklich durchspielen.

## Checkliste vor dem Commit

- [ ] SCHEMA_VERSION erhöht?
- [ ] `_migrate_vX_to_vY()` implementiert und im `migration_map` registriert?
- [ ] DDL-Konstanten für Fresh-Install auf denselben Stand gebracht?
- [ ] Kurzer manueller Test: Fresh-Install vs. migrierte DB liefern identisches Schema?
