'''
Created on 07.02.2026

@author: volker
'''

import sqlite3
from contextlib import contextmanager
from app.models.abteilung import Abteilung

SCHEMA_VERSION = 1  # initialer Stand


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

    def get_abteilung(self, id: int) -> Abteilung:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ?
                """,
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Abteilung {id} nicht gefunden")
            return Abteilung(**dict(row))

    def list_abteilungen(self) -> list[Abteilung]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                ORDER BY name
                """
            )
            return [Abteilung(**dict(row)) for row in cur.fetchall()]

    def create_abteilung(self, abt: Abteilung, created_by: str) -> Abteilung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO abteilung (name, kuerzel, beschreibung, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (abt.name, abt.kuerzel, abt.beschreibung, created_by, created_by),
            )
            abt.id = cur.lastrowid
    
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ?
                """,
                (abt.id,),
            )
            row = cur.fetchone()
            abt_db = Abteilung(**dict(row))
    
            # erster History-Eintrag (Version 1)
            cur.execute(
                """
                INSERT INTO abteilung_history
                (id, version, name, kuerzel, beschreibung,
                 created_at, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    abt_db.id,
                    abt_db.version,
                    abt_db.name,
                    abt_db.kuerzel,
                    abt_db.beschreibung,
                    abt_db.created_at,
                    abt_db.created_by,
                    abt_db.updated_at,
                    abt_db.updated_by,
                ),
            )
    
            return abt_db

    def update_abteilung(self, abt: Abteilung, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE abteilung
                SET name = ?, kuerzel = ?, beschreibung = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND version = ?
                """,
                (abt.name, abt.kuerzel, abt.beschreibung,
                 updated_by, abt.id, abt.version),
            )
            if cur.rowcount == 0:
                return False
    
            # neuen Stand holen
            cur.execute(
                """
                SELECT id, name, kuerzel, beschreibung,
                       version, created_at, created_by, updated_at, updated_by
                FROM abteilung
                WHERE id = ?
                """,
                (abt.id,),
            )
            row = cur.fetchone()
            new_row = dict(row)
    
            # History-Eintrag mit neuem Stand
            cur.execute(
                """
                INSERT INTO abteilung_history
                (id, version, name, kuerzel, beschreibung,
                 created_at, created_by, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_row["id"],
                    new_row["version"],
                    new_row["name"],
                    new_row["kuerzel"],
                    new_row["beschreibung"],
                    new_row["created_at"],
                    new_row["created_by"],
                    new_row["updated_at"],
                    new_row["updated_by"],
                ),
            )
    
            abt.version = new_row["version"]
            abt.updated_at = new_row["updated_at"]
            abt.updated_by = updated_by
            return True
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
                "UPDATE schema_version "
                "SET version = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = 1",
                (version,),
            )

    def _migrate_schema_if_needed(self):
        current = self._get_schema_version()
        if current == 0:
            self._migrate_0_to_1()
            current = 1

        if current != SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema-Version {current} gefunden, "
                f"erwartet {SCHEMA_VERSION}. Bitte Migration erweitern."
            )

    # -----------------------------------
    # Migrationen
    # -----------------------------------
    def _migrate_0_to_1(self):
        """Initiales Schema: Tabellen 1, 2, 2a, 3, 4 + History-Tabellen."""
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

                  version           INTEGER NOT NULL DEFAULT 1,

                  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by        TEXT,
                  updated_at        TEXT,
                  updated_by        TEXT
                )
                """
            )

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

                  PRIMARY KEY (id, version)
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

                  version       INTEGER NOT NULL DEFAULT 1,

                  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by    TEXT,
                  updated_at    TEXT,
                  updated_by    TEXT
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

                  PRIMARY KEY (id, version)
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

                  version        INTEGER NOT NULL DEFAULT 1,

                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  FOREIGN KEY (mitglied_id)  REFERENCES mitglied(id),
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

            # mitglied_abteilung_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_abteilung_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,

                  mitglied_id    INTEGER,
                  abteilung_id   INTEGER,
                  status         TEXT,
                  von            TEXT,
                  bis            TEXT,

                  created_at     TEXT,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,

                  PRIMARY KEY (id, version)
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
                  gueltig_bis    TEXT,
                  bedingung_raw  TEXT,

                  version        INTEGER NOT NULL DEFAULT 1,

                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

            # beitragsregel_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitragsregel_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,

                  name           TEXT,
                  abteilung_id   INTEGER,
                  betrag         REAL,
                  periode        TEXT,
                  gueltig_ab     TEXT,
                  gueltig_bis    TEXT,
                  bedingung_raw  TEXT,

                  created_at     TEXT,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # Tabelle 4: beitrag_sollstellung
            # direkt mit 'zeitraum' statt 'jahr' + 'faellig_am'
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitrag_sollstellung (
                  id               INTEGER PRIMARY KEY,
                  mitglied_id      INTEGER NOT NULL,
                  beitragsregel_id INTEGER NOT NULL,
                  zeitraum         TEXT NOT NULL,   -- z.B. '202600', '202601', '202641'
                  betrag_soll      REAL NOT NULL,

                  version          INTEGER NOT NULL DEFAULT 1,

                  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by       TEXT,
                  updated_at       TEXT,
                  updated_by       TEXT,
                  FOREIGN KEY (mitglied_id)      REFERENCES mitglied(id),
                  FOREIGN KEY (beitragsregel_id) REFERENCES beitragsregel(id)
                )
                """
            )

            # beitrag_sollstellung_history
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitrag_sollstellung_history (
                  id               INTEGER NOT NULL,
                  version          INTEGER NOT NULL,

                  mitglied_id      INTEGER,
                  beitragsregel_id INTEGER,
                  zeitraum         TEXT,
                  betrag_soll      REAL,

                  created_at       TEXT,
                  created_by       TEXT,
                  updated_at       TEXT,
                  updated_by       TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

        self._set_schema_version(1)
