"""Rename historical aggregate columns from *_old to *_beyond_5k in wallet_metrics_v2

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-08-22
"""
from alembic import op

revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None

RENAMES = [
    ("resolved_count_old", "resolved_count_beyond_5k"),
    ("winning_count_old", "winning_count_beyond_5k"),
    ("losing_count_old", "losing_count_beyond_5k"),
    ("win_rate_old", "win_rate_beyond_5k"),
    ("total_volume_old", "total_volume_beyond_5k"),
    ("total_pnl_old", "total_pnl_beyond_5k"),
    ("avg_buy_price_old", "avg_buy_price_beyond_5k"),
    ("category_stats_old", "category_stats_beyond_5k"),
    ("buys_below_15c_old", "buys_below_15c_beyond_5k"),
    ("wins_below_15c_old", "wins_below_15c_beyond_5k"),
    ("losses_below_15c_old", "losses_below_15c_beyond_5k"),
    ("avg_sell_below_15c_old", "avg_sell_below_15c_beyond_5k"),
    ("buys_15_30c_old", "buys_15_30c_beyond_5k"),
    ("wins_15_30c_old", "wins_15_30c_beyond_5k"),
    ("losses_15_30c_old", "losses_15_30c_beyond_5k"),
    ("avg_sell_15_30c_old", "avg_sell_15_30c_beyond_5k"),
    ("buys_30_45c_old", "buys_30_45c_beyond_5k"),
    ("wins_30_45c_old", "wins_30_45c_beyond_5k"),
    ("losses_30_45c_old", "losses_30_45c_beyond_5k"),
    ("avg_sell_30_45c_old", "avg_sell_30_45c_beyond_5k"),
    ("buys_45_60c_old", "buys_45_60c_beyond_5k"),
    ("wins_45_60c_old", "wins_45_60c_beyond_5k"),
    ("losses_45_60c_old", "losses_45_60c_beyond_5k"),
    ("avg_sell_45_60c_old", "avg_sell_45_60c_beyond_5k"),
    ("buys_60_75c_old", "buys_60_75c_beyond_5k"),
    ("wins_60_75c_old", "wins_60_75c_beyond_5k"),
    ("losses_60_75c_old", "losses_60_75c_beyond_5k"),
    ("avg_sell_60_75c_old", "avg_sell_60_75c_beyond_5k"),
    ("buys_above_75c_old", "buys_above_75c_beyond_5k"),
    ("wins_above_75c_old", "wins_above_75c_beyond_5k"),
    ("losses_above_75c_old", "losses_above_75c_beyond_5k"),
    ("avg_sell_above_75c_old", "avg_sell_above_75c_beyond_5k"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for old_col, new_col in RENAMES:
        exists = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'wallet_metrics_v2' AND column_name = :c",
            {"c": old_col},
        ).scalar()
        if exists:
            op.execute(f"ALTER TABLE wallet_metrics_v2 RENAME COLUMN {old_col} TO {new_col};")


def downgrade() -> None:
    conn = op.get_bind()
    for old_col, new_col in RENAMES:
        exists = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'wallet_metrics_v2' AND column_name = :c",
            {"c": new_col},
        ).scalar()
        if exists:
            op.execute(f"ALTER TABLE wallet_metrics_v2 RENAME COLUMN {new_col} TO {old_col};")
