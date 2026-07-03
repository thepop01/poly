"""add_leaderboard_baseline_snapshots

Revision ID: a1b2c3d4e5f0
Revises: aedadb4c98bc
Create Date: 2026-06-30 12:00:00

Add baseline balance/deposits/withdrawals snapshots to tracked_wallets
so PnL can be computed from the moment a wallet enters the leaderboard.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f0'
down_revision: Union[str, Sequence[str], None] = 'aedadb4c98bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS start_balance DOUBLE PRECISION DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS start_deposits DOUBLE PRECISION DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS start_withdrawals DOUBLE PRECISION DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS start_stats_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS start_stats_at;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS start_withdrawals;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS start_deposits;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS start_balance;")
