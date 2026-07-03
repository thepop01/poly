"""add_performance_indexes

Revision ID: a53ef8eaddfa
Revises: ad1dcc96ae5d
Create Date: 2026-06-25 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a53ef8eaddfa'
down_revision: Union[str, Sequence[str], None] = 'ad1dcc96ae5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Index for real-time trade polling
    op.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC);")
    
    # Index for real-time market polling
    op.execute("CREATE INDEX IF NOT EXISTS idx_markets_created_at ON markets(created_at DESC);")
    
    # Index for real-time alpha calls resolution polling
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpha_calls_resolved_at ON alpha_calls(resolved_at DESC);")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_trades_timestamp;")
    op.execute("DROP INDEX IF EXISTS idx_markets_created_at;")
    op.execute("DROP INDEX IF EXISTS idx_alpha_calls_resolved_at;")
