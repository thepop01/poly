"""add wallet_trade_window_stats table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5fa
Create Date: 2026-07-05 16:00:00

Stores per-wallet PnL/volume/win_rate for different trade windows (last N trades).
Used by curated wallet list to show short-term vs long-term performance.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_trade_window_stats (
            address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            window_size    INTEGER NOT NULL,
            pnl            NUMERIC(18,2) NOT NULL DEFAULT 0,
            volume         NUMERIC(18,2) NOT NULL DEFAULT 0,
            win_rate       NUMERIC(5,4) NOT NULL DEFAULT 0,
            resolved_count INTEGER NOT NULL DEFAULT 0,
            winning_count  INTEGER NOT NULL DEFAULT 0,
            roi_pct        NUMERIC(10,4) NOT NULL DEFAULT 0,
            computed_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, window_size)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tw_window_pnl ON wallet_trade_window_stats(address, window_size, pnl DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_trade_window_stats;")
