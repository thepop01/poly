"""update price buckets analytics

Revision ID: e6f7a8b9c0d1
Revises: c9e01f2a3b4c
Create Date: 2026-08-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'c9e01f2a3b4c'
branch_labels = None
depends_on = None

OLD_COLS = [
    "buys_below_10c", "buys_below_20c", "buys_below_30c", "buys_below_40c", "buys_above_70c",
    "wins_below_10c", "wins_below_20c", "wins_below_30c", "wins_below_40c", "wins_above_70c",
    "losses_below_10c", "losses_below_20c", "losses_below_30c", "losses_below_40c", "losses_above_70c"
]

NEW_COLS = [
    "buys_below_15c", "wins_below_15c", "losses_below_15c",
    "buys_15_30c", "wins_15_30c", "losses_15_30c",
    "buys_30_45c", "wins_30_45c", "losses_30_45c",
    "buys_45_60c", "wins_45_60c", "losses_45_60c",
    "buys_60_75c", "wins_60_75c", "losses_60_75c",
    "buys_above_75c", "wins_above_75c", "losses_above_75c"
]

def upgrade() -> None:
    for col in OLD_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 DROP COLUMN IF EXISTS {col};")
    for col in NEW_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 0;")

def downgrade() -> None:
    for col in NEW_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 DROP COLUMN IF EXISTS {col};")
    for col in OLD_COLS:
        op.execute(f"ALTER TABLE wallet_metrics_v2 ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 0;")
