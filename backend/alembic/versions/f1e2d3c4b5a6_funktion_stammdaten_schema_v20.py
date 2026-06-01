"""funktion_stammdaten_schema_v20

Revision ID: f1e2d3c4b5a6
Revises: a8f3c12d9e04
Create Date: 2026-06-01

Führt Funktions-Stammdatentabelle ein (konfigurierbare Funktionstypen
statt hardcodierter Liste).
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, Sequence[str], None] = 'a8f3c12d9e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
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

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_funktion_key_active
        ON funktion (key)
        WHERE deleted_at IS NULL
    """)

    for key, name in [
        ('schiedsrichter',   'Schiedsrichter'),
        ('uebungsleiter',    'Übungsleiter'),
        ('abteilungsleiter', 'Abteilungsleiter'),
    ]:
        op.execute(f"""
            INSERT INTO funktion (key, name, created_by)
            SELECT '{key}', '{name}', 'system'
            WHERE NOT EXISTS (SELECT 1 FROM funktion WHERE key = '{key}' AND deleted_at IS NULL)
        """)

    op.execute("""
        UPDATE schema_version SET version = 20, updated_at = CURRENT_TIMESTAMP
        WHERE version = 19
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS funktion")
    op.execute("""
        UPDATE schema_version SET version = 19, updated_at = CURRENT_TIMESTAMP
        WHERE version = 20
    """)
