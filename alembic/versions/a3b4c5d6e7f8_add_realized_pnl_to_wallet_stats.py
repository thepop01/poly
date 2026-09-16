"""add realized_pnl to wallet_stats

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS realized_pnl")
