"""add website pnl columns to tracked_wallets

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-03 12:00:00

Stores the all-time PnL/volume/rank/username as reported by Polymarket's
public /v1/leaderboard?user= endpoint (the same numbers shown on the website).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS website_pnl NUMERIC(18,2);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS website_volume NUMERIC(18,2);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS website_rank BIGINT;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS username VARCHAR(255);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS website_pnl_updated_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS website_pnl_updated_at;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS username;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS website_rank;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS website_volume;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS website_pnl;")
