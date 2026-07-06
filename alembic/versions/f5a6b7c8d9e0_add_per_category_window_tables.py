"""add per-category window tables + last_active + pnl_source

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-06 12:00:00
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WINDOWS = [100, 300, 800, 1500, 2500]


def upgrade() -> None:
    for w in WINDOWS:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS wallet_window_{w} (
                address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
                category       VARCHAR(20) NOT NULL,
                pnl            NUMERIC(18,2) NOT NULL DEFAULT 0,
                volume         NUMERIC(18,2) NOT NULL DEFAULT 0,
                win_rate       NUMERIC(5,4)  NOT NULL DEFAULT 0,
                roi_pct        NUMERIC(10,4) NOT NULL DEFAULT 0,
                resolved_count INTEGER       NOT NULL DEFAULT 0,
                winning_count  INTEGER       NOT NULL DEFAULT 0,
                last_active    TIMESTAMPTZ,
                computed_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (address, category)
            );
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_ww{w}_cat_pnl ON wallet_window_{w}(category, pnl DESC);")
    op.execute("ALTER TABLE wallet_category_stats ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS pnl_source VARCHAR(16);")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS pnl_source;")
    op.execute("ALTER TABLE wallet_category_stats DROP COLUMN IF EXISTS last_active;")
    for w in WINDOWS:
        op.execute(f"DROP TABLE IF EXISTS wallet_window_{w};")
