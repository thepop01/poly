"""add is_zero_balance to tracked_wallets

Revision ID: f2a3b4c5d6e7
Revises: a1b2c3d4e5f2, e5f6a7b8c9d0, f2a3b4c5d6e7
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = ("a1b2c3d4e5f2", "e5f6a7b8c9d0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS is_zero_balance BOOLEAN DEFAULT FALSE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_zero_balance ON tracked_wallets (is_zero_balance) WHERE is_zero_balance = TRUE")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tracked_wallets_zero_balance")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS is_zero_balance")
