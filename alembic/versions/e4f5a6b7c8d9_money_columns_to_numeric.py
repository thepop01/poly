"""convert money columns from float to numeric

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-06 12:30:00

FLOAT/DOUBLE PRECISION columns silently accumulate binary rounding error
across aggregation and are unsafe for money. Converts the remaining
Float-typed financial columns to NUMERIC(18,2) to match every sibling
money column added since (wallet_stats, wallet_category_stats,
wallet_trade_window_stats, curated_wallet_trades all already use NUMERIC).

Columns converted:
  * smart_money_trades.amount_usdc
  * tracked_wallets.balance
  * tracked_wallets.deposits
  * tracked_wallets.withdrawals
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE smart_money_trades ALTER COLUMN amount_usdc TYPE NUMERIC(18,2) USING amount_usdc::NUMERIC(18,2);")
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN balance TYPE NUMERIC(18,2) USING balance::NUMERIC(18,2);")
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN deposits TYPE NUMERIC(18,2) USING deposits::NUMERIC(18,2);")
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN withdrawals TYPE NUMERIC(18,2) USING withdrawals::NUMERIC(18,2);")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN withdrawals TYPE FLOAT USING withdrawals::FLOAT;")
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN deposits TYPE FLOAT USING deposits::FLOAT;")
    op.execute("ALTER TABLE tracked_wallets ALTER COLUMN balance TYPE FLOAT USING balance::FLOAT;")
    op.execute("ALTER TABLE smart_money_trades ALTER COLUMN amount_usdc TYPE FLOAT USING amount_usdc::FLOAT;")
