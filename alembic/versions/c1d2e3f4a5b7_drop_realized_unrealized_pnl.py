"""drop realized_pnl and unrealized_pnl from wallet_stats and tracked_wallets

Revision ID: c1d2e3f4a5b7
Revises: b0c1d2e3f4a5
Create Date: 2026-07-12
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c1d2e3f4a5b7'
down_revision: Union[str, Sequence[str], None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS realized_pnl")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS unrealised_pnl")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS unrealized_pnl")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS realized_pnl")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS unrealized_pnl")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC DEFAULT 0")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC DEFAULT 0")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC DEFAULT 0")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS unrealised_pnl NUMERIC(18,2) DEFAULT 0")
