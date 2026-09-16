"""remove global win rates

Revision ID: 8bec2d190c0f
Revises: 6739469a3e44
Create Date: 2026-07-13 16:00:46.085001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8bec2d190c0f'
down_revision: Union[str, Sequence[str], None] = '6739469a3e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop legacy global tracking columns
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS win_rate;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS roi_pct;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS resolved_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS winning_count;")

    # Drop Supabase fallback columns
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_win_rate;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_roi_pct;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_resolved_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_winning_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_updated_at;")

    # Drop Triangle Logic columns from tracked_wallets (these are now stored in wallet_stats)
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS tl_win_rate;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS tl_roi_pct;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS tl_resolved_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS tl_winning_count;")


def downgrade() -> None:
    # Re-add legacy columns
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS win_rate NUMERIC DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS roi_pct NUMERIC DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS resolved_count INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS winning_count INTEGER DEFAULT 0;")

    # Re-add Supabase columns
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_win_rate NUMERIC(6,4);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_roi_pct NUMERIC(10,4);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_resolved_count INTEGER;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_winning_count INTEGER;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_updated_at TIMESTAMPTZ;")

    # Re-add Triangle Logic columns
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS tl_win_rate NUMERIC(5,4);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS tl_roi_pct NUMERIC(10,4);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS tl_resolved_count INTEGER;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS tl_winning_count INTEGER;")
