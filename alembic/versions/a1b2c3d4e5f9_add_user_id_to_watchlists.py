"""add_user_id_to_watchlists

Revision ID: a1b2c3d4e5f9
Revises: a1b2c3d4e5f8
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f9'
down_revision: Union[str, None] = 'a1b2c3d4e5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_watchlists ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(user_id);")
    op.execute("ALTER TABLE user_watchlists ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ DEFAULT NOW();")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_watchlists_user_wallet ON user_watchlists(user_id, wallet_address);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_watchlists_user_wallet;")
    op.execute("ALTER TABLE user_watchlists DROP COLUMN IF EXISTS added_at;")
    op.execute("ALTER TABLE user_watchlists DROP COLUMN IF EXISTS user_id;")
