"""add avg sell price buckets to wallet_metrics_v2

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-08-13

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, Sequence[str], None] = 'f6g7h8i9j0k1'
branch_labels = None
depends_on = None

AVG_SELL_COLS = [
    "avg_sell_below_15c",
    "avg_sell_15_30c",
    "avg_sell_30_45c",
    "avg_sell_45_60c",
    "avg_sell_60_75c",
    "avg_sell_above_75c",
]

def upgrade() -> None:
    for col in AVG_SELL_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 ADD COLUMN IF NOT EXISTS {col} NUMERIC DEFAULT 0.0;")

def downgrade() -> None:
    for col in AVG_SELL_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 DROP COLUMN IF EXISTS {col};")
