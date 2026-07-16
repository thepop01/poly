"""reconcile wallets_v2 operational columns

Revision ID: a829c714e8cd
Revises: 591013c5e504
Create Date: 2026-07-16 01:37:19.755047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a829c714e8cd'
down_revision: Union[str, Sequence[str], None] = '591013c5e504'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE wallets_v2
          ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS last_checked_for_curated TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS pnl_source VARCHAR(16)
    """)
    # Retire MIGHT_COOK as a tier: it's a badge, not a tier.
    op.execute("""
        UPDATE wallets_v2
           SET might_cook_type = COALESCE(might_cook_type, 'deposit_no_trades'),
               tier = 'NEW',
               tier_reason = 'might-cook reclassified: deposit >= $5k, 0 trades'
         WHERE tier = 'MIGHT_COOK'
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallets_v2_tier_dormant ON wallets_v2 (tier, is_dormant)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_wallets_v2_tier_dormant")
    op.execute("""
        ALTER TABLE wallets_v2
          DROP COLUMN IF EXISTS next_check_at,
          DROP COLUMN IF EXISTS curated_at,
          DROP COLUMN IF EXISTS last_checked_for_curated,
          DROP COLUMN IF EXISTS pnl_source
    """)
