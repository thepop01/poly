"""add_supabase_winrate_columns

Revision ID: a1b2c3d4e5f5
Revises: f5a6b7c8d9e0
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f5'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Supabase win rate columns to tracked_wallets
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_win_rate NUMERIC;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_roi_pct NUMERIC;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_resolved_count INTEGER;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_winning_count INTEGER;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS sb_updated_at TIMESTAMPTZ;")

    # Add Supabase win rate columns to wallet_stats
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS sb_win_rate NUMERIC;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS sb_roi_pct NUMERIC;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS sb_resolved_count INTEGER;")
    op.execute("ALTER TABLE wallet_stats ADD COLUMN IF NOT EXISTS sb_winning_count INTEGER;")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_win_rate;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_roi_pct;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_resolved_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_winning_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS sb_updated_at;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS sb_win_rate;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS sb_roi_pct;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS sb_resolved_count;")
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS sb_winning_count;")

