"""Prune trades to 500 per wallet and feed to 24h

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "i2j3k4l5m6n7"
down_revision = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add index for efficient per-wallet trade pruning
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_wallet_trades_v2_wallet_time
        ON wallet_trades_v2 (wallet_address, traded_at DESC);
    """)


def downgrade() -> None:
    op.drop_index("idx_wallet_trades_v2_wallet_time", table_name="wallet_trades_v2")
