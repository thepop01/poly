"""add balance deposits withdrawals

Revision ID: aedadb4c98bc
Revises: 61c49b880fa5
Create Date: 2026-06-28 22:00:14.201177

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aedadb4c98bc'
down_revision: Union[str, Sequence[str], None] = '61c49b880fa5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tracked_wallets', sa.Column('balance', sa.Float(), server_default='0.0', nullable=False))
    op.add_column('tracked_wallets', sa.Column('deposits', sa.Float(), server_default='0.0', nullable=False))
    op.add_column('tracked_wallets', sa.Column('withdrawals', sa.Float(), server_default='0.0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tracked_wallets', 'withdrawals')
    op.drop_column('tracked_wallets', 'deposits')
    op.drop_column('tracked_wallets', 'balance')
