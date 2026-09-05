"""Live per-leg activity aggregates plus position token keys.

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-09-05
"""

from alembic import op


revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS wallet_market_activity_v2 (
    address            VARCHAR(42) NOT NULL,
    condition_id       VARCHAR(255) NOT NULL,
    outcome_token_id   NUMERIC NOT NULL DEFAULT 0,
    outcome_label      TEXT NOT NULL DEFAULT '',
    trade_buys         INTEGER NOT NULL DEFAULT 0,
    buy_shares         NUMERIC NOT NULL DEFAULT 0,
    buy_cost           NUMERIC NOT NULL DEFAULT 0,
    trade_sells        INTEGER NOT NULL DEFAULT 0,
    sell_shares        NUMERIC NOT NULL DEFAULT 0,
    sell_proceeds      NUMERIC NOT NULL DEFAULT 0,
    redeem_count       INTEGER NOT NULL DEFAULT 0,
    redeem_usdc        NUMERIC NOT NULL DEFAULT 0,
    split_shares       NUMERIC NOT NULL DEFAULT 0,
    merge_shares       NUMERIC NOT NULL DEFAULT 0,
    conversion_events  INTEGER NOT NULL DEFAULT 0,
    reward_usdc        NUMERIC NOT NULL DEFAULT 0,
    event_count        INTEGER NOT NULL DEFAULT 0,
    first_event_at     TIMESTAMPTZ,
    last_event_at      TIMESTAMPTZ,
    last_event_ts      BIGINT NOT NULL DEFAULT 0,
    last_event_sha     TEXT NOT NULL DEFAULT '',
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (address, condition_id, outcome_token_id)
)""")
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_wma_updated
    ON wallet_market_activity_v2(address, updated_at DESC)""")
    # Token key on position rows so legs join exactly (labels stay for display).
    # Nullable adds are metadata-only; existing rows keep NULL until resynced.
    op.execute("ALTER TABLE wallet_positions_v2 "
               "ADD COLUMN IF NOT EXISTS asset_token_id NUMERIC")
    op.execute("ALTER TABLE wallet_closed_positions_v2 "
               "ADD COLUMN IF NOT EXISTS asset_token_id NUMERIC")
    # 159M-row table: build concurrently outside the transaction so the
    # upgrade never blocks writes (same pattern as w6x7y8z9a0b1).
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_closed_asset_token
    ON wallet_closed_positions_v2(address, condition_id, asset_token_id)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_closed_asset_token")
    op.execute("ALTER TABLE wallet_closed_positions_v2 DROP COLUMN IF EXISTS asset_token_id")
    op.execute("ALTER TABLE wallet_positions_v2 DROP COLUMN IF EXISTS asset_token_id")
    op.execute("DROP INDEX IF EXISTS idx_wma_updated")
    op.execute("DROP TABLE IF EXISTS wallet_market_activity_v2")
