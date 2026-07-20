"""drop global_wallet_trades

Revision ID: 805e4fd77203
Revises: 4d555508b363
Create Date: 2026-07-20 23:32:30.534545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '805e4fd77203'
down_revision: Union[str, Sequence[str], None] = '4d555508b363'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("global_wallet_trades")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "global_wallet_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("wallet_address", sa.Text),
        sa.Column("tx_hash", sa.Text),
        sa.Column("condition_id", sa.Text),
        sa.Column("market_name", sa.Text),
        sa.Column("side", sa.Text),
        sa.Column("price", sa.Numeric),
        sa.Column("size", sa.Numeric),
        sa.Column("amount_usdc", sa.Numeric),
        sa.Column("traded_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("category", sa.Text),
        sa.Column("subcategory", sa.Text),
        sa.UniqueConstraint("wallet_address", "tx_hash"),
    )
