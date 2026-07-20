"""add curated_trades and sync cursor

Revision ID: 4d555508b363
Revises: 05d6efbb55db
Create Date: 2026-07-20 23:30:53.231545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d555508b363'
down_revision: Union[str, Sequence[str], None] = '05d6efbb55db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "curated_trades",
        sa.Column("tx_hash", sa.Text, nullable=False),
        sa.Column("log_index", sa.Integer, nullable=False),
        sa.Column("wallet_address", sa.Text, nullable=False),
        sa.Column("condition_id", sa.Text, nullable=True),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("side", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric, server_default="0"),
        sa.Column("size", sa.Numeric, server_default="0"),
        sa.Column("amount_usdc", sa.Numeric, server_default="0"),
        sa.Column("traded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("market_name", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("subcategory", sa.Text, nullable=True),
        sa.Column("block_number", sa.BigInteger, nullable=True),
        sa.PrimaryKeyConstraint("tx_hash", "log_index"),
    )
    op.create_index("ix_curated_trades_wallet_time",
                    "curated_trades", ["wallet_address", "traded_at"])
    op.create_table(
        "curated_trade_sync",
        sa.Column("wallet_address", sa.Text, primary_key=True),
        sa.Column("last_synced_block", sa.BigInteger, server_default="0"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("curated_trade_sync")
    op.drop_index("ix_curated_trades_wallet_time", table_name="curated_trades")
    op.drop_table("curated_trades")
