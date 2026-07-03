"""Add smart_money_alerts table

Revision ID: 143d4f1529ab
Revises: aedadb4c98bc
Create Date: 2026-06-29 00:46:50.368257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '143d4f1529ab'
down_revision: Union[str, Sequence[str], None] = 'aedadb4c98bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'smart_money_alerts',
        sa.Column('alert_id', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('address', sa.String(length=255), nullable=False),
        sa.Column('alert_type', sa.String(length=50), nullable=False), # 'LARGE_DEPOSIT', 'LARGE_TRADE'
        sa.Column('amount_usdc', sa.Numeric(), nullable=False),
        sa.Column('transaction_hash', sa.String(length=255), nullable=False, unique=True),
        sa.Column('market_id', sa.String(length=255), nullable=True),
        sa.Column('market_title', sa.Text(), nullable=True),
        sa.Column('side', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_smart_money_alerts_address', 'smart_money_alerts', ['address'])
    op.create_index('ix_smart_money_alerts_created_at', 'smart_money_alerts', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_smart_money_alerts_created_at', table_name='smart_money_alerts')
    op.drop_index('ix_smart_money_alerts_address', table_name='smart_money_alerts')
    op.drop_table('smart_money_alerts')
