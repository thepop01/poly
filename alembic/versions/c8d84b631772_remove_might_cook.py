"""remove might cook

Revision ID: c8d84b631772
Revises: 47020e2f4b94
Create Date: 2026-08-09 00:09:34.492878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d84b631772'
down_revision: Union[str, Sequence[str], None] = '47020e2f4b94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('wallets_v2', 'might_cook_type')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('wallets_v2', sa.Column('might_cook_type', sa.String(20), nullable=True))
