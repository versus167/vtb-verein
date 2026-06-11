'''
PostgreSQL database connection and schema management.
Rewritten 2026-05-18: sqlite3 → psycopg3, single consolidated schema (v15).
'''

import logging
import os
import bcrypt
from contextlib import contextmanager

logger = logging.getLogger(__name__)

import psycopg
from psycopg.rows import dict_row

SCHEMA_VERSION = 33


class Database:
    """Manages PostgreSQL connection and schema."""

    def __init__(self, database_url: str):
        self._database_url = database_url
        self.conn = psycopg.connect(database_url, row_factory=dict_row)
        self._init_schema()

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
        self.conn.close()

    # -----------------------------------
    # Schema-Initialisierung
    # -----------------------------------

    def _init_schema(self):
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id         INTEGER PRIMARY KEY CHECK (id = 1),
                    version    INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            logger.info("Frische Datenbank – Schema v%d wird erstellt …", SCHEMA_VERSION)
            self._create_schema()
            logger.info("Schema v%d erfolgreich angelegt.", SCHEMA_VERSION)
        elif row['version'] < SCHEMA_VERSION:
            logger.info("Schema-Version in DB: v%d – Code erwartet v%d. Starte Migrationen …",
                        row['version'], SCHEMA_VERSION)
            self._run_migrations(row['version'])
            logger.info("Alle Migrationen abgeschlossen. Schema jetzt v%d.", SCHEMA_VERSION)
        elif row['version'] > SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema-Version {row['version']} ist neuer als der Code (v{SCHEMA_VERSION}). "
                f"Bitte Code aktualisieren."
            )
        else:
            logger.info("Datenbank bereit. Schema v%d.", SCHEMA_VERSION)

    def _run_migrations(self, current_version: int) -> None:
        """Führt alle ausstehenden Migrationen sequenziell aus.
        Jede Migration läuft in einer eigenen Transaktion und aktualisiert
        schema_version als letzten Schritt — bei Fehler vollständiger Rollback."""
        migration_map = {
            16: self._migrate_v15_to_v16,
            17: self._migrate_v16_to_v17,
            18: self._migrate_v17_to_v18,
            19: self._migrate_v18_to_v19,
            20: self._migrate_v19_to_v20,
            21: self._migrate_v20_to_v21,
            22: self._migrate_v21_to_v22,
            23: self._migrate_v22_to_v23,
            24: self._migrate_v23_to_v24,
            25: self._migrate_v24_to_v25,
            26: self._migrate_v25_to_v26,
            27: self._migrate_v26_to_v27,
            28: self._migrate_v27_to_v28,
            29: self._migrate_v28_to_v29,
            30: self._migrate_v29_to_v30,
            31: self._migrate_v30_to_v31,
            32: self._migrate_v31_to_v32,
            33: self._migrate_v32_to_v33,
        }
        for target in range(current_version + 1, SCHEMA_VERSION + 1):
            fn = migration_map.get(target)
            if fn is None:
                raise RuntimeError(
                    f"Keine Migrationsfunktion für v{target} vorhanden. "
                    f"Bitte Code aktualisieren."
                )
            logger.info("Schema-Migration v%d → v%d wird ausgeführt …", target - 1, target)
            fn()
            logger.info("Schema-Migration v%d abgeschlossen.", target)

    def _migrate_v15_to_v16(self) -> None:
        """Partielle Unique-Indizes auf users.email/username (statt harter UNIQUE-Constraints),
        damit soft-gelöschte Accounts die E-Mail nicht dauerhaft blockieren."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key")
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_email_active
                ON users (email) WHERE deleted_at IS NULL
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_username_active
                ON users (username) WHERE deleted_at IS NULL
            """)
            cur.execute("UPDATE schema_version SET version = 16 WHERE id = 1")

    def _migrate_v16_to_v17(self) -> None:
        """mitglied.user_id → users.id (optional, 1:1) + Rolle 'mitglied' im CHECK-Constraint."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
            cur.execute("""
                ALTER TABLE users ADD CONSTRAINT users_role_check
                CHECK(role IN ('admin', 'user', 'readonly', 'special', 'mitglied'))
            """)
            cur.execute("ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_user_id
                ON mitglied (user_id) WHERE user_id IS NOT NULL
            """)
            cur.execute("ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS user_id INTEGER")
            cur.execute("UPDATE schema_version SET version = 17 WHERE id = 1")

    def _migrate_v17_to_v18(self) -> None:
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel RENAME COLUMN betrag TO betrag_pro_monat")
            cur.execute("ALTER TABLE beitragsregel RENAME COLUMN periode TO einzug_turnus")
            cur.execute("ALTER TABLE beitragsregel_history RENAME COLUMN betrag TO betrag_pro_monat")
            cur.execute("ALTER TABLE beitragsregel_history RENAME COLUMN periode TO einzug_turnus")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS zahler_typ TEXT NOT NULL DEFAULT 'mitglied'")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS zahler_kasse_id INTEGER REFERENCES kassen(id)")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_abteilung_status TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS zahler_typ TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS zahler_kasse_id INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_abteilung_status TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS faelligkeitsdatum TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'offen'")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS bezahlt_am TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN IF NOT EXISTS kassenbuchung_id INTEGER REFERENCES kassenbuchungen(id)")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS faelligkeitsdatum TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS status TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS bezahlt_am TEXT")
            cur.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN IF NOT EXISTS kassenbuchung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_insert
                AFTER INSERT ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_update
                AFTER UPDATE ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_update();
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitrag_sollstellung_history (
                        id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                        faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                        NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitrag_sollstellung_history (
                            id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                            faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                            NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_insert
                AFTER INSERT ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_update
                AFTER UPDATE ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 18 WHERE id = 1")

    def _migrate_v18_to_v19(self) -> None:
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_funktion (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  abteilung_id   INTEGER REFERENCES abteilung(id),
                  funktion       TEXT NOT NULL,
                  von            TEXT,
                  bis            TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_funktion_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,
                  mitglied_id    INTEGER,
                  abteilung_id   INTEGER,
                  funktion       TEXT,
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
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_funktion_history (
                        id, version, mitglied_id, abteilung_id, funktion, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_funktion_history (
                            id, version, mitglied_id, abteilung_id, funktion, von, bis,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_insert
                AFTER INSERT ON mitglied_funktion
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_update
                AFTER UPDATE ON mitglied_funktion
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_update();
            """)
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER REFERENCES abteilung(id)")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 19 WHERE id = 1")

    def _migrate_v19_to_v20(self) -> None:
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion (
                  id            SERIAL PRIMARY KEY,
                  key           TEXT NOT NULL,
                  name          TEXT NOT NULL,
                  beschreibung  TEXT,
                  version       INTEGER NOT NULL DEFAULT 1,
                  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  created_by    TEXT,
                  updated_at    TIMESTAMP,
                  updated_by    TEXT,
                  deleted_at    TIMESTAMP,
                  deleted_by    TEXT
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_funktion_key_active
                ON funktion (key)
                WHERE deleted_at IS NULL
            """)
            for key, name in [
                ('schiedsrichter',   'Schiedsrichter'),
                ('uebungsleiter',    'Übungsleiter'),
                ('abteilungsleiter', 'Abteilungsleiter'),
            ]:
                cur.execute("""
                    INSERT INTO funktion (key, name, created_by)
                    SELECT %s, %s, 'system'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM funktion WHERE key = %s AND deleted_at IS NULL
                    )
                """, (key, name, key))
            cur.execute("UPDATE schema_version SET version = 20 WHERE id = 1")

    def _migrate_v20_to_v21(self) -> None:
        """Benennt Permissions von mitglieder.*/users.* auf personen.* um."""
        mapping = [
            ('mitglieder.read',   'personen.read'),
            ('mitglieder.write',  'personen.write'),
            ('mitglieder.delete', 'personen.delete'),
            ('users.manage',      'personen.permissions'),
            ('users.read',        'personen.read'),
        ]
        with self.cursor() as cur:
            for old, new in mapping:
                # Neue Permission anlegen wo sie noch nicht existiert
                cur.execute("""
                    INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                    SELECT user_id, %s, created_by, created_by
                    FROM user_permissions
                    WHERE permission = %s
                      AND deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM user_permissions up2
                          WHERE up2.user_id = user_permissions.user_id
                            AND up2.permission = %s
                            AND up2.deleted_at IS NULL
                      )
                """, (new, old, new))
                # Alte Permission soft-deleten
                cur.execute("""
                    UPDATE user_permissions
                    SET deleted_at = CURRENT_TIMESTAMP, deleted_by = 'migration_v21'
                    WHERE permission = %s AND deleted_at IS NULL
                """, (old,))
            # users.manage-User bekommen auch personen.read/write/delete
            for perm in ('personen.read', 'personen.write', 'personen.delete'):
                cur.execute("""
                    INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                    SELECT DISTINCT user_id, %s, 'migration_v21', 'migration_v21'
                    FROM user_permissions
                    WHERE permission = 'personen.permissions'
                      AND deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM user_permissions up2
                          WHERE up2.user_id = user_permissions.user_id
                            AND up2.permission = %s
                            AND up2.deleted_at IS NULL
                      )
                """, (perm, perm))
            cur.execute("UPDATE schema_version SET version = 21 WHERE id = 1")

    def _migrate_v21_to_v22(self) -> None:
        """Fügt bedingung_funktion_abteilung_id zu beitragsregel hinzu."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_funktion_abteilung_id INTEGER REFERENCES abteilung(id)")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_funktion_abteilung_id INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, bedingung_funktion_abteilung_id,
                        ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, bedingung_funktion_abteilung_id,
                            ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.bedingung_funktion_abteilung_id,
                            NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 22 WHERE id = 1")

    def _migrate_v22_to_v23(self) -> None:
        """Fügt funktion_history + Audit-Trigger für die funktion-Tabelle hinzu."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funktion_history (
                  id           INTEGER NOT NULL,
                  version      INTEGER NOT NULL,
                  key          TEXT,
                  name         TEXT,
                  beschreibung TEXT,
                  created_at   TIMESTAMP,
                  created_by   TEXT,
                  updated_at   TIMESTAMP,
                  updated_by   TEXT,
                  deleted_at   TIMESTAMP,
                  deleted_by   TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO funktion_history (
                        id, version, key, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO funktion_history (
                            id, version, key, name, beschreibung,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                            NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_audit_insert
                AFTER INSERT ON funktion
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_funktion_audit_update
                AFTER UPDATE ON funktion
                FOR EACH ROW EXECUTE FUNCTION fn_funktion_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 23 WHERE id = 1")

    def _migrate_v23_to_v24(self) -> None:
        """Mehrere Kontaktdaten je Mitglied: neue Tabelle mitglied_kontakt (voll
        normalisiert). Bestehende mitglied.email/telefon werden als primäre Kontakte
        übernommen, danach werden die Spalten entfernt. mitglied_history behält seine
        email/telefon-Spalten als eingefrorene Historie."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_kontakt (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  typ            TEXT NOT NULL,
                  wert           TEXT NOT NULL,
                  label          TEXT,
                  ist_primaer    BOOLEAN NOT NULL DEFAULT FALSE,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_kontakt_history (
                  id             INTEGER NOT NULL,
                  version        INTEGER NOT NULL,
                  mitglied_id    INTEGER,
                  typ            TEXT,
                  wert           TEXT,
                  label          TEXT,
                  ist_primaer    BOOLEAN,
                  created_at     TEXT,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_kontakt_history (
                        id, version, mitglied_id, typ, wert, label, ist_primaer,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_kontakt_history (
                            id, version, mitglied_id, typ, wert, label, ist_primaer,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_kontakt_audit_insert
                AFTER INSERT ON mitglied_kontakt
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_kontakt_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_mitglied_kontakt_audit_update
                AFTER UPDATE ON mitglied_kontakt
                FOR EACH ROW EXECUTE FUNCTION fn_mitglied_kontakt_audit_update();
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_mitglied_id ON mitglied_kontakt(mitglied_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_deleted_at  ON mitglied_kontakt(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mitglied_kontakt_history_id  ON mitglied_kontakt_history(id)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_kontakt_primaer ON mitglied_kontakt (mitglied_id, typ) WHERE ist_primaer AND deleted_at IS NULL")

            # Bestandsdaten übernehmen: vorhandene email/telefon als primäre Kontakte
            cur.execute("""
                INSERT INTO mitglied_kontakt (mitglied_id, typ, wert, ist_primaer, created_by)
                SELECT id, 'email', email, TRUE, 'migration'
                FROM mitglied WHERE email IS NOT NULL AND email <> ''
            """)
            cur.execute("""
                INSERT INTO mitglied_kontakt (mitglied_id, typ, wert, ist_primaer, created_by)
                SELECT id, 'telefon', telefon, TRUE, 'migration'
                FROM mitglied WHERE telefon IS NOT NULL AND telefon <> ''
            """)

            # mitglied-Audit-Funktionen ohne email/telefon neu definieren …
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_history (
                            id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                            strasse, plz, ort, land,
                            eintrittsdatum, austrittsdatum, status,
                            zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                            user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                            NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                            NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                            NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                            NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            # … und erst danach die Spalten entfernen (Funktion referenziert sie nicht mehr)
            cur.execute("ALTER TABLE mitglied DROP COLUMN IF EXISTS email")
            cur.execute("ALTER TABLE mitglied DROP COLUMN IF EXISTS telefon")

            cur.execute("UPDATE schema_version SET version = 24 WHERE id = 1")

    def _migrate_v24_to_v25(self) -> None:
        """Funktions-Zeitraum verpflichtend: mitglied_funktion.von wird NOT NULL.
        Bestehende NULL/leere Werte werden auf das Anlagedatum (created_at) gesetzt."""
        with self.cursor() as cur:
            cur.execute("""
                UPDATE mitglied_funktion
                SET von = COALESCE(NULLIF(von, ''), LEFT(created_at, 10), CURRENT_DATE::text)
                WHERE von IS NULL OR von = ''
            """)
            cur.execute("ALTER TABLE mitglied_funktion ALTER COLUMN von SET NOT NULL")
            cur.execute("UPDATE schema_version SET version = 25 WHERE id = 1")

    def _migrate_v25_to_v26(self) -> None:
        """Altersabhängige Beitragsregeln: bedingung_alter_min/max an beitragsregel."""
        with self.cursor() as cur:
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_alter_min INTEGER")
            cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_alter_max INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_alter_min INTEGER")
            cur.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_alter_max INTEGER")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ, zahler_kasse_id,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ, NEW.zahler_kasse_id,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ, zahler_kasse_id,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ, NEW.zahler_kasse_id,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 26 WHERE id = 1")

    def _migrate_v26_to_v27(self) -> None:
        """Mannschaften/Teams: mannschaft + mitglied_mannschaft (mit Rolle/Zeitraum)."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mannschaft (
                  id             SERIAL PRIMARY KEY,
                  abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
                  name           TEXT NOT NULL,
                  saison         TEXT,
                  beschreibung   TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mannschaft_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  abteilung_id INTEGER, name TEXT, saison TEXT, beschreibung TEXT,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_mannschaft (
                  id             SERIAL PRIMARY KEY,
                  mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
                  mannschaft_id  INTEGER NOT NULL REFERENCES mannschaft(id),
                  rolle          TEXT NOT NULL,
                  von            TEXT NOT NULL,
                  bis            TEXT,
                  version        INTEGER NOT NULL DEFAULT 1,
                  created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by     TEXT,
                  updated_at     TEXT,
                  updated_by     TEXT,
                  deleted_at     TEXT,
                  deleted_by     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mitglied_mannschaft_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  mitglied_id INTEGER, mannschaft_id INTEGER, rolle TEXT, von TEXT, bis TEXT,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            for sql in (
                """CREATE OR REPLACE FUNCTION fn_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO mannschaft_history (id, version, abteilung_id, name, saison, beschreibung,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO mannschaft_history (id, version, abteilung_id, name, saison, beschreibung,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO mitglied_mannschaft_history (id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO mitglied_mannschaft_history (id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                "CREATE OR REPLACE TRIGGER trig_mannschaft_audit_insert AFTER INSERT ON mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mannschaft_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_mannschaft_audit_update AFTER UPDATE ON mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mannschaft_audit_update()",
                "CREATE OR REPLACE TRIGGER trig_mitglied_mannschaft_audit_insert AFTER INSERT ON mitglied_mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mitglied_mannschaft_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_mitglied_mannschaft_audit_update AFTER UPDATE ON mitglied_mannschaft FOR EACH ROW EXECUTE FUNCTION fn_mitglied_mannschaft_audit_update()",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_abteilung_id ON mannschaft(abteilung_id)",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_deleted_at ON mannschaft(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_mannschaft_history_id ON mannschaft_history(id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_mitglied_id ON mitglied_mannschaft(mitglied_id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_mannschaft_id ON mitglied_mannschaft(mannschaft_id)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_deleted_at ON mitglied_mannschaft(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_mitglied_mannschaft_history_id ON mitglied_mannschaft_history(id)",
            ):
                cur.execute(sql)
            cur.execute("UPDATE schema_version SET version = 27 WHERE id = 1")

    def _migrate_v27_to_v28(self) -> None:
        """Aufnahme-/Einmalgebühren: gebuehr (Katalog mit Gültigkeit) + gebuehr_forderung
        (einmalige Forderung je Mitglied, einziehbar wie Beiträge)."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr (
                  id              SERIAL PRIMARY KEY,
                  name            TEXT NOT NULL,
                  abteilung_id    INTEGER REFERENCES abteilung(id),
                  betrag          REAL NOT NULL,
                  anlass          TEXT NOT NULL DEFAULT 'aufnahme',
                  gueltig_ab      TEXT NOT NULL,
                  gueltig_bis     TEXT,
                  zahler_typ      TEXT NOT NULL DEFAULT 'mitglied',
                  zahler_kasse_id INTEGER REFERENCES kassen(id),
                  version         INTEGER NOT NULL DEFAULT 1,
                  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by      TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at      TEXT, deleted_by TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  name TEXT, abteilung_id INTEGER, betrag REAL, anlass TEXT,
                  gueltig_ab TEXT, gueltig_bis TEXT, zahler_typ TEXT, zahler_kasse_id INTEGER,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_forderung (
                  id                SERIAL PRIMARY KEY,
                  mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
                  gebuehr_id        INTEGER NOT NULL REFERENCES gebuehr(id),
                  datum             TEXT NOT NULL,
                  betrag_soll       REAL NOT NULL,
                  status            TEXT NOT NULL DEFAULT 'offen',
                  bezahlt_am        TEXT,
                  kassenbuchung_id  INTEGER REFERENCES kassenbuchungen(id),
                  version           INTEGER NOT NULL DEFAULT 1,
                  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  created_by        TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at        TEXT, deleted_by TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gebuehr_forderung_history (
                  id INTEGER NOT NULL, version INTEGER NOT NULL,
                  mitglied_id INTEGER, gebuehr_id INTEGER, datum TEXT, betrag_soll REAL,
                  status TEXT, bezahlt_am TEXT, kassenbuchung_id INTEGER,
                  created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
                  deleted_at TEXT, deleted_by TEXT,
                  PRIMARY KEY (id, version)
                )
            """)
            for sql in (
                """CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO gebuehr_history (id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                       zahler_typ, zahler_kasse_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                       NEW.zahler_typ, NEW.zahler_kasse_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO gebuehr_history (id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                       zahler_typ, zahler_kasse_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                       NEW.zahler_typ, NEW.zahler_kasse_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN INSERT INTO gebuehr_forderung_history (id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   RETURN NEW; END; $$;""",
                """CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                   BEGIN IF NEW.version != OLD.version THEN INSERT INTO gebuehr_forderung_history (id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                       created_at, created_by, updated_at, updated_by, deleted_at, deleted_by)
                   VALUES (NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                       NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by);
                   END IF; RETURN NEW; END; $$;""",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_audit_insert AFTER INSERT ON gebuehr FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_audit_update AFTER UPDATE ON gebuehr FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_audit_update()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_forderung_audit_insert AFTER INSERT ON gebuehr_forderung FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_forderung_audit_insert()",
                "CREATE OR REPLACE TRIGGER trig_gebuehr_forderung_audit_update AFTER UPDATE ON gebuehr_forderung FOR EACH ROW EXECUTE FUNCTION fn_gebuehr_forderung_audit_update()",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_abteilung_id ON gebuehr(abteilung_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_deleted_at ON gebuehr(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_history_id ON gebuehr_history(id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_mitglied_id ON gebuehr_forderung(mitglied_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_gebuehr_id ON gebuehr_forderung(gebuehr_id)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_status ON gebuehr_forderung(status)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_deleted_at ON gebuehr_forderung(deleted_at)",
                "CREATE INDEX IF NOT EXISTS idx_gebuehr_forderung_history_id ON gebuehr_forderung_history(id)",
            ):
                cur.execute(sql)
            cur.execute("UPDATE schema_version SET version = 28 WHERE id = 1")

    def _migrate_v28_to_v29(self) -> None:
        """Import-Zusatzfelder am Mitglied: Geschlecht, Bemerkungen, SEPA-Mandatsreferenz
        (+ -datum). Für die Übernahme aus dem SPG-Verein-Export."""
        with self.cursor() as cur:
            for col in ('geschlecht', 'bemerkungen', 'sepa_mandatsref', 'sepa_mandatsdatum'):
                cur.execute(f"ALTER TABLE mitglied ADD COLUMN IF NOT EXISTS {col} TEXT")
                cur.execute(f"ALTER TABLE mitglied_history ADD COLUMN IF NOT EXISTS {col} TEXT")
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                        user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                        NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO mitglied_history (
                            id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                            strasse, plz, ort, land,
                            eintrittsdatum, austrittsdatum, status,
                            zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                            geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                            user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                            NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                            NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                            NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                            NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                            NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("UPDATE schema_version SET version = 29 WHERE id = 1")

    def _migrate_v29_to_v30(self) -> None:
        """Entfernt die 'Kasse für Umbuchung' (zahler_kasse_id) aus beitragsregel und
        gebuehr (inkl. *_history). Beiträge/Gebühren werden nie auf Kassen gebucht;
        zahler_typ='abteilung' bleibt als reine Zahler-Zuordnung erhalten."""
        with self.cursor() as cur:
            # Audit-Trigger-Funktionen ohne zahler_kasse_id neu schreiben (sonst brechen
            # sie beim nächsten INSERT/UPDATE, weil NEW.zahler_kasse_id wegfällt).
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktion, ausnahme_funktion, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktion, NEW.ausnahme_funktion, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO gebuehr_history (
                        id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                        zahler_typ,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                        NEW.zahler_typ,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO gebuehr_history (
                            id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                            zahler_typ,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                            NEW.zahler_typ,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)
            # Spalte überall entfernen (FK auf kassen wird mit gedroppt)
            for tbl in ('beitragsregel', 'beitragsregel_history', 'gebuehr', 'gebuehr_history'):
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS zahler_kasse_id")
            cur.execute("UPDATE schema_version SET version = 30 WHERE id = 1")

    def _migrate_v30_to_v31(self) -> None:
        """Matrix-ID/Telegram-ID-Unique-Indizes schließen soft-gelöschte User aus.
        Bisher blockierte ein gelöschter Account die Matrix-/Telegram-ID dauerhaft,
        sodass sie kein anderer (lebender) Benutzer mehr verwenden konnte –
        analog zu uix_users_email_active/uix_users_username_active."""
        with self.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS uix_users_matrix_id")
            cur.execute("DROP INDEX IF EXISTS uix_users_telegram_id")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_matrix_id
                ON users (matrix_id) WHERE matrix_id IS NOT NULL AND deleted_at IS NULL
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_users_telegram_id
                ON users (telegram_id) WHERE telegram_id IS NOT NULL AND deleted_at IS NULL
            """)
            cur.execute("UPDATE schema_version SET version = 31 WHERE id = 1")

    def _migrate_v31_to_v32(self) -> None:
        """Fehlende Audit-Trigger auf beitragsregel und beitrag_sollstellung nachziehen.
        Beide Tabellen entstanden in der v17→v18-Migration; DBs, die diese Migration
        durchliefen, bevor die Trigger-Erzeugung dort ergänzt wurde, haben zwar die
        fn_*_audit_*-Funktionen, aber keine angebrachten Trigger – es wurde also keine
        *_history geschrieben. Frischaufbauten sind nicht betroffen (siehe _create_triggers).
        CREATE OR REPLACE TRIGGER ist idempotent: auf bereits korrekten DBs ein No-Op."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_insert
                AFTER INSERT ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitragsregel_audit_update
                AFTER UPDATE ON beitragsregel
                FOR EACH ROW EXECUTE FUNCTION fn_beitragsregel_audit_update();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_insert
                AFTER INSERT ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_insert();
            """)
            cur.execute("""
                CREATE OR REPLACE TRIGGER trig_beitrag_sollstellung_audit_update
                AFTER UPDATE ON beitrag_sollstellung
                FOR EACH ROW EXECUTE FUNCTION fn_beitrag_sollstellung_audit_update();
            """)
            cur.execute("UPDATE schema_version SET version = 32 WHERE id = 1")

    def _migrate_v32_to_v33(self) -> None:
        """Ein-/Ausschluss von Funktionen je Beitragsregel von Einzelwert auf
        Mehrfachauswahl umstellen: bedingung_funktion/ausnahme_funktion (TEXT) →
        bedingung_funktionen/ausnahme_funktionen (TEXT[]). Bestehende Einzelwerte
        werden in einelementige Arrays migriert, danach die Altspalten entfernt.
        Die Abteilungs-Qualifizierer (…_abteilung_id) bleiben unverändert."""
        with self.cursor() as cur:
            # 1) Neue Array-Spalten anlegen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS bedingung_funktionen TEXT[]")
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS ausnahme_funktionen TEXT[]")

            # 2) Backfill: vorhandene Einzelwerte in einelementige Arrays überführen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(
                    f"UPDATE {tbl} SET bedingung_funktionen = ARRAY[bedingung_funktion] "
                    f"WHERE bedingung_funktion IS NOT NULL AND bedingung_funktion <> ''"
                )
                cur.execute(
                    f"UPDATE {tbl} SET ausnahme_funktionen = ARRAY[ausnahme_funktion] "
                    f"WHERE ausnahme_funktion IS NOT NULL AND ausnahme_funktion <> ''"
                )

            # 3) Audit-Trigger-Funktionen auf die neuen Spalten umstellen (vor dem Drop,
            #    damit die Funktionskörper keine entfallenden Spalten mehr referenzieren)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktionen, bedingung_funktion_abteilung_id,
                        ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                    RETURN NEW;
                END; $$;
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.version != OLD.version THEN
                        INSERT INTO beitragsregel_history (
                            id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                            gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                            zahler_typ,
                            bedingung_funktionen, bedingung_funktion_abteilung_id,
                            ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                            bedingung_alter_min, bedingung_alter_max,
                            created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                        ) VALUES (
                            NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                            NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                            NEW.zahler_typ,
                            NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                            NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                            NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                            NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                        );
                    END IF;
                    RETURN NEW;
                END; $$;
            """)

            # 4) Altspalten entfernen
            for tbl in ('beitragsregel', 'beitragsregel_history'):
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS bedingung_funktion")
                cur.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS ausnahme_funktion")

            cur.execute("UPDATE schema_version SET version = 33 WHERE id = 1")

    def _create_schema(self):
        """Erstellt das vollständige Schema auf einer frischen Datenbank."""
        with self.cursor() as cur:
            self._create_tables(cur)
            self._create_trigger_functions(cur)
            self._create_triggers(cur)
            self._create_indexes(cur)
            self._seed_data(cur)
            cur.execute(
                "INSERT INTO schema_version (id, version) VALUES (1, %s)",
                (SCHEMA_VERSION,),
            )

    # -----------------------------------
    # Tabellen
    # -----------------------------------

    def _create_tables(self, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied (
              id                SERIAL PRIMARY KEY,
              mitgliedsnummer   INTEGER UNIQUE,
              vorname           TEXT NOT NULL,
              nachname          TEXT NOT NULL,
              geburtsdatum      TEXT,
              strasse           TEXT,
              plz               TEXT,
              ort               TEXT,
              land              TEXT,
              eintrittsdatum    TEXT,
              austrittsdatum    TEXT,
              status            TEXT NOT NULL DEFAULT 'aktiv',
              zahlungsart       TEXT NOT NULL,
              iban              TEXT,
              bic               TEXT,
              kontoinhaber      TEXT,
              abgerechnet_bis   TEXT,
              geschlecht        TEXT,
              bemerkungen       TEXT,
              sepa_mandatsref   TEXT,
              sepa_mandatsdatum TEXT,
              user_id           INTEGER,
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
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
              geschlecht        TEXT,
              bemerkungen       TEXT,
              sepa_mandatsref   TEXT,
              sepa_mandatsdatum TEXT,
              user_id           INTEGER,
              created_at        TEXT,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_kontakt (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              typ            TEXT NOT NULL,
              wert           TEXT NOT NULL,
              label          TEXT,
              ist_primaer    BOOLEAN NOT NULL DEFAULT FALSE,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_kontakt_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              typ            TEXT,
              wert           TEXT,
              label          TEXT,
              ist_primaer    BOOLEAN,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS abteilung (
              id            SERIAL PRIMARY KEY,
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS abteilung_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              name          TEXT,
              kuerzel       TEXT,
              beschreibung  TEXT,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_abteilung (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
              status         TEXT NOT NULL DEFAULT 'aktiv',
              von            TEXT,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_funktion (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              abteilung_id   INTEGER REFERENCES abteilung(id),
              funktion       TEXT NOT NULL,
              von            TEXT NOT NULL,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_funktion_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              abteilung_id   INTEGER,
              funktion       TEXT,
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitragsregel (
              id                           SERIAL PRIMARY KEY,
              name                         TEXT NOT NULL,
              abteilung_id                 INTEGER REFERENCES abteilung(id),
              betrag_pro_monat             REAL NOT NULL,
              einzug_turnus                TEXT NOT NULL,
              gueltig_ab                   TEXT NOT NULL,
              gueltig_bis                  TEXT,
              bedingung_raw                TEXT,
              bedingung_abteilung_status   TEXT,
              bedingung_funktionen         TEXT[],
              bedingung_funktion_abteilung_id INTEGER REFERENCES abteilung(id),
              ausnahme_funktionen          TEXT[],
              ausnahme_funktion_abteilung_id INTEGER REFERENCES abteilung(id),
              bedingung_alter_min          INTEGER,
              bedingung_alter_max          INTEGER,
              zahler_typ                   TEXT NOT NULL DEFAULT 'mitglied',
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitragsregel_history (
              id                           INTEGER NOT NULL,
              version                      INTEGER NOT NULL,
              name                         TEXT,
              abteilung_id                 INTEGER,
              betrag_pro_monat             REAL,
              einzug_turnus                TEXT,
              gueltig_ab                   TEXT,
              gueltig_bis                  TEXT,
              bedingung_raw                TEXT,
              bedingung_abteilung_status   TEXT,
              bedingung_funktionen         TEXT[],
              bedingung_funktion_abteilung_id INTEGER,
              ausnahme_funktionen          TEXT[],
              ausnahme_funktion_abteilung_id INTEGER,
              bedingung_alter_min          INTEGER,
              bedingung_alter_max          INTEGER,
              zahler_typ                   TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitrag_sollstellung (
              id                SERIAL PRIMARY KEY,
              mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
              beitragsregel_id  INTEGER NOT NULL REFERENCES beitragsregel(id),
              zeitraum          TEXT NOT NULL,
              betrag_soll       REAL NOT NULL,
              faelligkeitsdatum TEXT,
              status            TEXT NOT NULL DEFAULT 'offen',
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beitrag_sollstellung_history (
              id                INTEGER NOT NULL,
              version           INTEGER NOT NULL,
              mitglied_id       INTEGER,
              beitragsregel_id  INTEGER,
              zeitraum          TEXT,
              betrag_soll       REAL,
              faelligkeitsdatum TEXT,
              status            TEXT,
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id                SERIAL PRIMARY KEY,
              username          TEXT NOT NULL,
              email             TEXT NOT NULL,
              password_hash     TEXT NOT NULL,
              role              TEXT NOT NULL CHECK(role IN ('admin', 'user', 'readonly', 'special', 'mitglied')),
              active            INTEGER NOT NULL DEFAULT 1,
              last_login        TEXT,
              telegram_id       TEXT,
              matrix_id         TEXT,
              preferred_contact TEXT DEFAULT 'email',
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT NOT NULL,
              updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by        TEXT NOT NULL,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users_history (
              id                INTEGER NOT NULL,
              version           INTEGER NOT NULL,
              username          TEXT NOT NULL,
              email             TEXT NOT NULL,
              password_hash     TEXT NOT NULL,
              role              TEXT NOT NULL,
              active            INTEGER NOT NULL,
              last_login        TEXT,
              telegram_id       TEXT,
              matrix_id         TEXT,
              preferred_contact TEXT,
              created_at        TEXT NOT NULL,
              created_by        TEXT NOT NULL,
              updated_at        TEXT NOT NULL,
              updated_by        TEXT NOT NULL,
              deleted_at        TEXT,
              deleted_by        TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
              id          SERIAL PRIMARY KEY,
              user_id     INTEGER NOT NULL REFERENCES users(id),
              token       TEXT UNIQUE NOT NULL,
              token_type  TEXT NOT NULL CHECK(token_type IN ('magic_link', 'remember_me')),
              expires_at  TEXT NOT NULL,
              used_at     TEXT,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              user_id     INTEGER NOT NULL,
              token       TEXT NOT NULL,
              token_type  TEXT NOT NULL,
              expires_at  TEXT NOT NULL,
              used_at     TEXT,
              created_at  TEXT NOT NULL,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
              id          SERIAL PRIMARY KEY,
              user_id     INTEGER NOT NULL REFERENCES users(id),
              permission  TEXT NOT NULL,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT,
              UNIQUE (user_id, permission)
            )
        """)
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen (
              id                  SERIAL PRIMARY KEY,
              name                TEXT NOT NULL,
              beschreibung        TEXT,
              anfangsbestand_cent INTEGER NOT NULL DEFAULT 0,
              abteilung_id        INTEGER REFERENCES abteilung(id),
              version             INTEGER NOT NULL DEFAULT 1,
              created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by          TEXT NOT NULL,
              updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by          TEXT NOT NULL,
              deleted_at          TEXT,
              deleted_by          TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassen_history (
              id                  INTEGER NOT NULL,
              version             INTEGER NOT NULL,
              name                TEXT,
              beschreibung        TEXT,
              anfangsbestand_cent INTEGER,
              abteilung_id        INTEGER,
              created_at          TEXT,
              created_by          TEXT,
              updated_at          TEXT,
              updated_by          TEXT,
              deleted_at          TEXT,
              deleted_by          TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuch_exporte (
              id               SERIAL PRIMARY KEY,
              kasse_id         INTEGER NOT NULL REFERENCES kassen(id),
              zeitraum_von     TEXT NOT NULL,
              zeitraum_bis     TEXT NOT NULL,
              exportiert_am    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              exportiert_von   TEXT NOT NULL,
              dateiname        TEXT NOT NULL,
              anzahl_buchungen INTEGER NOT NULL,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT NOT NULL,
              deleted_at       TEXT,
              deleted_by       TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuch_exporte_history (
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              kasse_id         INTEGER,
              zeitraum_von     TEXT,
              zeitraum_bis     TEXT,
              exportiert_am    TEXT,
              exportiert_von   TEXT,
              dateiname        TEXT,
              anzahl_buchungen INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuchungen (
              id                      SERIAL PRIMARY KEY,
              kasse_id                INTEGER NOT NULL REFERENCES kassen(id),
              buchungsdatum           TEXT NOT NULL,
              belegnummer             TEXT NOT NULL,
              buchungstext            TEXT NOT NULL,
              kategorie               TEXT NOT NULL,
              einnahme_cent           INTEGER NOT NULL DEFAULT 0,
              ausgabe_cent            INTEGER NOT NULL DEFAULT 0,
              notiz                   TEXT,
              exportiert_in_export_id INTEGER REFERENCES kassenbuch_exporte(id),
              version                 INTEGER NOT NULL DEFAULT 1,
              created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by              TEXT NOT NULL,
              updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by              TEXT NOT NULL,
              deleted_at              TEXT,
              deleted_by              TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kassenbuchungen_history (
              id                      INTEGER NOT NULL,
              version                 INTEGER NOT NULL,
              kasse_id                INTEGER,
              buchungsdatum           TEXT,
              belegnummer             TEXT,
              buchungstext            TEXT,
              kategorie               TEXT,
              einnahme_cent           INTEGER,
              ausgabe_cent            INTEGER,
              notiz                   TEXT,
              exportiert_in_export_id INTEGER,
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
            CREATE TABLE IF NOT EXISTS kasse_berechtigungen (
              id               SERIAL PRIMARY KEY,
              kasse_id         INTEGER NOT NULL REFERENCES kassen(id),
              user_id          INTEGER NOT NULL REFERENCES users(id),
              darf_lesen       INTEGER NOT NULL DEFAULT 0,
              darf_schreiben   INTEGER NOT NULL DEFAULT 0,
              darf_exportieren INTEGER NOT NULL DEFAULT 0,
              version          INTEGER NOT NULL DEFAULT 1,
              created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by       TEXT NOT NULL,
              updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by       TEXT NOT NULL,
              deleted_at       TEXT,
              deleted_by       TEXT,
              UNIQUE (kasse_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kasse_berechtigungen_history (
              id               INTEGER NOT NULL,
              version          INTEGER NOT NULL,
              kasse_id         INTEGER,
              user_id          INTEGER,
              darf_lesen       INTEGER,
              darf_schreiben   INTEGER,
              darf_exportieren INTEGER,
              created_at       TEXT,
              created_by       TEXT,
              updated_at       TEXT,
              updated_by       TEXT,
              deleted_at       TEXT,
              deleted_by       TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereiche (
              id            SERIAL PRIMARY KEY,
              name          TEXT NOT NULL,
              beschreibung  TEXT,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT NOT NULL,
              updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by    TEXT NOT NULL,
              deleted_at    TEXT,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereiche_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              name          TEXT,
              beschreibung  TEXT,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kategorien (
              id          SERIAL PRIMARY KEY,
              name        TEXT NOT NULL,
              icon        TEXT,
              version     INTEGER NOT NULL DEFAULT 1,
              created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by  TEXT NOT NULL,
              updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by  TEXT NOT NULL,
              deleted_at  TEXT,
              deleted_by  TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kategorien_history (
              id          INTEGER NOT NULL,
              version     INTEGER NOT NULL,
              name        TEXT,
              icon        TEXT,
              created_at  TEXT,
              created_by  TEXT,
              updated_at  TEXT,
              updated_by  TEXT,
              deleted_at  TEXT,
              deleted_by  TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
              id              SERIAL PRIMARY KEY,
              titel           TEXT NOT NULL,
              beschreibung    TEXT NOT NULL,
              status          TEXT NOT NULL DEFAULT 'offen'
                              CHECK(status IN ('offen','in_pruefung','eingeplant','rueckfrage','erledigt','abgelehnt')),
              prioritaet      TEXT NOT NULL DEFAULT 'normal'
                              CHECK(prioritaet IN ('niedrig','normal','hoch','sicherheit')),
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kommentare (
              id            SERIAL PRIMARY KEY,
              ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
              autor_id      INTEGER NOT NULL REFERENCES users(id),
              inhalt        TEXT NOT NULL,
              sichtbarkeit  TEXT NOT NULL DEFAULT 'oeffentlich'
                            CHECK(sichtbarkeit IN ('oeffentlich', 'intern')),
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT NOT NULL,
              updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by    TEXT NOT NULL,
              deleted_at    TEXT,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_kommentare_history (
              id            INTEGER NOT NULL,
              version       INTEGER NOT NULL,
              ticket_id     INTEGER,
              autor_id      INTEGER,
              inhalt        TEXT,
              sichtbarkeit  TEXT,
              created_at    TEXT,
              created_by    TEXT,
              updated_at    TEXT,
              updated_by    TEXT,
              deleted_at    TEXT,
              deleted_by    TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_anhaenge (
              id              SERIAL PRIMARY KEY,
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_teilnehmer (
              ticket_id        INTEGER NOT NULL REFERENCES tickets(id),
              user_id          INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_von INTEGER NOT NULL REFERENCES users(id),
              hinzugefuegt_am  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (ticket_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereich_berechtigungen (
              id              SERIAL PRIMARY KEY,
              bereich_id      INTEGER NOT NULL REFERENCES ticket_bereiche(id),
              user_id         INTEGER NOT NULL REFERENCES users(id),
              darf_lesen      INTEGER NOT NULL DEFAULT 0,
              darf_bearbeiten INTEGER NOT NULL DEFAULT 0,
              darf_schliessen INTEGER NOT NULL DEFAULT 0,
              version         INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by      TEXT NOT NULL,
              updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_by      TEXT NOT NULL,
              deleted_at      TEXT,
              deleted_by      TEXT,
              UNIQUE (bereich_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_bereich_berechtigungen_history (
              id              INTEGER NOT NULL,
              version         INTEGER NOT NULL,
              bereich_id      INTEGER,
              user_id         INTEGER,
              darf_lesen      INTEGER,
              darf_bearbeiten INTEGER,
              darf_schliessen INTEGER,
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
            CREATE TABLE IF NOT EXISTS kassenbuchung_anhaenge (
              id              SERIAL PRIMARY KEY,
              buchung_id      INTEGER NOT NULL REFERENCES kassenbuchungen(id),
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mannschaft (
              id             SERIAL PRIMARY KEY,
              abteilung_id   INTEGER NOT NULL REFERENCES abteilung(id),
              name           TEXT NOT NULL,
              saison         TEXT,
              beschreibung   TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mannschaft_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              abteilung_id   INTEGER,
              name           TEXT,
              saison         TEXT,
              beschreibung   TEXT,
              created_at     TEXT,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_mannschaft (
              id             SERIAL PRIMARY KEY,
              mitglied_id    INTEGER NOT NULL REFERENCES mitglied(id),
              mannschaft_id  INTEGER NOT NULL REFERENCES mannschaft(id),
              rolle          TEXT NOT NULL,
              von            TEXT NOT NULL,
              bis            TEXT,
              version        INTEGER NOT NULL DEFAULT 1,
              created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by     TEXT,
              updated_at     TEXT,
              updated_by     TEXT,
              deleted_at     TEXT,
              deleted_by     TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mitglied_mannschaft_history (
              id             INTEGER NOT NULL,
              version        INTEGER NOT NULL,
              mitglied_id    INTEGER,
              mannschaft_id  INTEGER,
              rolle          TEXT,
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr (
              id              SERIAL PRIMARY KEY,
              name            TEXT NOT NULL,
              abteilung_id    INTEGER REFERENCES abteilung(id),
              betrag          REAL NOT NULL,
              anlass          TEXT NOT NULL DEFAULT 'aufnahme',
              gueltig_ab      TEXT NOT NULL,
              gueltig_bis     TEXT,
              zahler_typ      TEXT NOT NULL DEFAULT 'mitglied',
              version         INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by      TEXT,
              updated_at      TEXT,
              updated_by      TEXT,
              deleted_at      TEXT,
              deleted_by      TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_history (
              id INTEGER NOT NULL, version INTEGER NOT NULL,
              name TEXT, abteilung_id INTEGER, betrag REAL, anlass TEXT,
              gueltig_ab TEXT, gueltig_bis TEXT, zahler_typ TEXT,
              created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
              deleted_at TEXT, deleted_by TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_forderung (
              id                SERIAL PRIMARY KEY,
              mitglied_id       INTEGER NOT NULL REFERENCES mitglied(id),
              gebuehr_id        INTEGER NOT NULL REFERENCES gebuehr(id),
              datum             TEXT NOT NULL,
              betrag_soll       REAL NOT NULL,
              status            TEXT NOT NULL DEFAULT 'offen',
              bezahlt_am        TEXT,
              kassenbuchung_id  INTEGER REFERENCES kassenbuchungen(id),
              version           INTEGER NOT NULL DEFAULT 1,
              created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by        TEXT,
              updated_at        TEXT,
              updated_by        TEXT,
              deleted_at        TEXT,
              deleted_by        TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gebuehr_forderung_history (
              id INTEGER NOT NULL, version INTEGER NOT NULL,
              mitglied_id INTEGER, gebuehr_id INTEGER, datum TEXT, betrag_soll REAL,
              status TEXT, bezahlt_am TEXT, kassenbuchung_id INTEGER,
              created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT,
              deleted_at TEXT, deleted_by TEXT,
              PRIMARY KEY (id, version)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion (
              id            SERIAL PRIMARY KEY,
              key           TEXT NOT NULL,
              name          TEXT NOT NULL,
              beschreibung  TEXT,
              version       INTEGER NOT NULL DEFAULT 1,
              created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              created_by    TEXT,
              updated_at    TIMESTAMP,
              updated_by    TEXT,
              deleted_at    TIMESTAMP,
              deleted_by    TEXT
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uix_funktion_key_active
            ON funktion (key) WHERE deleted_at IS NULL
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funktion_history (
              id           INTEGER NOT NULL,
              version      INTEGER NOT NULL,
              key          TEXT,
              name         TEXT,
              beschreibung TEXT,
              created_at   TIMESTAMP,
              created_by   TEXT,
              updated_at   TIMESTAMP,
              updated_by   TEXT,
              deleted_at   TIMESTAMP,
              deleted_by   TEXT,
              PRIMARY KEY (id, version)
            )
        """)

        # Forward-Referenzen: Diese FKs werden erst NACH allen CREATE TABLE gesetzt,
        # weil ihre Ziel-Tabelle in der Erzeugungsreihenfolge später kommt
        # (mitglied vor users, beitrag_sollstellung vor kassenbuchungen).
        # Inline-REFERENCES würden beim Frischaufbau mit UndefinedTable abbrechen.
        # Constraint-Namen entsprechen den Postgres-Defaults, damit frisch gebaute
        # und hochmigrierte DBs identisch sind.
        cur.execute("""
            ALTER TABLE mitglied
            ADD CONSTRAINT mitglied_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id)
        """)
        cur.execute("""
            ALTER TABLE beitrag_sollstellung
            ADD CONSTRAINT beitrag_sollstellung_kassenbuchung_id_fkey
            FOREIGN KEY (kassenbuchung_id) REFERENCES kassenbuchungen(id)
        """)

    # -----------------------------------
    # Trigger-Funktionen (PL/pgSQL)
    # -----------------------------------

    def _create_trigger_functions(self, cur):
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_history (
                    id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                    strasse, plz, ort, land,
                    eintrittsdatum, austrittsdatum, status,
                    zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                    geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                    user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                    NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                    NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                    NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                    NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                    NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_history (
                        id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                        strasse, plz, ort, land,
                        eintrittsdatum, austrittsdatum, status,
                        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                        geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                        user_id, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitgliedsnummer, NEW.vorname, NEW.nachname, NEW.geburtsdatum,
                        NEW.strasse, NEW.plz, NEW.ort, NEW.land,
                        NEW.eintrittsdatum, NEW.austrittsdatum, NEW.status,
                        NEW.zahlungsart, NEW.iban, NEW.bic, NEW.kontoinhaber, NEW.abgerechnet_bis,
                        NEW.geschlecht, NEW.bemerkungen, NEW.sepa_mandatsref, NEW.sepa_mandatsdatum,
                        NEW.user_id, NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_kontakt_history (
                    id, version, mitglied_id, typ, wert, label, ist_primaer,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_kontakt_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_kontakt_history (
                        id, version, mitglied_id, typ, wert, label, ist_primaer,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.typ, NEW.wert, NEW.label, NEW.ist_primaer,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mannschaft_history (
                    id, version, abteilung_id, name, saison, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mannschaft_history (
                        id, version, abteilung_id, name, saison, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.abteilung_id, NEW.name, NEW.saison, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_mannschaft_history (
                    id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_mannschaft_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_mannschaft_history (
                        id, version, mitglied_id, mannschaft_id, rolle, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.mannschaft_id, NEW.rolle, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_gebuehr_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO gebuehr_history (
                    id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                    zahler_typ,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                    NEW.zahler_typ,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_gebuehr_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO gebuehr_history (
                        id, version, name, abteilung_id, betrag, anlass, gueltig_ab, gueltig_bis,
                        zahler_typ,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag, NEW.anlass, NEW.gueltig_ab, NEW.gueltig_bis,
                        NEW.zahler_typ,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO gebuehr_forderung_history (
                    id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_gebuehr_forderung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO gebuehr_forderung_history (
                        id, version, mitglied_id, gebuehr_id, datum, betrag_soll, status, bezahlt_am, kassenbuchung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.gebuehr_id, NEW.datum, NEW.betrag_soll, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_abteilung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO abteilung_history (
                    id, version, name, kuerzel, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_abteilung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO abteilung_history (
                        id, version, name, kuerzel, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.kuerzel, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_abteilung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_abteilung_history (
                    id, version, mitglied_id, abteilung_id, status, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_abteilung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_abteilung_history (
                        id, version, mitglied_id, abteilung_id, status, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_users_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO users_history (
                    id, version, username, email, password_hash, role, active, last_login,
                    telegram_id, matrix_id, preferred_contact,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                    NEW.active, NEW.last_login, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_users_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO users_history (
                        id, version, username, email, password_hash, role, active, last_login,
                        telegram_id, matrix_id, preferred_contact,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.username, NEW.email, NEW.password_hash, NEW.role,
                        NEW.active, NEW.last_login, NEW.telegram_id, NEW.matrix_id, NEW.preferred_contact,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO auth_tokens_history (
                    id, version, user_id, token, token_type, expires_at, used_at, created_at
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
                    NEW.expires_at, NEW.used_at, NEW.created_at
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_auth_tokens_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO auth_tokens_history (
                        id, version, user_id, token, token_type, expires_at, used_at, created_at
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.token, NEW.token_type,
                        NEW.expires_at, NEW.used_at, NEW.created_at
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_permissions_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO user_permissions_history (
                    id, version, user_id, permission,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.user_id, NEW.permission,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_user_permissions_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO user_permissions_history (
                        id, version, user_id, permission,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.user_id, NEW.permission,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassen_history (
                    id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent, NEW.abteilung_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassen_history (
                        id, version, name, beschreibung, anfangsbestand_cent, abteilung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung, NEW.anfangsbestand_cent, NEW.abteilung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuchungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kassenbuchungen_history (
                    id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                    kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                    NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                    NEW.notiz, NEW.exportiert_in_export_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuchungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kassenbuchungen_history (
                        id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                        kategorie, einnahme_cent, ausgabe_cent, notiz, exportiert_in_export_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.buchungsdatum, NEW.belegnummer,
                        NEW.buchungstext, NEW.kategorie, NEW.einnahme_cent, NEW.ausgabe_cent,
                        NEW.notiz, NEW.exportiert_in_export_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kassenbuch_exporte_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kasse_berechtigungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO kasse_berechtigungen_history (
                    id, version, kasse_id, user_id,
                    darf_lesen, darf_schreiben, darf_exportieren,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                    NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_kasse_berechtigungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO kasse_berechtigungen_history (
                        id, version, kasse_id, user_id,
                        darf_lesen, darf_schreiben, darf_exportieren,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.kasse_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_schreiben, NEW.darf_exportieren,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereiche_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_bereiche_history (
                    id, version, name, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereiche_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_bereiche_history (
                        id, version, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kategorien_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_kategorien_history (
                    id, version, name, icon,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.icon,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kategorien_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_kategorien_history (
                        id, version, name, icon,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.icon,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_tickets_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO tickets_history (
                    id, version, titel, beschreibung, status, prioritaet,
                    bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                    faellig_am, geschlossen_am, geschlossen_von,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                    NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                    NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_tickets_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO tickets_history (
                        id, version, titel, beschreibung, status, prioritaet,
                        bereich_id, kategorie_id, gemeldet_von, zugewiesen_an,
                        faellig_am, geschlossen_am, geschlossen_von,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.titel, NEW.beschreibung, NEW.status, NEW.prioritaet,
                        NEW.bereich_id, NEW.kategorie_id, NEW.gemeldet_von, NEW.zugewiesen_an,
                        NEW.faellig_am, NEW.geschlossen_am, NEW.geschlossen_von,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kommentare_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_kommentare_history (
                    id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_kommentare_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_kommentare_history (
                        id, version, ticket_id, autor_id, inhalt, sichtbarkeit,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.ticket_id, NEW.autor_id, NEW.inhalt, NEW.sichtbarkeit,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereich_berechtigungen_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO ticket_bereich_berechtigungen_history (
                    id, version, bereich_id, user_id,
                    darf_lesen, darf_bearbeiten, darf_schliessen,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.bereich_id, NEW.user_id,
                    NEW.darf_lesen, NEW.darf_bearbeiten, NEW.darf_schliessen,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_ticket_bereich_berechtigungen_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO ticket_bereich_berechtigungen_history (
                        id, version, bereich_id, user_id,
                        darf_lesen, darf_bearbeiten, darf_schliessen,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.bereich_id, NEW.user_id,
                        NEW.darf_lesen, NEW.darf_bearbeiten, NEW.darf_schliessen,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)

        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO mitglied_funktion_history (
                    id, version, mitglied_id, abteilung_id, funktion, von, bis,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_mitglied_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO mitglied_funktion_history (
                        id, version, mitglied_id, abteilung_id, funktion, von, bis,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.funktion, NEW.von, NEW.bis,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO beitragsregel_history (
                    id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                    gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                    zahler_typ,
                    bedingung_funktionen, bedingung_funktion_abteilung_id,
                    ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                    bedingung_alter_min, bedingung_alter_max,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                    NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                    NEW.zahler_typ,
                    NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                    NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                    NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_beitragsregel_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO beitragsregel_history (
                        id, version, name, abteilung_id, betrag_pro_monat, einzug_turnus,
                        gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                        zahler_typ,
                        bedingung_funktionen, bedingung_funktion_abteilung_id,
                        ausnahme_funktionen, ausnahme_funktion_abteilung_id,
                        bedingung_alter_min, bedingung_alter_max,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                        NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                        NEW.zahler_typ,
                        NEW.bedingung_funktionen, NEW.bedingung_funktion_abteilung_id,
                        NEW.ausnahme_funktionen, NEW.ausnahme_funktion_abteilung_id,
                        NEW.bedingung_alter_min, NEW.bedingung_alter_max,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO beitrag_sollstellung_history (
                    id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                    faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                    NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_beitrag_sollstellung_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO beitrag_sollstellung_history (
                        id, version, mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                        faelligkeitsdatum, status, bezahlt_am, kassenbuchung_id,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.mitglied_id, NEW.beitragsregel_id, NEW.zeitraum, NEW.betrag_soll,
                        NEW.faelligkeitsdatum, NEW.status, NEW.bezahlt_am, NEW.kassenbuchung_id,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_audit_insert() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                INSERT INTO funktion_history (
                    id, version, key, name, beschreibung,
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                    NEW.deleted_at, NEW.deleted_by
                );
                RETURN NEW;
            END; $$;
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION fn_funktion_audit_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.version != OLD.version THEN
                    INSERT INTO funktion_history (
                        id, version, key, name, beschreibung,
                        created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                    ) VALUES (
                        NEW.id, NEW.version, NEW.key, NEW.name, NEW.beschreibung,
                        NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                        NEW.deleted_at, NEW.deleted_by
                    );
                END IF;
                RETURN NEW;
            END; $$;
        """)

    # -----------------------------------
    # Trigger-Bindungen
    # -----------------------------------

    def _create_triggers(self, cur):
        for name, event, table, fn in [
            ('trig_mitglied_audit_insert',                          'INSERT', 'mitglied',                          'fn_mitglied_audit_insert'),
            ('trig_mitglied_audit_update',                          'UPDATE', 'mitglied',                          'fn_mitglied_audit_update'),
            ('trig_abteilung_audit_insert',                         'INSERT', 'abteilung',                         'fn_abteilung_audit_insert'),
            ('trig_abteilung_audit_update',                         'UPDATE', 'abteilung',                         'fn_abteilung_audit_update'),
            ('trig_mitglied_abteilung_audit_insert',                'INSERT', 'mitglied_abteilung',                'fn_mitglied_abteilung_audit_insert'),
            ('trig_mitglied_abteilung_audit_update',                'UPDATE', 'mitglied_abteilung',                'fn_mitglied_abteilung_audit_update'),
            ('trig_mitglied_funktion_audit_insert',                 'INSERT', 'mitglied_funktion',                 'fn_mitglied_funktion_audit_insert'),
            ('trig_mitglied_funktion_audit_update',                 'UPDATE', 'mitglied_funktion',                 'fn_mitglied_funktion_audit_update'),
            ('trig_mitglied_kontakt_audit_insert',                  'INSERT', 'mitglied_kontakt',                  'fn_mitglied_kontakt_audit_insert'),
            ('trig_mitglied_kontakt_audit_update',                  'UPDATE', 'mitglied_kontakt',                  'fn_mitglied_kontakt_audit_update'),
            ('trig_mannschaft_audit_insert',                        'INSERT', 'mannschaft',                        'fn_mannschaft_audit_insert'),
            ('trig_mannschaft_audit_update',                        'UPDATE', 'mannschaft',                        'fn_mannschaft_audit_update'),
            ('trig_mitglied_mannschaft_audit_insert',               'INSERT', 'mitglied_mannschaft',               'fn_mitglied_mannschaft_audit_insert'),
            ('trig_mitglied_mannschaft_audit_update',               'UPDATE', 'mitglied_mannschaft',               'fn_mitglied_mannschaft_audit_update'),
            ('trig_gebuehr_audit_insert',                           'INSERT', 'gebuehr',                           'fn_gebuehr_audit_insert'),
            ('trig_gebuehr_audit_update',                           'UPDATE', 'gebuehr',                           'fn_gebuehr_audit_update'),
            ('trig_gebuehr_forderung_audit_insert',                 'INSERT', 'gebuehr_forderung',                 'fn_gebuehr_forderung_audit_insert'),
            ('trig_gebuehr_forderung_audit_update',                 'UPDATE', 'gebuehr_forderung',                 'fn_gebuehr_forderung_audit_update'),
            ('trig_users_audit_insert',                             'INSERT', 'users',                             'fn_users_audit_insert'),
            ('trig_users_audit_update',                             'UPDATE', 'users',                             'fn_users_audit_update'),
            ('trig_auth_tokens_audit_insert',                       'INSERT', 'auth_tokens',                       'fn_auth_tokens_audit_insert'),
            ('trig_auth_tokens_audit_update',                       'UPDATE', 'auth_tokens',                       'fn_auth_tokens_audit_update'),
            ('trig_user_permissions_audit_insert',                  'INSERT', 'user_permissions',                  'fn_user_permissions_audit_insert'),
            ('trig_user_permissions_audit_update',                  'UPDATE', 'user_permissions',                  'fn_user_permissions_audit_update'),
            ('trig_kassen_audit_insert',                            'INSERT', 'kassen',                            'fn_kassen_audit_insert'),
            ('trig_kassen_audit_update',                            'UPDATE', 'kassen',                            'fn_kassen_audit_update'),
            ('trig_kassenbuchungen_audit_insert',                   'INSERT', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_insert'),
            ('trig_kassenbuchungen_audit_update',                   'UPDATE', 'kassenbuchungen',                   'fn_kassenbuchungen_audit_update'),
            ('trig_kassenbuch_exporte_audit_insert',                'INSERT', 'kassenbuch_exporte',                'fn_kassenbuch_exporte_audit_insert'),
            ('trig_kasse_berechtigungen_audit_insert',              'INSERT', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_insert'),
            ('trig_kasse_berechtigungen_audit_update',              'UPDATE', 'kasse_berechtigungen',              'fn_kasse_berechtigungen_audit_update'),
            ('trig_ticket_bereiche_audit_insert',                   'INSERT', 'ticket_bereiche',                   'fn_ticket_bereiche_audit_insert'),
            ('trig_ticket_bereiche_audit_update',                   'UPDATE', 'ticket_bereiche',                   'fn_ticket_bereiche_audit_update'),
            ('trig_ticket_kategorien_audit_insert',                 'INSERT', 'ticket_kategorien',                 'fn_ticket_kategorien_audit_insert'),
            ('trig_ticket_kategorien_audit_update',                 'UPDATE', 'ticket_kategorien',                 'fn_ticket_kategorien_audit_update'),
            ('trig_tickets_audit_insert',                           'INSERT', 'tickets',                           'fn_tickets_audit_insert'),
            ('trig_tickets_audit_update',                           'UPDATE', 'tickets',                           'fn_tickets_audit_update'),
            ('trig_ticket_kommentare_audit_insert',                 'INSERT', 'ticket_kommentare',                 'fn_ticket_kommentare_audit_insert'),
            ('trig_ticket_kommentare_audit_update',                 'UPDATE', 'ticket_kommentare',                 'fn_ticket_kommentare_audit_update'),
            ('trig_ticket_bereich_berechtigungen_audit_insert',     'INSERT', 'ticket_bereich_berechtigungen',     'fn_ticket_bereich_berechtigungen_audit_insert'),
            ('trig_ticket_bereich_berechtigungen_audit_update',     'UPDATE', 'ticket_bereich_berechtigungen',     'fn_ticket_bereich_berechtigungen_audit_update'),
            ('trig_beitragsregel_audit_insert',                     'INSERT', 'beitragsregel',                     'fn_beitragsregel_audit_insert'),
            ('trig_beitragsregel_audit_update',                     'UPDATE', 'beitragsregel',                     'fn_beitragsregel_audit_update'),
            ('trig_beitrag_sollstellung_audit_insert',              'INSERT', 'beitrag_sollstellung',              'fn_beitrag_sollstellung_audit_insert'),
            ('trig_beitrag_sollstellung_audit_update',              'UPDATE', 'beitrag_sollstellung',              'fn_beitrag_sollstellung_audit_update'),
            ('trig_funktion_audit_insert',                          'INSERT', 'funktion',                          'fn_funktion_audit_insert'),
            ('trig_funktion_audit_update',                          'UPDATE', 'funktion',                          'fn_funktion_audit_update'),
        ]:
            cur.execute(f"""
                CREATE OR REPLACE TRIGGER {name}
                AFTER {event} ON {table}
                FOR EACH ROW EXECUTE FUNCTION {fn}();
            """)

    # -----------------------------------
    # Indizes
    # -----------------------------------

    def _create_indexes(self, cur):
        for name, target in [
            ("idx_users_username",                                  "users(username)"),
            ("idx_users_email",                                     "users(email)"),
            ("idx_users_role",                                      "users(role)"),
            ("idx_users_active",                                    "users(active)"),
            ("idx_users_deleted_at",                                "users(deleted_at)"),
            ("idx_users_history_id",                                "users_history(id)"),
            ("idx_auth_tokens_token",                               "auth_tokens(token)"),
            ("idx_auth_tokens_user_id",                             "auth_tokens(user_id)"),
            ("idx_auth_tokens_expires_at",                          "auth_tokens(expires_at)"),
            ("idx_auth_tokens_token_type",                          "auth_tokens(token_type)"),
            ("idx_auth_tokens_history_id",                          "auth_tokens_history(id)"),
            ("idx_user_permissions_user_id",                        "user_permissions(user_id)"),
            ("idx_user_permissions_permission",                     "user_permissions(permission)"),
            ("idx_user_permissions_deleted_at",                     "user_permissions(deleted_at)"),
            ("idx_user_permissions_history_id",                     "user_permissions_history(id)"),
            ("idx_kassen_deleted_at",                               "kassen(deleted_at)"),
            ("idx_kassen_abteilung_id",                             "kassen(abteilung_id)"),
            ("idx_kassenbuchungen_kasse_id",                        "kassenbuchungen(kasse_id)"),
            ("idx_kassenbuchungen_buchungsdatum",                   "kassenbuchungen(buchungsdatum)"),
            ("idx_kassenbuchungen_deleted_at",                      "kassenbuchungen(deleted_at)"),
            ("idx_kassenbuchungen_export_id",                       "kassenbuchungen(exportiert_in_export_id)"),
            ("idx_kassenbuchungen_belegnummer",                     "kassenbuchungen(kasse_id, belegnummer)"),
            ("idx_kassenbuchungen_history_id",                      "kassenbuchungen_history(id)"),
            ("idx_kassenbuch_exporte_kasse_id",                     "kassenbuch_exporte(kasse_id)"),
            ("idx_kassenbuch_exporte_zeitraum",                     "kassenbuch_exporte(zeitraum_von, zeitraum_bis)"),
            ("idx_kasse_berechtigungen_kasse_id",                   "kasse_berechtigungen(kasse_id)"),
            ("idx_kasse_berechtigungen_user_id",                    "kasse_berechtigungen(user_id)"),
            ("idx_kasse_berechtigungen_deleted_at",                 "kasse_berechtigungen(deleted_at)"),
            ("idx_kasse_berechtigungen_history_id",                 "kasse_berechtigungen_history(id)"),
            ("idx_ticket_bereiche_deleted_at",                      "ticket_bereiche(deleted_at)"),
            ("idx_ticket_kategorien_deleted_at",                    "ticket_kategorien(deleted_at)"),
            ("idx_tickets_status",                                  "tickets(status)"),
            ("idx_tickets_prioritaet",                              "tickets(prioritaet)"),
            ("idx_tickets_bereich_id",                              "tickets(bereich_id)"),
            ("idx_tickets_kategorie_id",                            "tickets(kategorie_id)"),
            ("idx_tickets_gemeldet_von",                            "tickets(gemeldet_von)"),
            ("idx_tickets_zugewiesen_an",                           "tickets(zugewiesen_an)"),
            ("idx_tickets_deleted_at",                              "tickets(deleted_at)"),
            ("idx_tickets_history_id",                              "tickets_history(id)"),
            ("idx_ticket_kommentare_ticket_id",                     "ticket_kommentare(ticket_id)"),
            ("idx_ticket_kommentare_autor_id",                      "ticket_kommentare(autor_id)"),
            ("idx_ticket_kommentare_deleted_at",                    "ticket_kommentare(deleted_at)"),
            ("idx_ticket_kommentare_history_id",                    "ticket_kommentare_history(id)"),
            ("idx_ticket_anhaenge_ticket_id",                       "ticket_anhaenge(ticket_id)"),
            ("idx_ticket_anhaenge_kommentar_id",                    "ticket_anhaenge(kommentar_id)"),
            ("idx_ticket_anhaenge_deleted_at",                      "ticket_anhaenge(deleted_at)"),
            ("idx_ticket_teilnehmer_ticket_id",                     "ticket_teilnehmer(ticket_id)"),
            ("idx_ticket_teilnehmer_user_id",                       "ticket_teilnehmer(user_id)"),
            ("idx_ticket_bereich_berechtigungen_bereich_id",        "ticket_bereich_berechtigungen(bereich_id)"),
            ("idx_ticket_bereich_berechtigungen_user_id",           "ticket_bereich_berechtigungen(user_id)"),
            ("idx_ticket_bereich_berechtigungen_deleted_at",        "ticket_bereich_berechtigungen(deleted_at)"),
            ("idx_ticket_bereich_berechtigungen_history_id",        "ticket_bereich_berechtigungen_history(id)"),
            ("idx_kassenbuchung_anhaenge_buchung_id",               "kassenbuchung_anhaenge(buchung_id)"),
            ("idx_kassenbuchung_anhaenge_deleted_at",               "kassenbuchung_anhaenge(deleted_at)"),
            ("idx_mitglied_kontakt_mitglied_id",                    "mitglied_kontakt(mitglied_id)"),
            ("idx_mitglied_kontakt_deleted_at",                     "mitglied_kontakt(deleted_at)"),
            ("idx_mitglied_kontakt_history_id",                     "mitglied_kontakt_history(id)"),
            ("idx_mannschaft_abteilung_id",                         "mannschaft(abteilung_id)"),
            ("idx_mannschaft_deleted_at",                           "mannschaft(deleted_at)"),
            ("idx_mannschaft_history_id",                           "mannschaft_history(id)"),
            ("idx_mitglied_mannschaft_mitglied_id",                 "mitglied_mannschaft(mitglied_id)"),
            ("idx_mitglied_mannschaft_mannschaft_id",               "mitglied_mannschaft(mannschaft_id)"),
            ("idx_mitglied_mannschaft_deleted_at",                  "mitglied_mannschaft(deleted_at)"),
            ("idx_mitglied_mannschaft_history_id",                  "mitglied_mannschaft_history(id)"),
            ("idx_gebuehr_abteilung_id",                            "gebuehr(abteilung_id)"),
            ("idx_gebuehr_deleted_at",                              "gebuehr(deleted_at)"),
            ("idx_gebuehr_history_id",                              "gebuehr_history(id)"),
            ("idx_gebuehr_forderung_mitglied_id",                   "gebuehr_forderung(mitglied_id)"),
            ("idx_gebuehr_forderung_gebuehr_id",                    "gebuehr_forderung(gebuehr_id)"),
            ("idx_gebuehr_forderung_status",                        "gebuehr_forderung(status)"),
            ("idx_gebuehr_forderung_deleted_at",                    "gebuehr_forderung(deleted_at)"),
            ("idx_gebuehr_forderung_history_id",                    "gebuehr_forderung_history(id)"),
        ]:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")

        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_user_id       ON mitglied (user_id)  WHERE user_id IS NOT NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_mitglied_kontakt_primaer ON mitglied_kontakt (mitglied_id, typ) WHERE ist_primaer AND deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_email_active    ON users (email)       WHERE deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_username_active ON users (username)    WHERE deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_telegram_id     ON users (telegram_id) WHERE telegram_id IS NOT NULL AND deleted_at IS NULL")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_users_matrix_id       ON users (matrix_id)   WHERE matrix_id   IS NOT NULL AND deleted_at IS NULL")

    # -----------------------------------
    # Seed-Daten
    # -----------------------------------

    def _seed_data(self, cur):
        _ADMIN_PERMS = {
            'personen.read', 'personen.write', 'personen.delete', 'personen.permissions',
            'abteilungen.read', 'abteilungen.write', 'abteilungen.delete',
            'mannschaften.read', 'mannschaften.write', 'mannschaften.delete',
            'beitraege.read', 'beitraege.write', 'beitraege.abrechnen',
            'gebuehren.read', 'gebuehren.write', 'gebuehren.abrechnen',
            'berichte.read', 'berichte.export',
            'system.config',
            'tickets.access',
            'tickets.bereiche_verwalten',
        }

        pw_hash = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode()
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, active, created_by, updated_by)
            VALUES (%s, %s, %s, 'admin', 1, 'SYSTEM', 'SYSTEM')
            RETURNING id
        """, ('admin', 'admin@verein.local', pw_hash))
        admin_id = cur.fetchone()['id']
        logger.warning("Standard-Admin erstellt: Username='admin', Passwort='admin123' - BITTE ÄNDERN!")

        for perm in _ADMIN_PERMS:
            cur.execute("""
                INSERT INTO user_permissions (user_id, permission, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
                ON CONFLICT DO NOTHING
            """, (admin_id, perm))

        for name, beschreibung in [
            ('Platz 1',      'Hauptspielfeld'),
            ('Platz 2',      'Nebenspielfeld'),
            ('Kabinen',      'Umkleiden und Sanitaranlagen'),
            ('Vereinsheim',  'Clubhaus und Gastraum'),
            ('Aussenanlage', 'Zaeune, Wege, Parkplatz'),
            ('Sonstiges',    None),
        ]:
            cur.execute("""
                INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
                RETURNING id
            """, (name, beschreibung))
            bereich_id = cur.fetchone()['id']
            cur.execute("""
                INSERT INTO ticket_bereich_berechtigungen
                    (bereich_id, user_id, darf_lesen, darf_bearbeiten, darf_schliessen, created_by, updated_by)
                VALUES (%s, %s, 1, 1, 1, 'SYSTEM', 'SYSTEM')
                ON CONFLICT DO NOTHING
            """, (bereich_id, admin_id))

        for name, icon in [
            ('Schaden',      'wrench'),
            ('Sicherheit',   'shield-alert'),
            ('Ausstattung',  'package'),
            ('Reinigung',    'sparkles'),
            ('IT / Technik', 'monitor'),
            ('Sonstiges',    'circle-help'),
        ]:
            cur.execute("""
                INSERT INTO ticket_kategorien (name, icon, created_by, updated_by)
                VALUES (%s, %s, 'SYSTEM', 'SYSTEM')
            """, (name, icon))

        for key, name in [
            ('schiedsrichter',   'Schiedsrichter'),
            ('uebungsleiter',    'Übungsleiter'),
            ('abteilungsleiter', 'Abteilungsleiter'),
        ]:
            cur.execute("""
                INSERT INTO funktion (key, name, created_by)
                SELECT %s, %s, 'SYSTEM'
                WHERE NOT EXISTS (
                    SELECT 1 FROM funktion WHERE key = %s AND deleted_at IS NULL
                )
            """, (key, name, key))
