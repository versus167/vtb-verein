'''
Created on 21.02.2026

Database connection and schema management.

@author: AI Assistant
'''

import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 10  # Version 10: Ticket-Permissions


class Database:
    """Manages database connection, schema versioning, and migrations."""

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
        if current == 5:
            self._migrate_5_to_6()
            current = 6
        if current == 6:
            self._migrate_6_to_7()
            current = 7
        if current == 7:
            self._migrate_7_to_8()
            current = 8
        if current == 8:
            self._migrate_8_to_9()
            current = 9
        if current == 9:
            self._migrate_9_to_10()
            current = 10

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
                CREATE TRIGGER users_audit_update
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
        self._set_schema_version(4)

    def _migrate_4_to_5(self):
        """Migration 4->5: user_permissions Tabelle für Permission-Matrix."""
        _DEFAULTS_V5 = {
            'admin': {
                'mitglieder.read', 'mitglieder.write', 'mitglieder.delete',
                'abteilungen.read', 'abteilungen.write', 'abteilungen.delete',
                'beitraege.read', 'beitraege.write',
                'berichte.read', 'berichte.export',
                'users.read', 'users.manage',
                'system.config',
            },
            'user': {
                'mitglieder.read', 'mitglieder.write', 'mitglieder.delete',
                'abteilungen.read', 'abteilungen.write', 'abteilungen.delete',
                'beitraege.read', 'beitraege.write',
                'berichte.read', 'berichte.export',
                'users.read',
            },
            'readonly': {
                'mitglieder.read',
                'abteilungen.read',
                'beitraege.read',
                'berichte.read',
            },
        }

        with self.cursor() as cur:
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
            cur.execute("SELECT id, role FROM users WHERE deleted_at IS NULL")
            existing_users = cur.fetchall()
            for row in existing_users:
                user_id = row['id']
                role = row['role']
                effective_role = role if role in _DEFAULTS_V5 else 'readonly'
                for perm in _DEFAULTS_V5[effective_role]:
                    cur.execute("""
                        INSERT OR IGNORE INTO user_permissions
                            (user_id, permission, created_by, updated_by)
                        VALUES (?, ?, 'MIGRATION_4_5', 'MIGRATION_4_5')
                    """, (user_id, perm))

        self._set_schema_version(5)

    def _migrate_5_to_6(self):
        """Migration 5->6: Kassenbuch-Tabellen."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                    TEXT NOT NULL,
                    beschreibung            TEXT,
                    anfangsbestand_cent     INTEGER NOT NULL DEFAULT 0,
                    abteilung_id            INTEGER,
                    version                 INTEGER NOT NULL DEFAULT 1,
                    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by              TEXT NOT NULL,
                    updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by              TEXT NOT NULL,
                    deleted_at              TEXT,
                    deleted_by              TEXT,
                    FOREIGN KEY (abteilung_id) REFERENCES abteilung(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_deleted_at ON kassen(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassen_abteilung_id ON kassen(abteilung_id)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassen_history (
                    id                      INTEGER NOT NULL,
                    version                 INTEGER NOT NULL,
                    name                    TEXT,
                    beschreibung            TEXT,
                    anfangsbestand_cent     INTEGER,
                    abteilung_id            INTEGER,
                    created_at              TEXT,
                    created_by              TEXT,
                    updated_at              TEXT,
                    updated_by              TEXT,
                    deleted_at              TEXT,
                    deleted_by              TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kassen_audit_insert
                AFTER INSERT ON kassen
                FOR EACH ROW
                BEGIN
                    INSERT INTO kassen_history (
                        id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent,
                        NEW.abteilung_id, NEW.created_at, NEW.created_by, NEW.updated_at,
                        NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kassen_audit_update
                AFTER UPDATE ON kassen
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO kassen_history (
                        id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent,
                        NEW.abteilung_id, NEW.created_at, NEW.created_by, NEW.updated_at,
                        NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassenbuchungen (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    kasse_id                    INTEGER NOT NULL,
                    buchungsdatum               TEXT NOT NULL,
                    belegnummer                 TEXT NOT NULL,
                    buchungstext                TEXT NOT NULL,
                    kategorie                   TEXT NOT NULL,
                    einnahme_cent               INTEGER NOT NULL DEFAULT 0,
                    ausgabe_cent                INTEGER NOT NULL DEFAULT 0,
                    notiz                       TEXT,
                    exportiert_in_export_id     INTEGER,
                    version                     INTEGER NOT NULL DEFAULT 1,
                    created_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by                  TEXT NOT NULL,
                    updated_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by                  TEXT NOT NULL,
                    deleted_at                  TEXT,
                    deleted_by                  TEXT,
                    FOREIGN KEY (kasse_id) REFERENCES kassen(id),
                    FOREIGN KEY (exportiert_in_export_id) REFERENCES kassenbuch_exporte(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_kasse_id ON kassenbuchungen(kasse_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_buchungsdatum ON kassenbuchungen(buchungsdatum)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_deleted_at ON kassenbuchungen(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_export_id ON kassenbuchungen(exportiert_in_export_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_belegnummer ON kassenbuchungen(kasse_id, belegnummer)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassenbuchungen_history (
                    id                          INTEGER NOT NULL,
                    version                     INTEGER NOT NULL,
                    kasse_id                    INTEGER,
                    buchungsdatum               TEXT,
                    belegnummer                 TEXT,
                    buchungstext                TEXT,
                    kategorie                   TEXT,
                    einnahme_cent               INTEGER,
                    ausgabe_cent                INTEGER,
                    notiz                       TEXT,
                    exportiert_in_export_id     INTEGER,
                    created_at                  TEXT,
                    created_by                  TEXT,
                    updated_at                  TEXT,
                    updated_by                  TEXT,
                    deleted_at                  TEXT,
                    deleted_by                  TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuchungen_history_id ON kassenbuchungen_history(id)")
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kassenbuchungen_audit_insert
                AFTER INSERT ON kassenbuchungen
                FOR EACH ROW
                BEGIN
                    INSERT INTO kassenbuchungen_history (
                        id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                        kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                        NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                        NEW.notiz, NEW.exportiert_in_export_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kassenbuchungen_audit_update
                AFTER UPDATE ON kassenbuchungen
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO kassenbuchungen_history (
                        id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                        kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                        NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                        NEW.notiz, NEW.exportiert_in_export_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassenbuch_exporte (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    kasse_id            INTEGER NOT NULL,
                    zeitraum_von        TEXT NOT NULL,
                    zeitraum_bis        TEXT NOT NULL,
                    exportiert_am       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    exportiert_von      TEXT NOT NULL,
                    dateiname           TEXT NOT NULL,
                    anzahl_buchungen    INTEGER NOT NULL,
                    version             INTEGER NOT NULL DEFAULT 1,
                    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by          TEXT NOT NULL,
                    deleted_at          TEXT,
                    deleted_by          TEXT,
                    FOREIGN KEY (kasse_id) REFERENCES kassen(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuch_exporte_kasse_id ON kassenbuch_exporte(kasse_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kassenbuch_exporte_zeitraum ON kassenbuch_exporte(zeitraum_von, zeitraum_bis)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kassenbuch_exporte_history (
                    id                  INTEGER NOT NULL,
                    version             INTEGER NOT NULL,
                    kasse_id            INTEGER,
                    zeitraum_von        TEXT,
                    zeitraum_bis        TEXT,
                    exportiert_am       TEXT,
                    exportiert_von      TEXT,
                    dateiname           TEXT,
                    anzahl_buchungen    INTEGER,
                    created_at          TEXT,
                    created_by          TEXT,
                    deleted_at          TEXT,
                    deleted_by          TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kassenbuch_exporte_audit_insert
                AFTER INSERT ON kassenbuch_exporte
                FOR EACH ROW
                BEGIN
                    INSERT INTO kassenbuch_exporte_history (
                        id, version, kasse_id, zeitraum_von, zeitraum_bis,
                        exportiert_am, exportiert_von, dateiname, anzahl_buchungen,
                        created_at, created_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.zeitraum_von, NEW.zeitraum_bis,
                        NEW.exportiert_am, NEW.exportiert_von, NEW.dateiname, NEW.anzahl_buchungen,
                        NEW.created_at, NEW.created_by, NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
        self._set_schema_version(6)

    def _migrate_6_to_7(self):
        """Migration 6->7: Kassenbuch-Permissions für bestehende User (vorläufig, wird in v8 entfernt)."""
        _KASSE_PERMS_V7 = {
            'admin':    {'kasse.read', 'kasse.write', 'kasse.delete', 'kasse.export'},
            'user':     {'kasse.read', 'kasse.write', 'kasse.delete', 'kasse.export'},
            'readonly': {'kasse.read'},
            'special':  {'kasse.read'},
        }
        with self.cursor() as cur:
            cur.execute("SELECT id, role FROM users WHERE deleted_at IS NULL")
            existing_users = cur.fetchall()
            for row in existing_users:
                user_id = row['id']
                role = row['role']
                perms = _KASSE_PERMS_V7.get(role, {'kasse.read'})
                for perm in perms:
                    cur.execute("""
                        INSERT OR IGNORE INTO user_permissions
                            (user_id, permission, created_by, updated_by)
                        VALUES (?, ?, 'MIGRATION_6_7', 'MIGRATION_6_7')
                    """, (user_id, perm))
        self._set_schema_version(7)

    def _migrate_7_to_8(self):
        """Migration 7->8: Kassenspezifische Berechtigungen (kasse_berechtigungen).

        Änderungen:
        1. Neue Tabelle kasse_berechtigungen mit Soft-Delete und Versionierung
        2. Neue Tabelle kasse_berechtigungen_history + INSERT/UPDATE-Trigger
        3. Globale kasse.*-Permissions aus user_permissions entfernen (Soft-Delete)
        4. Admins erhalten automatisch alle Rechte für bestehende Kassen

        HINWEIS: kasse.*-Permissions werden per Soft-Delete entfernt (deleted_at setzen),
        nicht per Hard-Delete, damit die History erhalten bleibt.
        """
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kasse_berechtigungen (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    kasse_id        INTEGER NOT NULL,
                    user_id         INTEGER NOT NULL,
                    darf_lesen      INTEGER NOT NULL DEFAULT 0,
                    darf_schreiben  INTEGER NOT NULL DEFAULT 0,
                    darf_exportieren INTEGER NOT NULL DEFAULT 0,

                    version         INTEGER NOT NULL DEFAULT 1,

                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by      TEXT NOT NULL,
                    deleted_at      TEXT,
                    deleted_by      TEXT,

                    FOREIGN KEY (kasse_id) REFERENCES kassen(id),
                    FOREIGN KEY (user_id)  REFERENCES users(id),
                    UNIQUE (kasse_id, user_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kasse_berechtigungen_kasse_id ON kasse_berechtigungen(kasse_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kasse_berechtigungen_user_id ON kasse_berechtigungen(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kasse_berechtigungen_deleted_at ON kasse_berechtigungen(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS kasse_berechtigungen_history (
                    id              INTEGER NOT NULL,
                    version         INTEGER NOT NULL,

                    kasse_id        INTEGER,
                    user_id         INTEGER,
                    darf_lesen      INTEGER,
                    darf_schreiben  INTEGER,
                    darf_exportieren INTEGER,

                    created_at      TEXT,
                    created_by      TEXT,
                    updated_at      TEXT,
                    updated_by      TEXT,
                    deleted_at      TEXT,
                    deleted_by      TEXT,

                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kasse_berechtigungen_history_id ON kasse_berechtigungen_history(id)")

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kasse_berechtigungen_audit_insert
                AFTER INSERT ON kasse_berechtigungen
                FOR EACH ROW
                BEGIN
                    INSERT INTO kasse_berechtigungen_history (
                        id, version, kasse_id, user_id,
                        darf_lesen, darf_schreiben, darf_exportieren,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS kasse_berechtigungen_audit_update
                AFTER UPDATE ON kasse_berechtigungen
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO kasse_berechtigungen_history (
                        id, version, kasse_id, user_id,
                        darf_lesen, darf_schreiben, darf_exportieren,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            cur.execute("""
                UPDATE user_permissions
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = 'MIGRATION_7_8',
                    version    = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = 'MIGRATION_7_8'
                WHERE permission IN ('kasse.read', 'kasse.write', 'kasse.delete', 'kasse.export')
                  AND deleted_at IS NULL
            """)

            cur.execute("SELECT id FROM kassen WHERE deleted_at IS NULL")
            kassen = cur.fetchall()
            cur.execute("SELECT id FROM users WHERE role = 'admin' AND deleted_at IS NULL AND active = 1")
            admins = cur.fetchall()
            for kasse in kassen:
                for admin in admins:
                    cur.execute("""
                        INSERT OR IGNORE INTO kasse_berechtigungen
                            (kasse_id, user_id, darf_lesen, darf_schreiben, darf_exportieren,
                             created_by, updated_by)
                        VALUES (?, ?, 1, 1, 1, 'MIGRATION_7_8', 'MIGRATION_7_8')
                    """, (kasse['id'], admin['id']))

        self._set_schema_version(8)

    def _migrate_8_to_9(self):
        """Migration 8->9: Ticket-System.

        Neue Tabellen:
        - ticket_bereiche      (Ortsbereiche: Platz 1, Kabinen, ...)
        - ticket_kategorien    (Schadensarten: Schaden, Sicherheit, ...)
        - tickets              (Haupttabelle)
        - ticket_kommentare    (oeffentlich + intern)
        - ticket_anhaenge      (Datei-Referenzen, stored_name = att_{id:06d}.ext)
        - ticket_teilnehmer    (Beobachter/Helfer, keine History noetig)

        History-Trigger: tickets + ticket_kommentare (INSERT + UPDATE, kein DELETE)
        Keine History fuer ticket_anhaenge und ticket_teilnehmer.
        """
        with self.cursor() as cur:

            # ============================================
            # ticket_bereiche
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_bereiche (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    beschreibung    TEXT,
                    version         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by      TEXT NOT NULL,
                    deleted_at      TEXT,
                    deleted_by      TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_bereiche_deleted_at ON ticket_bereiche(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_bereiche_history (
                    id              INTEGER NOT NULL,
                    version         INTEGER NOT NULL,
                    name            TEXT,
                    beschreibung    TEXT,
                    created_at      TEXT,
                    created_by      TEXT,
                    updated_at      TEXT,
                    updated_by      TEXT,
                    deleted_at      TEXT,
                    deleted_by      TEXT,
                    PRIMARY KEY (id, version)
                )
            """)

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_bereiche_audit_insert
                AFTER INSERT ON ticket_bereiche
                FOR EACH ROW
                BEGIN
                    INSERT INTO ticket_bereiche_history (
                        id, version, name, beschreibung,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_bereiche_audit_update
                AFTER UPDATE ON ticket_bereiche
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO ticket_bereiche_history (
                        id, version, name, beschreibung,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            # Kein DELETE-Trigger fuer ticket_bereiche

            # ============================================
            # ticket_kategorien
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_kategorien (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    icon            TEXT,
                    version         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by      TEXT NOT NULL,
                    deleted_at      TEXT,
                    deleted_by      TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_kategorien_deleted_at ON ticket_kategorien(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_kategorien_history (
                    id              INTEGER NOT NULL,
                    version         INTEGER NOT NULL,
                    name            TEXT,
                    icon            TEXT,
                    created_at      TEXT,
                    created_by      TEXT,
                    updated_at      TEXT,
                    updated_by      TEXT,
                    deleted_at      TEXT,
                    deleted_by      TEXT,
                    PRIMARY KEY (id, version)
                )
            """)

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_kategorien_audit_insert
                AFTER INSERT ON ticket_kategorien
                FOR EACH ROW
                BEGIN
                    INSERT INTO ticket_kategorien_history (
                        id, version, name, icon,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.icon,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_kategorien_audit_update
                AFTER UPDATE ON ticket_kategorien
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO ticket_kategorien_history (
                        id, version, name, icon,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.icon,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)

            # ============================================
            # tickets (Haupttabelle)
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    titel           TEXT NOT NULL,
                    beschreibung    TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'offen'
                                    CHECK(status IN (
                                        'offen', 'in_pruefung', 'eingeplant',
                                        'rueckfrage', 'erledigt', 'abgelehnt'
                                    )),
                    prioritaet      TEXT NOT NULL DEFAULT 'normal'
                                    CHECK(prioritaet IN ('niedrig', 'normal', 'hoch', 'sicherheit')),
                    bereich_id      INTEGER REFERENCES ticket_bereiche(id),
                    kategorie_id    INTEGER REFERENCES ticket_kategorien(id),
                    gemeldet_von    INTEGER NOT NULL REFERENCES users(id),
                    zugewiesen_an   INTEGER REFERENCES users(id),
                    faellig_am      TEXT,
                    geschlossen_am  TEXT,
                    geschlossen_von INTEGER REFERENCES users(id),
                    version         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by      TEXT NOT NULL,
                    deleted_at      TEXT,
                    deleted_by      TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_prioritaet ON tickets(prioritaet)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_bereich_id ON tickets(bereich_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_kategorie_id ON tickets(kategorie_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_gemeldet_von ON tickets(gemeldet_von)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_zugewiesen_an ON tickets(zugewiesen_an)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_deleted_at ON tickets(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets_history (
                    id              INTEGER NOT NULL,
                    version         INTEGER NOT NULL,
                    titel           TEXT,
                    beschreibung    TEXT,
                    status          TEXT,
                    prioritaet      TEXT,
                    bereich_id      INTEGER,
                    kategorie_id    INTEGER,
                    gemeldet_von    INTEGER,
                    zugewiesen_an   INTEGER,
                    faellig_am      TEXT,
                    geschlossen_am  TEXT,
                    geschlossen_von INTEGER,
                    created_at      TEXT,
                    created_by      TEXT,
                    updated_at      TEXT,
                    updated_by      TEXT,
                    deleted_at      TEXT,
                    deleted_by      TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_history_id ON tickets_history(id)")

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS tickets_audit_insert
                AFTER INSERT ON tickets
                FOR EACH ROW
                BEGIN
                    INSERT INTO tickets_history (
                        id, version, titel, beschreibung, status, prioritaet,
                        bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                        faellig_am, geschlossen_am, geschlossen_von,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                        NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                        NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS tickets_audit_update
                AFTER UPDATE ON tickets
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO tickets_history (
                        id, version, titel, beschreibung, status, prioritaet,
                        bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                        faellig_am, geschlossen_am, geschlossen_von,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                        NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                        NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            # Kein DELETE-Trigger fuer tickets

            # ============================================
            # ticket_kommentare
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_kommentare (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id       INTEGER NOT NULL REFERENCES tickets(id),
                    autor_id        INTEGER NOT NULL REFERENCES users(id),
                    inhalt          TEXT NOT NULL,
                    sichtbarkeit    TEXT NOT NULL DEFAULT 'oeffentlich'
                                    CHECK(sichtbarkeit IN ('oeffentlich', 'intern')),
                    version         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_by      TEXT NOT NULL,
                    deleted_at      TEXT,
                    deleted_by      TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_kommentare_ticket_id ON ticket_kommentare(ticket_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_kommentare_autor_id ON ticket_kommentare(autor_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_kommentare_deleted_at ON ticket_kommentare(deleted_at)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_kommentare_history (
                    id              INTEGER NOT NULL,
                    version         INTEGER NOT NULL,
                    ticket_id       INTEGER,
                    autor_id        INTEGER,
                    inhalt          TEXT,
                    sichtbarkeit    TEXT,
                    created_at      TEXT,
                    created_by      TEXT,
                    updated_at      TEXT,
                    updated_by      TEXT,
                    deleted_at      TEXT,
                    deleted_by      TEXT,
                    PRIMARY KEY (id, version)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_kommentare_history_id ON ticket_kommentare_history(id)")

            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_kommentare_audit_insert
                AFTER INSERT ON ticket_kommentare
                FOR EACH ROW
                BEGIN
                    INSERT INTO ticket_kommentare_history (
                        id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS ticket_kommentare_audit_update
                AFTER UPDATE ON ticket_kommentare
                FOR EACH ROW
                WHEN NEW.version != OLD.version
                BEGIN
                    INSERT INTO ticket_kommentare_history (
                        id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                        created_at, created_by, updated_at, updated_by,
                        deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END;
            """)
            # Kein DELETE-Trigger fuer ticket_kommentare

            # ============================================
            # ticket_anhaenge
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_anhaenge (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id       INTEGER NOT NULL REFERENCES tickets(id),
                    kommentar_id    INTEGER REFERENCES ticket_kommentare(id),
                    original_name   TEXT NOT NULL,
                    stored_name     TEXT UNIQUE,
                    mime_type       TEXT NOT NULL,
                    dateigroesse    INTEGER NOT NULL,
                    hochgeladen_von INTEGER NOT NULL REFERENCES users(id),
                    hochgeladen_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    deleted_at      TEXT,
                    deleted_by      TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_anhaenge_ticket_id ON ticket_anhaenge(ticket_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_anhaenge_kommentar_id ON ticket_anhaenge(kommentar_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_anhaenge_deleted_at ON ticket_anhaenge(deleted_at)")

            # ============================================
            # ticket_teilnehmer
            # ============================================
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_teilnehmer (
                    ticket_id        INTEGER NOT NULL REFERENCES tickets(id),
                    user_id          INTEGER NOT NULL REFERENCES users(id),
                    hinzugefuegt_von INTEGER NOT NULL REFERENCES users(id),
                    hinzugefuegt_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticket_id, user_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_teilnehmer_ticket_id ON ticket_teilnehmer(ticket_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_teilnehmer_user_id ON ticket_teilnehmer(user_id)")

            # ============================================
            # Stammdaten: Bereiche und Kategorien
            # ============================================
            stammbereiche = [
                ('Platz 1', 'Hauptspielfeld'),
                ('Platz 2', 'Nebenspielfeld'),
                ('Kabinen', 'Umkleiden und Sanitaranlagen'),
                ('Vereinsheim', 'Clubhaus und Gastraum'),
                ('Aussenanlage', 'Zaeune, Wege, Parkplatz'),
                ('Sonstiges', None),
            ]
            for name, beschreibung in stammbereiche:
                cur.execute("""
                    INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by)
                    VALUES (?, ?, 'MIGRATION_8_9', 'MIGRATION_8_9')
                """, (name, beschreibung))

            stammkategorien = [
                ('Schaden', 'wrench'),
                ('Sicherheit', 'shield-alert'),
                ('Ausstattung', 'package'),
                ('Reinigung', 'sparkles'),
                ('IT / Technik', 'monitor'),
                ('Sonstiges', 'circle-help'),
            ]
            for name, icon in stammkategorien:
                cur.execute("""
                    INSERT INTO ticket_kategorien (name, icon, created_by, updated_by)
                    VALUES (?, ?, 'MIGRATION_8_9', 'MIGRATION_8_9')
                """, (name, icon))

        self._set_schema_version(9)

    def _migrate_9_to_10(self):
        """Migration 9->10: Ticket-Permissions für bestehende User verteilen.

        Vergabe gemäß Rolle:
        - admin   → alle 7 Ticket-Permissions
        - user    → tickets.read, tickets.create
        - readonly→ tickets.read
        - special → tickets.read

        Verwendet INSERT OR IGNORE, damit bereits vorhandene Einträge
        (z.B. manuell vorab vergeben) nicht doppelt angelegt werden.
        """
        _TICKET_PERMS_V10 = {
            'admin': {
                'tickets.read',
                'tickets.create',
                'tickets.assign',
                'tickets.close',
                'tickets.delete',
                'tickets.intern_read',
                'tickets.bereiche_verwalten',
            },
            'user': {
                'tickets.read',
                'tickets.create',
            },
            'readonly': {
                'tickets.read',
            },
            'special': {
                'tickets.read',
            },
        }
        with self.cursor() as cur:
            cur.execute("SELECT id, role FROM users WHERE deleted_at IS NULL AND active = 1")
            existing_users = cur.fetchall()
            for row in existing_users:
                user_id = row['id']
                role = row['role']
                perms = _TICKET_PERMS_V10.get(role, {'tickets.read'})
                for perm in perms:
                    cur.execute("""
                        INSERT OR IGNORE INTO user_permissions
                            (user_id, permission, created_by, updated_by)
                        VALUES (?, ?, 'MIGRATION_9_10', 'MIGRATION_9_10')
                    """, (user_id, perm))
        self._set_schema_version(10)
