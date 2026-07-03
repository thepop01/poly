"""add smart money trades

Revision ID: 61c49b880fa5
Revises: 10497cf0fba0
Create Date: 2026-06-28 20:34:25.229606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61c49b880fa5'
down_revision: Union[str, Sequence[str], None] = '10497cf0fba0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'smart_money_trades',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('wallet_address', sa.String(length=42), nullable=False),
        sa.Column('tx_hash', sa.String(), nullable=False),
        sa.Column('market_name', sa.String(), nullable=True),
        sa.Column('side', sa.String(), nullable=True),
        sa.Column('amount_usdc', sa.Float(), nullable=False),
        sa.Column('traded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tx_hash')
    )
    op.create_index('ix_smart_money_trades_wallet', 'smart_money_trades', ['wallet_address'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_smart_money_trades_wallet', table_name='smart_money_trades')
    op.drop_table('smart_money_trades')
