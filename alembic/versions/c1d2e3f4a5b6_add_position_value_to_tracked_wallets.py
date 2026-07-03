"""add position_value to tracked_wallets

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5g6
Create Date: 2026-07-02 12:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS position_value NUMERIC(18,2) DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS strategy VARCHAR(64);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS active_days INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS trades_2x INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS trades_1_5x INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS added_reason VARCHAR(64);")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC(18,2) DEFAULT 0;")


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS unrealized_pnl;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS added_reason;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS trades_1_5x;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS trades_2x;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS active_days;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS strategy;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS position_value;")
