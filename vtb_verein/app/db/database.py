'''
Created on 21.02.2026

Database connection and schema management.

@author: AI Assistant
'''

import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 5  # Version 5: user_permissions Tabelle für Permission-Matrix


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
        if current == 1:
            self._migrate_1_to_2()
            current = 2
        if current == 2:
            self._migrate_2_to_3()
            current = 3
        if current == 3:
            self._migrate_3_to_4()
            current = 4
        if current == 4:
            self._migrate_4_to_5()
            current = 5

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

    def _migrate_1_to_2(self):
        """Migration 1->2: History-Trigger für mitglied hinzufügen, DELETE-Trigger entfernen."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS mitglied_audit_insert
                AFTER INSERT ON mitglied
                FOR EACH ROW
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land, email, telefon,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land, NEW.email, NEW.telefon,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS mitglied_audit_update
                AFTER UPDATE ON mitglied
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land, email, telefon,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land, NEW.email, NEW.telefon,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            # Hard-Delete ist nur für Prune-Funktionen, soll nicht in History
            cur.execute("DROP TRIGGER IF EXISTS mitglied_audit_delete")
            cur.execute("DROP TRIGGER IF EXISTS abteilung_audit_delete")
            cur.execute("DROP TRIGGER IF EXISTS mitglied_abteilung_audit_delete")
            cur.execute("DROP TRIGGER IF EXISTS users_audit_delete")
        self._set_schema_version(2)

    def _migrate_2_to_3(self):
        """Migration 2->3: Rolle 'special' zur users-Tabelle hinzufügen."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'readonly', 'special')),
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
            cur.execute("INSERT INTO users_new SELECT * FROM users")
            cur.execute("DROP TABLE users")
            cur.execute("ALTER TABLE users_new RENAME TO users")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at)")
            cur.execute("""
                CREATE TRIGGER users_audit_insert
                AFTER INSERT ON users
                FOR EACH ROW
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.created_at, NEW.created_by,
                        NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER users_audit_update
                AFTER UPDATE ON users
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.created_at, NEW.created_by,
                        NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
        self._set_schema_version(3)

    def _migrate_3_to_4(self):
        """Migration 3->4: auth_tokens Tabelle für Magic-Link-Authentication."""
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                  id            INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id       INTEGER NOT NULL,
                  token         TEXT UNIQUE NOT NULL,
                  token_type    TEXT NOT NULL CHECK(token_type IN ('magic_link', 'remember_me')),
                  expires_at    TEXT NOT NULL,
                  used_at       TEXT,
                  version       INTEGER NOT NULL DEFAULT 1,
                  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_token ON auth_tokens(token)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_token_type ON auth_tokens(token_type)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens_history (
                  id            INTEGER NOT NULL,
                  version       INTEGER NOT NULL,
                  user_id       INTEGER NOT NULL,
                  token         TEXT NOT NULL,
                  token_type    TEXT NOT NULL,
                  expires_at    TEXT NOT NULL,
                  used_at       TEXT,
                  created_at    TEXT NOT NULL,
                  PRIMARY KEY (id, version)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_history_id ON auth_tokens_history(id)")
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS auth_tokens_audit_insert
                AFTER INSERT ON auth_tokens
                FOR EACH ROW
                BEGIN
                    INSERT INTO auth_tokens_history (
                        id, version, user_id, token, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS auth_tokens_audit_update
                AFTER UPDATE ON auth_tokens
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO auth_tokens_history (
                        id, version, user_id, token, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                END;
            """)
            # KEIN DELETE-Trigger - Token-Cleanup soll nicht in History landen
        self._set_schema_version(4)

    def _migrate_4_to_5(self):
        """Migration 4->5: user_permissions Tabelle für Permission-Matrix.

        Änderungen:
        1. Neue Tabelle user_permissions mit Soft-Delete und Versionierung
        2. Neue Tabelle user_permissions_history
        3. Trigger für INSERT/UPDATE (kein DELETE - Prune soll nicht getrackt werden)
        4. Standard-Permissions für bestehende Users nach Rolle setzen
        """
        from app.models.permission import Permission

        with self.cursor() as cur:
            # ============================================
            # Tabelle: user_permissions
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_permissions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    permission  TEXT NOT NULL,

                    version     INTEGER NOT NULL DEFAULT 1,

                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by  TEXT NOT NULL,
                    deleted_at  TEXT,
                    deleted_by  TEXT,

                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE (user_id, permission)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_user_id ON user_permissions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_permission ON user_permissions(permission)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_deleted_at ON user_permissions(deleted_at)")

            # ============================================
            # Tabelle: user_permissions_history
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_permissions_history (
                    id          INTEGER NOT NULL,
                    version     INTEGER NOT NULL,

                    user_id     INTEGER NOT NULL,
                    permission  TEXT NOT NULL,

                    created_at  TEXT NOT NULL,
                    created_by  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    updated_by  TEXT NOT NULL,
                    deleted_at  TEXT,
                    deleted_by  TEXT,

                    PRIMARY KEY (id, version)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_permissions_history_id ON user_permissions_history(id)")

            # ============================================
            # Trigger: INSERT
            # ============================================
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS user_permissions_audit_insert
                AFTER INSERT ON user_permissions
                FOR EACH ROW
                BEGIN
                    INSERT INTO user_permissions_history (
                        id, version, user_id, permission,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # ============================================
            # Trigger: UPDATE (nur bei Versions-Änderung)
            # ============================================
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS user_permissions_audit_update
                AFTER UPDATE ON user_permissions
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO user_permissions_history (
                        id, version, user_id, permission,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            # KEIN DELETE-Trigger - Prune soll nicht in History landen

            # ============================================
            # Bestehende Users mit Default-Permissions befüllen
            # ============================================
            cur.execute("SELECT id, role FROM users WHERE deleted_at IS NULL")
            existing_users = cur.fetchall()
            now = 'CURRENT_TIMESTAMP'
            for row in existing_users:
                user_id = row['id']
                role = row['role']
                # 'special' auf 'readonly' mappen für Default-Permissions
                effective_role = role if role in ('admin', 'user', 'readonly') else 'readonly'
                permissions = Permission.defaults_for_role(effective_role)
                for perm in permissions:
                    cur.execute("""
                        INSERT OR IGNORE INTO user_permissions
                            (user_id, permission, created_by, updated_by)
                        VALUES (?, ?, 'MIGRATION_4_5', 'MIGRATION_4_5')
                    """, (user_id, perm))

        self._set_schema_version(5)
