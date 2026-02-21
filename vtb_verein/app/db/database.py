'''
Created on 21.02.2026

Database connection and schema management.

@author: AI Assistant
'''

import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 1  # Alles in migrate_0_to_1, da noch kein Produktivbetrieb


class Database:
    """Manages database connection, schema versioning, and migrations.
    
    This class handles:
    - Database connection lifecycle
    - Schema version tracking
    - Schema migrations
    - Connection configuration
    """
    
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema_version_table()
        self._migrate_schema_if_needed()
    
    @contextmanager
    def cursor(self):
        """Context manager for cursor with automatic commit/rollback."""
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
        """Close the database connection."""
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
        """Initiales Schema: Alle Tabellen inkl. Users + History-Trigger + Soft-Delete."""
        with self.cursor() as cur:
            # ============================================
            # Tabelle 1: mitglied
            # ============================================
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied (
                  id                INTEGER PRIMARY KEY,
                  mitgliedsnummer   INTEGER UNIQUE,
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
                  updated_by        TEXT,
                  deleted_at        TEXT,
                  deleted_by        TEXT
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_history (
                  id                INTEGER NOT NULL,
                  version           INTEGER NOT NULL,

                  mitgliedsnummer   INTEGER,
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
                  deleted_at        TEXT,
                  deleted_by        TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # ============================================
            # Tabelle 2: abteilung
            # ============================================
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
                  updated_by    TEXT,
                  deleted_at    TEXT,
                  deleted_by    TEXT
                )
                """
            )

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
                  deleted_at        TEXT,
                  deleted_by        TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # Trigger für abteilung: INSERT
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS abteilung_audit_insert
                AFTER INSERT ON abteilung
                FOR EACH ROW
                BEGIN
                    INSERT INTO abteilung_history (
                        id, version, name, kuerzel, beschreibung,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # Trigger für abteilung: UPDATE (nur wenn Version sich ändert)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS abteilung_audit_update
                AFTER UPDATE ON abteilung
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO abteilung_history (
                        id, version, name, kuerzel, beschreibung,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # Trigger für abteilung: DELETE (falls jemals hard delete)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS abteilung_audit_delete
                AFTER DELETE ON abteilung
                FOR EACH ROW
                BEGIN
                    INSERT INTO abteilung_history (
                        id, version, name, kuerzel, beschreibung,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        OLD.id, OLD.version, OLD.name, OLD.kuerzel, OLD.beschreibung,
                        OLD.created_at, OLD.created_by, OLD.updated_at, OLD.updated_by,
                        OLD.deleted_at, OLD.deleted_by
                    );
                END;
            """)

            # ============================================
            # Tabelle 2a: mitglied_abteilung
            # ============================================
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mitglied_abteilung (
                  id             INTEGER PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL,
                  abteilung_id   INTEGER NOT NULL,
                  status         TEXT NOT NULL DEFAULT 'aktiv',
                  von            TEXT,
                  bis            TEXT,

                  version        INTEGER NOT NULL DEFAULT 1,

                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT,
                  FOREIGN KEY (mitglied_id)  REFERENCES mitglied(id),
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

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
                  deleted_at     TEXT,
                  deleted_by     TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # Trigger für mitglied_abteilung: INSERT
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS mitglied_abteilung_audit_insert
                AFTER INSERT ON mitglied_abteilung
                FOR EACH ROW
                BEGIN
                    INSERT INTO mitglied_abteilung_history (
                        id, version, mitglied_id, abteilung_id, status, von, bis,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # Trigger für mitglied_abteilung: UPDATE (nur wenn Version sich ändert)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS mitglied_abteilung_audit_update
                AFTER UPDATE ON mitglied_abteilung
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO mitglied_abteilung_history (
                        id, version, mitglied_id, abteilung_id, status, von, bis,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # Trigger für mitglied_abteilung: DELETE (falls jemals hard delete)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS mitglied_abteilung_audit_delete
                AFTER DELETE ON mitglied_abteilung
                FOR EACH ROW
                BEGIN
                    INSERT INTO mitglied_abteilung_history (
                        id, version, mitglied_id, abteilung_id, status, von, bis,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        OLD.id, OLD.version, OLD.mitglied_id, OLD.abteilung_id, OLD.status, OLD.von, OLD.bis,
                        OLD.created_at, OLD.created_by, OLD.updated_at, OLD.updated_by,
                        OLD.deleted_at, OLD.deleted_by
                    );
                END;
            """)

            # ============================================
            # Tabelle 3: beitragsregel
            # ============================================
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
                  deleted_at     TEXT,
                  deleted_by     TEXT,
                  FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
                """
            )

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
                  deleted_at     TEXT,
                  deleted_by     TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # ============================================
            # Tabelle 4: beitrag_sollstellung
            # ============================================
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS beitrag_sollstellung (
                  id               INTEGER PRIMARY KEY,
                  mitglied_id      INTEGER NOT NULL,
                  beitragsregel_id INTEGER NOT NULL,
                  zeitraum         TEXT NOT NULL,
                  betrag_soll      REAL NOT NULL,

                  version          INTEGER NOT NULL DEFAULT 1,

                  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by       TEXT,
                  updated_at       TEXT,
                  updated_by       TEXT,
                  deleted_at       TEXT,
                  deleted_by       TEXT,
                  FOREIGN KEY (mitglied_id)      REFERENCES mitglied(id),
                  FOREIGN KEY (beitragsregel_id) REFERENCES beitragsregel(id)
                )
                """
            )

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
                  deleted_at       TEXT,
                  deleted_by       TEXT,

                  PRIMARY KEY (id, version)
                )
                """
            )

            # ============================================
            # Tabelle 5: users
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'readonly')),
                    active INTEGER NOT NULL DEFAULT 1,
                    last_login TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT NOT NULL,
                    deleted_at TEXT,
                    deleted_by TEXT
                )
            """)
            
            # Indices für Performance
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users_history (
                    id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    last_login TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    deleted_at TEXT,
                    deleted_by TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_history_id ON users_history(id)")

            # Trigger für users: INSERT
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS users_audit_insert
                AFTER INSERT ON users
                FOR EACH ROW
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.created_at,
                        NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # Trigger für users: UPDATE (nur wenn Version sich ändert!)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS users_audit_update
                AFTER UPDATE ON users
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.created_at,
                        NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            
            # Trigger für users: DELETE (falls jemals hard delete)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS users_audit_delete
                AFTER DELETE ON users
                FOR EACH ROW
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        OLD.id, OLD.version, OLD.username, OLD.email, OLD.password_hash, OLD.role,
                        OLD.active, OLD.last_login, OLD.created_at,
                        OLD.created_by, OLD.updated_at, OLD.updated_by,
                        OLD.deleted_at, OLD.deleted_by
                    );
                END;
            """)

            # Erstelle Standard-Admin wenn keine User existieren
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                import bcrypt
                default_password = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                cur.execute("""
                    INSERT INTO users (username, email, password_hash, role, active, created_by, updated_by)
                    VALUES (?, ?, ?, 'admin', 1, 'SYSTEM', 'SYSTEM')
                """, ('admin', 'admin@verein.local', default_password))
                
                print("⚠️  Standard-Admin erstellt: Username='admin', Passwort='admin123' - BITTE ÄNDERN!")

        self._set_schema_version(1)
