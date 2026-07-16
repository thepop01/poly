"""add wallet_closed_positions, rename to global_wallet_trades, add wallet_positions, wallet_combo_positions, trade columns

Revision ID: f0a1b2c3d4e5
Revises: c8d9e0f1a2b3
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename curated_wallet_trades → global_wallet_trades + add columns
    op.execute("ALTER TABLE curated_wallet_trades RENAME TO global_wallet_trades;")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN is_curated BOOLEAN NOT NULL DEFAULT FALSE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_gwt_is_curated ON global_wallet_trades(is_curated);")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN asset VARCHAR(66);")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN slug TEXT;")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN icon TEXT;")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN event_slug TEXT;")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN outcome VARCHAR(50);")
    op.execute("ALTER TABLE global_wallet_trades ADD COLUMN outcome_index INTEGER;")

    # 2. wallet_closed_positions
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_closed_positions (
            address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            condition_id   VARCHAR(255) NOT NULL,
            title          TEXT,
            realized_pnl   NUMERIC(18,2) NOT NULL DEFAULT 0,
            total_bought   NUMERIC(18,2) NOT NULL DEFAULT 0,
            end_date       TIMESTAMPTZ,
            category       VARCHAR(50),
            subcategory    VARCHAR(100),
            fetched_at     TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, condition_id)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wcp_address_enddate ON wallet_closed_positions(address, end_date DESC);")

    # 3. wallet_positions
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_positions (
            address              VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            condition_id         VARCHAR(66) NOT NULL,
            asset                VARCHAR(66),
            title                TEXT,
            slug                 TEXT,
            icon                 TEXT,
            event_slug           TEXT,
            outcome              VARCHAR(50),
            outcome_index        INTEGER,
            opposite_outcome     VARCHAR(50),
            opposite_asset       VARCHAR(66),
            size                 NUMERIC(18,6) NOT NULL DEFAULT 0,
            avg_price            NUMERIC(18,6) NOT NULL DEFAULT 0,
            initial_value        NUMERIC(18,6) NOT NULL DEFAULT 0,
            current_value        NUMERIC(18,6) NOT NULL DEFAULT 0,
            cash_pnl             NUMERIC(18,6) NOT NULL DEFAULT 0,
            percent_pnl          NUMERIC(10,4) NOT NULL DEFAULT 0,
            total_bought         NUMERIC(18,6) NOT NULL DEFAULT 0,
            realized_pnl         NUMERIC(18,6) NOT NULL DEFAULT 0,
            percent_realized_pnl NUMERIC(10,4) NOT NULL DEFAULT 0,
            cur_price            NUMERIC(10,6) NOT NULL DEFAULT 0,
            redeemable           BOOLEAN NOT NULL DEFAULT FALSE,
            mergeable            BOOLEAN NOT NULL DEFAULT FALSE,
            end_date             TIMESTAMPTZ,
            negative_risk        BOOLEAN NOT NULL DEFAULT FALSE,
            category             VARCHAR(50),
            subcategory          VARCHAR(100),
            computed_at          TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, condition_id)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wp_address ON wallet_positions(address);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_wp_category ON wallet_positions(category);")

    # 4. wallet_combo_positions
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_combo_positions (
            address               VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            combo_condition_id    VARCHAR(66) NOT NULL,
            status                VARCHAR(20) NOT NULL DEFAULT 'OPEN',
            shares_balance        NUMERIC(18,6) NOT NULL DEFAULT 0,
            entry_avg_price_usdc  NUMERIC(18,6) NOT NULL DEFAULT 0,
            entry_cost_usdc       NUMERIC(18,6) NOT NULL DEFAULT 0,
            realized_payout_usdc  NUMERIC(18,6) NOT NULL DEFAULT 0,
            total_cost_usdc       NUMERIC(18,6) NOT NULL DEFAULT 0,
            legs_total            INTEGER NOT NULL DEFAULT 0,
            legs_resolved         INTEGER NOT NULL DEFAULT 0,
            first_entry_at        TIMESTAMPTZ,
            resolved_at           TIMESTAMPTZ,
            computed_at           TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, combo_condition_id)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wcp_combo_status ON wallet_combo_positions(status);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_combo_positions;")
    op.execute("DROP TABLE IF EXISTS wallet_positions;")
    op.execute("DROP TABLE IF EXISTS wallet_closed_positions;")
    op.execute("DROP INDEX IF EXISTS idx_gwt_is_curated;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS outcome_index;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS outcome;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS event_slug;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS icon;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS slug;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS asset;")
    op.execute("ALTER TABLE global_wallet_trades DROP COLUMN IF EXISTS is_curated;")
    op.execute("ALTER TABLE global_wallet_trades RENAME TO curated_wallet_trades;")
