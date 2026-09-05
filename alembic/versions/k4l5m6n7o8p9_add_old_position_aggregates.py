"""Add historical aggregate columns for positions beyond rank 5000 to wallet_metrics_v2

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wallet_metrics_v2
          -- Headline stats for positions beyond rank 5000
          ADD COLUMN IF NOT EXISTS resolved_count_old       INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS winning_count_old        INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losing_count_old         INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS win_rate_old             NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS total_volume_old         NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS total_pnl_old            NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_buy_price_old        NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS closed_cost_total        NUMERIC DEFAULT 0,

          -- Category & Subcategory breakdown for positions beyond rank 5000
          ADD COLUMN IF NOT EXISTS category_stats_old       JSONB DEFAULT '{}'::jsonb,

          -- Price bucket matrix stats for positions beyond rank 5000
          ADD COLUMN IF NOT EXISTS buys_below_15c_old       INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_below_15c_old       INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_below_15c_old     INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_below_15c_old   NUMERIC DEFAULT 0,

          ADD COLUMN IF NOT EXISTS buys_15_30c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_15_30c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_15_30c_old        INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_15_30c_old      NUMERIC DEFAULT 0,

          ADD COLUMN IF NOT EXISTS buys_30_45c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_30_45c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_30_45c_old        INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_30_45c_old      NUMERIC DEFAULT 0,

          ADD COLUMN IF NOT EXISTS buys_45_60c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_45_60c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_45_60c_old        INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_45_60c_old      NUMERIC DEFAULT 0,

          ADD COLUMN IF NOT EXISTS buys_60_75c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_60_75c_old          INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_60_75c_old        INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_60_75c_old      NUMERIC DEFAULT 0,

          ADD COLUMN IF NOT EXISTS buys_above_75c_old       INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS wins_above_75c_old       INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS losses_above_75c_old     INT DEFAULT 0,
          ADD COLUMN IF NOT EXISTS avg_sell_above_75c_old   NUMERIC DEFAULT 0,

          -- Prune cutoff & audit tracking
          ADD COLUMN IF NOT EXISTS pruned_min_closed_at     TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS pruned_at                TIMESTAMPTZ;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE wallet_metrics_v2
          DROP COLUMN IF EXISTS resolved_count_old,
          DROP COLUMN IF EXISTS winning_count_old,
          DROP COLUMN IF EXISTS losing_count_old,
          DROP COLUMN IF EXISTS win_rate_old,
          DROP COLUMN IF EXISTS total_volume_old,
          DROP COLUMN IF EXISTS total_pnl_old,
          DROP COLUMN IF EXISTS avg_buy_price_old,
          DROP COLUMN IF EXISTS closed_cost_total,
          DROP COLUMN IF EXISTS category_stats_old,
          DROP COLUMN IF EXISTS buys_below_15c_old,
          DROP COLUMN IF EXISTS wins_below_15c_old,
          DROP COLUMN IF EXISTS losses_below_15c_old,
          DROP COLUMN IF EXISTS avg_sell_below_15c_old,
          DROP COLUMN IF EXISTS buys_15_30c_old,
          DROP COLUMN IF EXISTS wins_15_30c_old,
          DROP COLUMN IF EXISTS losses_15_30c_old,
          DROP COLUMN IF EXISTS avg_sell_15_30c_old,
          DROP COLUMN IF EXISTS buys_30_45c_old,
          DROP COLUMN IF EXISTS wins_30_45c_old,
          DROP COLUMN IF EXISTS losses_30_45c_old,
          DROP COLUMN IF EXISTS avg_sell_30_45c_old,
          DROP COLUMN IF EXISTS buys_45_60c_old,
          DROP COLUMN IF EXISTS wins_45_60c_old,
          DROP COLUMN IF EXISTS losses_45_60c_old,
          DROP COLUMN IF EXISTS avg_sell_45_60c_old,
          DROP COLUMN IF EXISTS buys_60_75c_old,
          DROP COLUMN IF EXISTS wins_60_75c_old,
          DROP COLUMN IF EXISTS losses_60_75c_old,
          DROP COLUMN IF EXISTS avg_sell_60_75c_old,
          DROP COLUMN IF EXISTS buys_above_75c_old,
          DROP COLUMN IF EXISTS wins_above_75c_old,
          DROP COLUMN IF EXISTS losses_above_75c_old,
          DROP COLUMN IF EXISTS avg_sell_above_75c_old,
          DROP COLUMN IF EXISTS pruned_min_closed_at,
          DROP COLUMN IF EXISTS pruned_at;
    """)
