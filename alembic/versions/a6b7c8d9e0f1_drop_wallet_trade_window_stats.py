from typing import Sequence, Union
from alembic import op

revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_trade_window_stats;")

def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_trade_window_stats (
            address VARCHAR(42) NOT NULL, window_size INTEGER NOT NULL,
            pnl NUMERIC(18,2) DEFAULT 0, volume NUMERIC(18,2) DEFAULT 0,
            win_rate NUMERIC(5,4) DEFAULT 0, resolved_count INTEGER DEFAULT 0,
            winning_count INTEGER DEFAULT 0, roi_pct NUMERIC(10,4) DEFAULT 0,
            computed_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (address, window_size));
    """)
