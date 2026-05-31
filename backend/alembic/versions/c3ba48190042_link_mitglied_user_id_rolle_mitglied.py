"""link_mitglied_user_id_rolle_mitglied

Revision ID: c3ba48190042
Revises: c5ddaac58648
Create Date: 2026-05-31

Verknüpft mitglied.user_id → users.id (optional, 1:1).
Fügt neue Rolle 'mitglied' zum CHECK-Constraint hinzu.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'c3ba48190042'
down_revision: Union[str, Sequence[str], None] = 'c5ddaac58648'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Neue Rolle 'mitglied' im CHECK-Constraint
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT users_role_check
        CHECK(role IN ('admin', 'user', 'readonly', 'special', 'mitglied'))
    """)

    # user_id FK zu mitglied
    op.execute("ALTER TABLE mitglied ADD COLUMN user_id INTEGER REFERENCES users(id)")
    op.execute("""
        CREATE UNIQUE INDEX uix_mitglied_user_id
        ON mitglied (user_id) WHERE user_id IS NOT NULL
    """)

    # user_id auch in der History-Tabelle (für vollständige Audit-Trails)
    op.execute("ALTER TABLE mitglied_history ADD COLUMN user_id INTEGER")

    op.execute("UPDATE schema_version SET version = 17 WHERE id = 1")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_mitglied_user_id")
    op.execute("ALTER TABLE mitglied DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE mitglied_history DROP COLUMN IF EXISTS user_id")

    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute("""
        ALTER TABLE users ADD CONSTRAINT users_role_check
        CHECK(role IN ('admin', 'user', 'readonly', 'special'))
    """)

    op.execute("UPDATE schema_version SET version = 16 WHERE id = 1")
