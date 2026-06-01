"""funktionen_schema_v19

Revision ID: a8f3c12d9e04
Revises: 7efbbbdea7c2
Create Date: 2026-06-01

Führt Mitglieds-Funktionszuordnungen ein (Schiedsrichter, Übungsleiter,
Abteilungsleiter) und erweitert beitragsregel um Funktions-Bedingungen.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'a8f3c12d9e04'
down_revision: Union[str, Sequence[str], None] = '7efbbbdea7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── mitglied_funktion ──────────────────────────────────────────────
    op.execute("""
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
    op.execute("""
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

    # ── Trigger für mitglied_funktion ──────────────────────────────────
    op.execute("""
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
        END; $$
    """)
    op.execute("""
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
        END; $$
    """)
    op.execute("""
        CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_insert
        AFTER INSERT ON mitglied_funktion
        FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_insert()
    """)
    op.execute("""
        CREATE OR REPLACE TRIGGER trig_mitglied_funktion_audit_update
        AFTER UPDATE ON mitglied_funktion
        FOR EACH ROW EXECUTE FUNCTION fn_mitglied_funktion_audit_update()
    """)

    # ── beitragsregel: Funktions-Bedingungen ───────────────────────────
    op.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
    op.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
    op.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER REFERENCES abteilung(id)")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS bedingung_funktion TEXT")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion TEXT")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN IF NOT EXISTS ausnahme_funktion_abteilung_id INTEGER")

    # ── Audit-Trigger für beitragsregel aktualisieren ──────────────────
    op.execute("""
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
        END; $$
    """)
    op.execute("""
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
        END; $$
    """)

    op.execute("UPDATE schema_version SET version = 19 WHERE id = 1")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trig_mitglied_funktion_audit_update ON mitglied_funktion")
    op.execute("DROP TRIGGER IF EXISTS trig_mitglied_funktion_audit_insert ON mitglied_funktion")
    op.execute("DROP FUNCTION IF EXISTS fn_mitglied_funktion_audit_update")
    op.execute("DROP FUNCTION IF EXISTS fn_mitglied_funktion_audit_insert")
    op.execute("DROP TABLE IF EXISTS mitglied_funktion_history")
    op.execute("DROP TABLE IF EXISTS mitglied_funktion")

    for col in ['bedingung_funktion', 'ausnahme_funktion', 'ausnahme_funktion_abteilung_id']:
        op.execute(f"ALTER TABLE beitragsregel DROP COLUMN IF EXISTS {col}")
        op.execute(f"ALTER TABLE beitragsregel_history DROP COLUMN IF EXISTS {col}")

    op.execute("UPDATE schema_version SET version = 18 WHERE id = 1")
