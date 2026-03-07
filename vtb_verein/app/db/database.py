'''
Created on 21.02.2026

Database connection and schema management.

@author: AI Assistant
'''

import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 4  # Version 4: auth_tokens Tabelle für Magic-Link-Authentication


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
        # [Existing migration code from cite:64 - truncated for space]
        pass  # Code bleibt gleich wie in aktueller database.py

    def _migrate_1_to_2(self):
        """Migration 1->2: History-Trigger für mitglied hinzufügen, DELETE-Trigger entfernen."""
        # [Existing migration code - truncated for space]
        pass  # Code bleibt gleich

    def _migrate_2_to_3(self):
        """Migration 2->3: Rolle 'special' zur users-Tabelle hinzufügen."""
        # [Existing migration code - truncated for space]
        pass  # Code bleibt gleich
    
    def _migrate_3_to_4(self):
        """Migration 3->4: auth_tokens Tabelle für Magic-Link-Authentication.
        
        Änderungen:
        1. Neue auth_tokens Tabelle für Magic-Links und Remember-Me-Tokens
        2. History-Tabelle für auth_tokens
        3. Trigger für INSERT/UPDATE (kein DELETE - Cleanup soll nicht getrackt werden)
        """
        with self.cursor() as cur:
            # ============================================
            # Tabelle: auth_tokens
            # ============================================
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
            
            # Indices für Performance
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_token ON auth_tokens(token)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires_at ON auth_tokens(expires_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_token_type ON auth_tokens(token_type)")
            
            # History-Tabelle
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
            
            # Trigger für auth_tokens: INSERT
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
            
            # Trigger für auth_tokens: UPDATE (nur wenn Version sich ändert)
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
