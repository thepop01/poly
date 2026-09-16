"""merge_all_heads_final

Revision ID: 6739469a3e44
Revises: a1b2c3d4e5f5, c1d2e3f4a5b7
Create Date: 2026-07-13 01:19:40.179861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6739469a3e44'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f5', 'c1d2e3f4a5b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
