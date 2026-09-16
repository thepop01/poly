"""add trade metrics to wallet_stats

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS avg_buy_price NUMERIC(10,6) DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS buys_below_10c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS buys_below_20c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS buys_below_30c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS buys_below_40c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS buys_above_70c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS wins_below_10c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS wins_below_20c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS wins_below_30c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS wins_below_40c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS wins_above_70c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS losses_below_10c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS losses_below_20c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS losses_below_30c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS losses_below_40c INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS losses_above_70c INTEGER DEFAULT 0;")


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS avg_buy_price;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS buys_below_10c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS buys_below_20c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS buys_below_30c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS buys_below_40c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS buys_above_70c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS wins_below_10c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS wins_below_20c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS wins_below_30c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS wins_below_40c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS wins_above_70c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS losses_below_10c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS losses_below_20c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS losses_below_30c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS losses_below_40c;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF NOT EXISTS losses_above_70c;")
