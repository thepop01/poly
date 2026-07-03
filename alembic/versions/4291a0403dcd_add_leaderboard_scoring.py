"""add_leaderboard_scoring

Revision ID: 4291a0403dcd
Revises: b93239ff6ae6
Create Date: 2026-06-22 17:50:41.129080

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4291a0403dcd'
down_revision: Union[str, Sequence[str], None] = 'b93239ff6ae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS alpha_score NUMERIC(10,4);")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS trades_2x INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS trades_1_5x INTEGER DEFAULT 0;")

def downgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS alpha_score;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS trades_2x;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS trades_1_5x;")
