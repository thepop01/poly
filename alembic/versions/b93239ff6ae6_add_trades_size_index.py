"""add_trades_size_index

Revision ID: b93239ff6ae6
Revises: 89f35540e1a5
Create Date: 2026-06-22 17:34:17.342628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b93239ff6ae6'
down_revision: Union[str, Sequence[str], None] = '89f35540e1a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_trades_size ON trades(size DESC);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_trades_size;")
