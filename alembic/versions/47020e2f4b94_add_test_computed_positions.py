"""add_test_computed_positions

Revision ID: 47020e2f4b94
Revises: 52bb6a8cb994
Create Date: 2026-07-22 00:35:38.091926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '47020e2f4b94'
down_revision: Union[str, Sequence[str], None] = '52bb6a8cb994'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'test_computed_positions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('address', sa.String(255), nullable=False),
        sa.Column('condition_id', sa.String(255), nullable=False),
        sa.Column('outcome', sa.String(255), nullable=True),
        sa.Column('total_bought_usd', sa.Float(), server_default='0', nullable=False),
        sa.Column('total_sold_usd', sa.Float(), server_default='0', nullable=False),
        sa.Column('total_buy_tokens', sa.Float(), server_default='0', nullable=False),
        sa.Column('total_sell_tokens', sa.Float(), server_default='0', nullable=False),
        sa.Column('realized_pnl', sa.Float(), server_default='0', nullable=False),
        sa.Column('cash_pnl', sa.Float(), server_default='0', nullable=False),
        sa.Column('is_resolved', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_win', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('address', 'condition_id', name='uq_test_computed_positions_addr_cond')
    )
    op.create_index('ix_test_computed_positions_address', 'test_computed_positions', ['address'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_test_computed_positions_address', table_name='test_computed_positions')
    op.drop_table('test_computed_positions')
