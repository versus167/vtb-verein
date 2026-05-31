"""partial_unique_index_users_email_username

Revision ID: c5ddaac58648
Revises: 67b540c93843
Create Date: 2026-05-31 09:31:49.869396

Ersetzt die harten UNIQUE-Constraints auf users.email und users.username
durch partielle Unique-Indizes (WHERE deleted_at IS NULL), damit
soft-gelöschte Accounts die E-Mail/den Benutzernamen nicht dauerhaft blockieren.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c5ddaac58648'
down_revision: Union[str, Sequence[str], None] = '67b540c93843'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alte column-level UNIQUE-Constraints droppen
    op.drop_constraint('users_email_key',    'users', type_='unique')
    op.drop_constraint('users_username_key', 'users', type_='unique')

    # Partielle Unique-Indizes nur für nicht-gelöschte User
    op.execute("""
        CREATE UNIQUE INDEX uix_users_email_active
        ON users (email)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uix_users_username_active
        ON users (username)
        WHERE deleted_at IS NULL
    """)

    # Schema-Version auf 16 erhöhen
    op.execute("UPDATE schema_version SET version = 16 WHERE id = 1")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_users_email_active")
    op.execute("DROP INDEX IF EXISTS uix_users_username_active")

    op.create_unique_constraint('users_email_key',    'users', ['email'])
    op.create_unique_constraint('users_username_key', 'users', ['username'])

    op.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
