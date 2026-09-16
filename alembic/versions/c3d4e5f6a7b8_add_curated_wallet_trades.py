"""add curated_wallet_trades table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-05 18:00:00

Stores ALL trades for curated wallets (no $1k threshold).
Keeps detailed subcategory (NFL, NBA, EPL) for records.
wallet_tags uses flattened subcategory (Football, Basketball, Soccer) for filters.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'curated_wallet_trades',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('wallet_address', sa.String(length=42), nullable=False),
        sa.Column('tx_hash', sa.String(length=66), nullable=False),
        sa.Column('condition_id', sa.String(length=66), nullable=True),
        sa.Column('market_name', sa.Text(), nullable=True),
        sa.Column('side', sa.String(length=10), nullable=True),
        sa.Column('price', sa.Numeric(), nullable=True),
        sa.Column('size', sa.Numeric(), nullable=True),
        sa.Column('amount_usdc', sa.Numeric(), nullable=True),
        sa.Column('traded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('detailed_subcategory', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('wallet_address', 'tx_hash', name='uq_curated_trades_wallet_tx'),
    )
    op.create_index('ix_curated_trades_wallet', 'curated_wallet_trades', ['wallet_address'])
    op.create_index('ix_curated_trades_time', 'curated_wallet_trades', ['traded_at'])


def downgrade() -> None:
    op.drop_index('ix_curated_trades_time', table_name='curated_wallet_trades')
    op.drop_index('ix_curated_trades_wallet', table_name='curated_wallet_trades')
    op.drop_table('curated_wallet_trades')
