"""add wallet_subcategory_stats

Revision ID: b3c4d5e6f7a8
Revises: f0a1b2c3d4e5
Create Date: 2026-07-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_subcategory_stats (
            address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            category       VARCHAR(50) NOT NULL,
            subcategory    VARCHAR(100) NOT NULL,
            total_pnl      NUMERIC NOT NULL DEFAULT 0,
            total_volume   NUMERIC NOT NULL DEFAULT 0,
            win_rate       NUMERIC NOT NULL DEFAULT 0,
            resolved_count INTEGER NOT NULL DEFAULT 0,
            winning_count  INTEGER NOT NULL DEFAULT 0,
            roi_pct        NUMERIC NOT NULL DEFAULT 0,
            last_active    TIMESTAMPTZ,
            computed_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, category, subcategory)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wcss_category_subcategory ON wallet_subcategory_stats(category, subcategory);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_wcss_address ON wallet_subcategory_stats(address);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_subcategory_stats;")
