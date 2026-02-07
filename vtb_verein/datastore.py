'''
Created on 07.02.2026

@author: volker
'''

import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 3  # hier erhöhst du bei Änderungen am Schema


class VereinsDB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema_version_table()
        self._migrate_schema_if_needed()

    # -----------------------------------
    # Basis: Kontext / Commit-Handling
    # -----------------------------------
    @contextmanager
    def cursor(self):
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def close(self):
        self.conn.close()

    # -----------------------------------
    # Schema-Versionierung
    # -----------------------------------
    def _init_schema_version_table(self):
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    id              INTEGER PRIMARY KEY CHECK (id = 1),
                    version         INTEGER NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_version (id, version) VALUES (1, ?)",
                    (0,),
                )

    def _get_schema_version(self) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            (version,) = cur.fetchone()
            return version

    def _set_schema_version(self, version: int):
        with self.cursor() as cur:
            cur.execute(
                "UPDATE schema_version SET version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (version,),
            )

    def _migrate_schema_if_needed(self):
        current = self._get_schema_version()
        if current == 0:
            self._migrate_0_to_1()
            current = 1
        
        if current == 1:
            self._migrate_1_to_2()
            current = 2
            
        if current == 2:
            self._migrate_2_to_3()
            current = 3
        # hier zukünftige Migrationen einbauen:
        # if current == 1:
        #     self._migrate_1_to_2()
        #     current = 2

        if current != SCHEMA_VERSION:
            # Optional: Fehler werfen, wenn SW-Version nicht zum DB-Schema passt
            raise RuntimeError(
                f"Schema-Version {current} gefunden, "
                f"erwartet {SCHEMA_VERSION}. Bitte Migration erweitern."
            )

    # -----------------------------------
    # Migrationen
    # -----------------------------------
    def _migrate_0_to_1(self):
        """Initiales Schema: Tabellen 1, 2, 2a, 3, 4 + audit_log."""
        with self.cursor() as cur:
            # Tabelle 1: mitglied
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied (
                  id                INTEGER PRIMARY KEY,
                  mitgliedsnummer   TEXT UNIQUE,
                  vorname           TEXT NOT NULL,
                  nachname          TEXT NOT NULL,
                  geburtsdatum      TEXT,
                  strasse           TEXT,
                  plz               TEXT,
                  ort               TEXT,
                  land              TEXT,
                  email             TEXT,
                  telefon           TEXT,

                  eintrittsdatum    TEXT,
                  austrittsdatum    TEXT,
                  status            TEXT NOT NULL DEFAULT 'aktiv',

                  zahlungsart       TEXT NOT NULL,
                  iban              TEXT,
                  bic               TEXT,
                  kontoinhaber      TEXT,
                  abgerechnet_bis   TEXT,

                  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT
                )
                """
            )

            # Tabelle 2: abteilung
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS abteilung (
                  id            INTEGER PRIMARY KEY,
                  name          TEXT NOT NULL,
                  kuerzel       TEXT,
                  beschreibung  TEXT,
                  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by    TEXT,
                  updated_at    TEXT,
                  updated_by    TEXT
                )
                """
            )

            # Tabelle 2a: mitglied_abteilung
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_abteilung (
                  id             INTEGER PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL,
                  abteilung_id   INTEGER NOT NULL,
                  status         TEXT NOT NULL DEFAULT 'standard',
                  von            TEXT,
                  bis            TEXT,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  FOREIGN KEY (mitglied_id)  REFERENCES mitglied(id),
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

            # Tabelle 3: beitragsregel
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitragsregel (
                  id             INTEGER PRIMARY KEY,
                  name           TEXT NOT NULL,
                  abteilung_id   INTEGER,
                  betrag         REAL NOT NULL,
                  periode        TEXT NOT NULL,
                  gueltig_ab     TEXT NOT NULL,
                  bedingung_raw  TEXT,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

            # Tabelle 4: beitrag_sollstellung
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitrag_sollstellung (
                  id               INTEGER PRIMARY KEY,
                  mitglied_id      INTEGER NOT NULL,
                  beitragsregel_id INTEGER NOT NULL,
                  jahr             INTEGER NOT NULL,
                  betrag_soll      REAL NOT NULL,
                  faellig_am       TEXT NOT NULL,
                  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by       TEXT,
                  updated_at       TEXT,
                  updated_by       TEXT,
                  FOREIGN KEY (mitglied_id)      REFERENCES mitglied(id),
                  FOREIGN KEY (beitragsregel_id) REFERENCES beitragsregel(id)
                )
                """
            )

            # Audit-Log-Tabelle
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                  id           INTEGER PRIMARY KEY,
                  table_name   TEXT NOT NULL,
                  record_pk    INTEGER NOT NULL,
                  operation    TEXT NOT NULL,
                  changed_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  changed_by   TEXT,
                  old_data     TEXT,
                  new_data     TEXT
                )
                """
            )

            # Hier könntest du direkt noch Trigger hinzufügen (später Schritt)

        self._set_schema_version(1)
    
    # -----------------------------------
    # Migration 1 -> 2
    # -----------------------------------
    def _migrate_1_to_2(self):
        """Version-Spalte + History-Tabellen für alle Haupttabellen."""
        with self.cursor() as cur:
            # 1) version-Spalten ergänzen (falls noch nicht vorhanden)
            # SQLite kennt IF NOT EXISTS bei ALTER TABLE ADD COLUMN nicht,
            # daher hier simpel und idempotent: Fehler ignorieren.
            for table in [
                "mitglied",
                "abteilung",
                "mitglied_abteilung",
                "beitragsregel",
                "beitrag_sollstellung",
            ]:
                try:
                    cur.execute(
                        f"ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                    )
                except sqlite3.OperationalError:
                    # Spalte existiert bereits -> ignorieren
                    pass

            # 2) History-Tabellen anlegen

            # mitglied_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  mitgliedsnummer   TEXT,
                  vorname           TEXT,
                  nachname          TEXT,
                  geburtsdatum      TEXT,
                  strasse           TEXT,
                  plz               TEXT,
                  ort               TEXT,
                  land              TEXT,
                  email             TEXT,
                  telefon           TEXT,

                  eintrittsdatum    TEXT,
                  austrittsdatum    TEXT,
                  status            TEXT,

                  zahlungsart       TEXT,
                  iban              TEXT,
                  bic               TEXT,
                  kontoinhaber      TEXT,
                  abgerechnet_bis   TEXT,

                  created_at        TEXT,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT,

                  history_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  history_created_by TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # abteilung_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS abteilung_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  name              TEXT,
                  kuerzel           TEXT,
                  beschreibung      TEXT,

                  created_at        TEXT,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT,

                  history_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  history_created_by TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # mitglied_abteilung_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_abteilung_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  mitglied_id       INTEGER,
                  abteilung_id      INTEGER,
                  status            TEXT,
                  von               TEXT,
                  bis               TEXT,

                  created_at        TEXT,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT,

                  history_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  history_created_by TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # beitragsregel_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitragsregel_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  name              TEXT,
                  abteilung_id      INTEGER,
                  betrag            REAL,
                  periode           TEXT,
                  gueltig_ab        TEXT,
                  bedingung_raw     TEXT,

                  created_at        TEXT,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT,

                  history_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  history_created_by TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # beitrag_sollstellung_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitrag_sollstellung_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  mitglied_id       INTEGER,
                  beitragsregel_id  INTEGER,
                  jahr              INTEGER,
                  betrag_soll       REAL,
                  faellig_am        TEXT,

                  created_at        TEXT,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT,

                  history_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  history_created_by TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

        self._set_schema_version(2)
    
    def _migrate_2_to_3(self):
        """Entfernt die alte audit_log-Tabelle, die nicht mehr verwendet wird."""
        with self.cursor() as cur:
            try:
                cur.execute("DROP TABLE IF EXISTS audit_log")
            except sqlite3.OperationalError:
                # falls sie nie existiert hat oder schon weg ist
                pass

        self._set_schema_version(3)
