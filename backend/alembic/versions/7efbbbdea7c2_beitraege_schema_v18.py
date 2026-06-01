"""beitraege_schema_v18

Revision ID: 7efbbbdea7c2
Revises: c3ba48190042
Create Date: 2026-05-31

Erweitert beitragsregel und beitrag_sollstellung um alle nötigen Felder
für die vollständige Beitragsverwaltung mit SEPA-Lastschrift und
Abteilungs-Umbuchungen.
"""
from typing import Sequence, Union
from alembic import op


revision: str = '7efbbbdea7c2'
down_revision: Union[str, Sequence[str], None] = 'c3ba48190042'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── beitragsregel ──────────────────────────────────────────────
    # betrag → betrag_pro_monat, periode → einzug_turnus
    op.execute("ALTER TABLE beitragsregel RENAME COLUMN betrag TO betrag_pro_monat")
    op.execute("ALTER TABLE beitragsregel RENAME COLUMN periode TO einzug_turnus")
    op.execute("ALTER TABLE beitragsregel_history RENAME COLUMN betrag TO betrag_pro_monat")
    op.execute("ALTER TABLE beitragsregel_history RENAME COLUMN periode TO einzug_turnus")

    # Zahler-Konzept
    op.execute("ALTER TABLE beitragsregel ADD COLUMN zahler_typ TEXT NOT NULL DEFAULT 'mitglied'")
    op.execute("ALTER TABLE beitragsregel ADD COLUMN zahler_kasse_id INTEGER REFERENCES kassen(id)")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN zahler_typ TEXT")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN zahler_kasse_id INTEGER")

    # Bedingung: welche Abteilungs-Status sind betroffen (NULL = alle)
    op.execute("ALTER TABLE beitragsregel ADD COLUMN bedingung_abteilung_status TEXT")
    op.execute("ALTER TABLE beitragsregel_history ADD COLUMN bedingung_abteilung_status TEXT")

    # ── beitrag_sollstellung ───────────────────────────────────────
    op.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN faelligkeitsdatum TEXT")
    op.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN status TEXT NOT NULL DEFAULT 'offen'")
    op.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN bezahlt_am TEXT")
    op.execute("ALTER TABLE beitrag_sollstellung ADD COLUMN kassenbuchung_id INTEGER REFERENCES kassenbuchungen(id)")
    op.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN faelligkeitsdatum TEXT")
    op.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN status TEXT")
    op.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN bezahlt_am TEXT")
    op.execute("ALTER TABLE beitrag_sollstellung_history ADD COLUMN kassenbuchung_id INTEGER")

    # ── Trigger-Funktionen aktualisieren ──────────────────────────
    op.execute("""
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
                    created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
                ) VALUES (
                    NEW.id, NEW.version, NEW.name, NEW.abteilung_id, NEW.betrag_pro_monat, NEW.einzug_turnus,
                    NEW.gueltig_ab, NEW.gueltig_bis, NEW.bedingung_raw, NEW.bedingung_abteilung_status,
                    NEW.zahler_typ, NEW.zahler_kasse_id,
                    NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by, NEW.deleted_at, NEW.deleted_by
                );
            END IF;
            RETURN NEW;
        END; $$
    """)
    op.execute("""
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
        END; $$
    """)
    op.execute("""
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
        END; $$
    """)

    op.execute("UPDATE schema_version SET version = 18 WHERE id = 1")


def downgrade() -> None:
    op.execute("ALTER TABLE beitragsregel RENAME COLUMN betrag_pro_monat TO betrag")
    op.execute("ALTER TABLE beitragsregel RENAME COLUMN einzug_turnus TO periode")
    op.execute("ALTER TABLE beitragsregel_history RENAME COLUMN betrag_pro_monat TO betrag")
    op.execute("ALTER TABLE beitragsregel_history RENAME COLUMN einzug_turnus TO periode")

    for col in ['zahler_typ', 'zahler_kasse_id', 'bedingung_abteilung_status']:
        op.execute(f"ALTER TABLE beitragsregel DROP COLUMN IF EXISTS {col}")
        op.execute(f"ALTER TABLE beitragsregel_history DROP COLUMN IF EXISTS {col}")

    for col in ['faelligkeitsdatum', 'status', 'bezahlt_am', 'kassenbuchung_id']:
        op.execute(f"ALTER TABLE beitrag_sollstellung DROP COLUMN IF EXISTS {col}")
        op.execute(f"ALTER TABLE beitrag_sollstellung_history DROP COLUMN IF EXISTS {col}")

    op.execute("UPDATE schema_version SET version = 17 WHERE id = 1")
