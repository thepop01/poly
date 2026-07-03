"""add_realized_unrealized_pnl

Revision ID: 0a222b92e6c3
Revises: 620cdef12984
Create Date: 2026-06-28 17:06:44.499035

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a222b92e6c3'
down_revision: Union[str, Sequence[str], None] = '620cdef12984'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN realized_pnl NUMERIC DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN unrealized_pnl NUMERIC DEFAULT 0;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN unrealized_pnl;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN realized_pnl;")
