"""add_tracked_wallets_table

Revision ID: f1a2b3c4d5e6
Revises: a53ef8eaddfa
Create Date: 2026-06-28 10:45:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'a53ef8eaddfa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tracked_wallets (
            address          VARCHAR(42) PRIMARY KEY,
            discovery_source TEXT[]      DEFAULT '{}',

            -- All-time stats
            total_pnl        NUMERIC     DEFAULT 0,
            total_volume     NUMERIC     DEFAULT 0,
            win_rate         NUMERIC     DEFAULT 0,
            roi_pct          NUMERIC     DEFAULT 0,
            resolved_count   INTEGER     DEFAULT 0,
            winning_count    INTEGER     DEFAULT 0,

            -- Weekly stats (last 7 days)
            pnl_weekly       NUMERIC     DEFAULT 0,
            volume_weekly    NUMERIC     DEFAULT 0,

            -- Monthly stats (last 30 days)
            pnl_monthly      NUMERIC     DEFAULT 0,
            volume_monthly   NUMERIC     DEFAULT 0,

            -- Metadata
            tier             VARCHAR(20) DEFAULT 'Silver',
            alpha_score      NUMERIC     DEFAULT 0,
            added_at         TIMESTAMPTZ DEFAULT NOW(),
            last_indexed     TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_total_pnl ON tracked_wallets(total_pnl DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_total_volume ON tracked_wallets(total_volume DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_win_rate ON tracked_wallets(win_rate DESC);")

    # Queue table for wallets waiting to be evaluated
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_discovery_queue (
            address     VARCHAR(42) PRIMARY KEY,
            spotted_at  TIMESTAMPTZ DEFAULT NOW(),
            processed   BOOLEAN     DEFAULT FALSE
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_discovery_queue;")
    op.execute("DROP TABLE IF EXISTS tracked_wallets;")
