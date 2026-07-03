"""add_max_trade_size

Revision ID: 10497cf0fba0
Revises: 0a222b92e6c3
Create Date: 2026-06-28 18:44:52.076236

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10497cf0fba0'
down_revision: Union[str, Sequence[str], None] = '0a222b92e6c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS max_trade_size NUMERIC DEFAULT 0;")

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS max_trade_size;")
