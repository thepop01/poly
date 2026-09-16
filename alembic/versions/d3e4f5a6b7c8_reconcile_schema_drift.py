"""reconcile schema drift

Revision ID: d3e4f5a6b7c8
Revises: c3d4e5f6a7b8
Create Date: 2026-07-06 12:00:00

Brings the live/production schema back under version control.

Several objects were hand-patched directly into the production database and
were never captured by a migration, so a fresh checkout could not reproduce
production. This migration recreates every drifted object. Every statement is
guarded with IF NOT EXISTS so it is a safe no-op on databases that already
have these objects (production) and fully reproduces them on a fresh DB.

Objects reconciled
------------------
Tables:
  * wallet_category_stats  - per-wallet, per-category PnL/volume/win-rate
                             (leaderboard.py, leaderboard_stats.py,
                              poly_leaderboard_sync.py)
  * tracker_lists          - user-owned wallet lists (tracker.py)
  * tracker_list_wallets   - wallets inside a tracker list (tracker.py)

Columns on tracked_wallets:
  * is_curated              BOOLEAN  DEFAULT FALSE
  * curated_at              TIMESTAMPTZ
  * last_checked_for_curated TIMESTAMPTZ
  * is_dormant              BOOLEAN  DEFAULT FALSE
  * track_count             INTEGER  DEFAULT 0
  * source_type             VARCHAR(20)   ('trade' | 'deposit' | 'leaderboard' | 'manual')
  * last_trade_at           TIMESTAMPTZ

Column on wallet_deposits:
  * is_might_cook           BOOLEAN  DEFAULT FALSE

Type choices deliberately mirror the sibling in-version tables
(wallet_trade_window_stats, tracked_wallets base): money/rate columns use
NUMERIC rather than FLOAT.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tracked_wallets: curation + dormancy + discovery-source columns
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS is_curated BOOLEAN DEFAULT FALSE;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS last_checked_for_curated TIMESTAMPTZ;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS is_dormant BOOLEAN DEFAULT FALSE;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS track_count INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS source_type VARCHAR(20);")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS last_trade_at TIMESTAMPTZ;")

    # Filters that hit these columns constantly (leaderboard.py global list).
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_is_curated ON tracked_wallets(is_curated);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallets_source_type ON tracked_wallets(source_type);")

    # ------------------------------------------------------------------
    # wallet_deposits: "might cook" flag (large deposit, zero trades)
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE wallet_deposits ADD COLUMN IF NOT EXISTS is_might_cook BOOLEAN DEFAULT FALSE;")
    # leaderboard.py filters WHERE is_might_cook = TRUE.
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_deposits_might_cook ON wallet_deposits(is_might_cook) WHERE is_might_cook = TRUE;")

    # ------------------------------------------------------------------
    # wallet_category_stats: per-wallet, per-category performance
    # Conflict/PK target is (address, category) per every upsert in code.
    # The stat columns default to 0 because the sync worker inserts only
    # (address, category, total_pnl, total_volume, computed_at).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_category_stats (
            address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            category       VARCHAR(50) NOT NULL,
            total_pnl      NUMERIC      NOT NULL DEFAULT 0,
            total_volume   NUMERIC      NOT NULL DEFAULT 0,
            win_rate       NUMERIC      NOT NULL DEFAULT 0,
            resolved_count INTEGER      NOT NULL DEFAULT 0,
            winning_count  INTEGER      NOT NULL DEFAULT 0,
            roi_pct        NUMERIC      NOT NULL DEFAULT 0,
            computed_at    TIMESTAMPTZ  DEFAULT NOW(),
            PRIMARY KEY (address, category)
        );
        """
    )
    # Category views sort by these; category is the join key.
    op.execute("CREATE INDEX IF NOT EXISTS idx_wcs_category_pnl ON wallet_category_stats(category, total_pnl DESC);")

    # ------------------------------------------------------------------
    # tracker_lists / tracker_list_wallets: user-owned wallet lists
    # (route params type list_id as int -> BIGSERIAL/BIGINT surrogate key)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_lists (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            name       VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (user_id, name)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tracker_list_wallets (
            list_id        BIGINT NOT NULL REFERENCES tracker_lists(id) ON DELETE CASCADE,
            wallet_address VARCHAR(42) NOT NULL,
            note           TEXT DEFAULT '',
            added_at       TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (list_id, wallet_address)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracker_lists_user ON tracker_lists(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tracker_list_wallets_list ON tracker_list_wallets(list_id);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tracker_list_wallets_list;")
    op.execute("DROP INDEX IF EXISTS idx_tracker_lists_user;")
    op.execute("DROP TABLE IF EXISTS tracker_list_wallets;")
    op.execute("DROP TABLE IF EXISTS tracker_lists;")

    op.execute("DROP INDEX IF EXISTS idx_wcs_category_pnl;")
    op.execute("DROP TABLE IF EXISTS wallet_category_stats;")

    op.execute("DROP INDEX IF EXISTS idx_wallet_deposits_might_cook;")
    op.execute("ALTER TABLE wallet_deposits DROP COLUMN IF EXISTS is_might_cook;")

    op.execute("DROP INDEX IF EXISTS idx_tracked_wallets_source_type;")
    op.execute("DROP INDEX IF EXISTS idx_tracked_wallets_is_curated;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS last_trade_at;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS source_type;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS track_count;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS is_dormant;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS last_checked_for_curated;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS curated_at;")
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS is_curated;")
