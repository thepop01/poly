"""drop tier column from tracked_wallets

Revision ID: 2c8c67f6fb6d
Revises: a6b7c8d9e0f1
Create Date: 2026-07-07 01:59:32.691606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c8c67f6fb6d'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('tracked_wallets', 'tier')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('tracked_wallets', sa.Column('tier', sa.VARCHAR(length=32), autoincrement=False, nullable=True))
