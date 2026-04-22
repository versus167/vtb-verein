Du hilfst mir, ein Webprojekt für Vereinsverwaltung zu entwickeln.
Repository: https://github.com/versus167/vtb-verein

## Projekt-Kontext
- Python-basierte Webanwendung mit NiceGUI
- SQLite-Datenbank mit strukturiertem Repository-Pattern
- Fokus auf Mitgliederverwaltung, Abteilungen, Beiträge, Tools für den Verein wie Kasse, Hallenplan oder ähnliches

## Datenbank-Prinzipien (WICHTIG - immer beachten!)

**Aktuell: SQLite** (schneller Einstieg). Mögliche zukünftige Migration zu PostgreSQL.

### Soft-Delete
- Wir verwenden **ausschließlich** Soft-Delete über `deleted_at` und `deleted_by`
- Repository-Methoden heißen `mark_*_deleted()`, nicht `delete_*()`
- Hard-Delete ist nur für zukünftige Prune-Funktionen vorgesehen
- **Prune-Operationen**: Noch nicht implementiert (TODO: Später für Datenbank-Cleanup) 

### History-Tracking
- Jede Haupttabelle hat eine entsprechende `*_history` Tabelle
- History wird über **SQLite-Trigger in `database.py`** automatisch geschrieben
- **INSERT-Trigger**: Jeder neue Record wird sofort in die History geschrieben
- **UPDATE-Trigger**: Nur wenn `version != old.version`, wird in History geschrieben
- **DELETE-Trigger**: Schreibt den finalen Stand in History (für echte Deletes, nicht Soft-Delete)
- Bei Soft-Delete (via `mark_*_deleted()`) wird der letzte Stand mit `deleted_at`/`deleted_by` in History geschrieben

### Versionierung
- Jede Entität hat ein `version` Feld (Optimistic Locking)
- Version wird bei jedem UPDATE erhöht
- History-Trigger reagieren auf Version-Änderungen

## Architektur-Pattern
- **Repository-Pattern**: Alle DB-Operationen in `*_repository.py`
- **Facade-Pattern**: `VereinsDB` delegiert an Repositories
- **Service-Layer**: Business-Logik gehört in Services, nicht in Repositories
- **UI-Layer**: NiceGUI-basierte Komponenten in `app/ui/`

## Änderungen und Pull Requests
- Alle Änderungen nur per Pull Request auf die `master`-Branch
- Niemals direkt auf `master` committen

## NiceGUI-spezifische Regeln
- `ui.add_head_html()` immer INNERHALB der @ui.page-Funktion
- Tabellen-Row-Styling über body-Slot mit Vue-Template
- Performance: SQL-Berechnungen in DB, nicht in Python-Loops
- Alle Client-Aktionen (ui.notify, ui.download, etc.) müssen vor dialog.close() aufgerufen werden.

## Branch-Namen
- Format: `kategorie/kurze-beschreibung` (lowercase, hyphens)
- Kategorien: `feature/`, `fix/`, `refactor/`, `docs/`
- Branches immer im jeweiligen Unterordner anlegen (mit Slash)
- Beispiel: `feature/member-list-filter-recent-exits`
- Beispiel: `fix/mitglied-history-triggers`
- NICHT: `feature-member-list-filter` (ohne Slash)

## Feature-Entwicklung
- Commit-Messages: Deutsch, beschreibend, mit Kontext
- Vor PR: Lokal testen, Edge Cases prüfen 

## SQL-Datumsberechnungen
- Relative Datumsberechnungen mit SQLite-Funktionen: `date('now', '-6 months')`
- Berechnete Flags direkt im SQL (Performance)



Erinnere mich, wenn in einem Thread eine Anweisung/Regel auftritt, die vlt. hier in die Instruction passt, dass ich das hier ändere!
