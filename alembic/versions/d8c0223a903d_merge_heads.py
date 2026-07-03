"""merge heads

Revision ID: d8c0223a903d
Revises: 143d4f1529ab, a1b2c3d4e5f9
Create Date: 2026-06-30 00:06:49.803635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8c0223a903d'
down_revision: Union[str, Sequence[str], None] = ('143d4f1529ab', 'a1b2c3d4e5f9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
