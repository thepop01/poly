"""Add Activity lifecycle evidence, incremental scan state, and archive manifests.

Revision ID: r1s2t3u4v5
Revises: q0r1s2t3u4v5
Create Date: 2026-09-02
"""

from alembic import op


revision = "r1s2t3u4v5"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Position-grain Activity facts.  These are deliberately separate from
    # wallet_closed_positions_v2 so incomplete provenance cannot affect PnL.
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            ADD COLUMN IF NOT EXISTS activity_sell_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_sell_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_avg_sell_price NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_redeem_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_redeem_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_split_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_split_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_merge_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_merge_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_conversion_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_conversion_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_reward_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_rebate_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_yield_usdc NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_net_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS activity_event_count INTEGER,
            ADD COLUMN IF NOT EXISTS activity_distinct_event_count INTEGER,
            ADD COLUMN IF NOT EXISTS activity_first_event_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS activity_last_event_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS acquisition_status TEXT,
            ADD COLUMN IF NOT EXISTS position_recommendation TEXT,
            ADD COLUMN IF NOT EXISTS baseline_complete BOOLEAN NOT NULL DEFAULT FALSE
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_activity_scan_state_v2 (
            address VARCHAR(42) PRIMARY KEY,
            baseline_complete BOOLEAN NOT NULL DEFAULT FALSE,
            baseline_start_at TIMESTAMPTZ,
            baseline_end_at TIMESTAMPTZ,
            last_confirmed_timestamp TIMESTAMPTZ,
            last_confirmed_event_hash TEXT,
            last_scan_at TIMESTAMPTZ,
            last_audit_id UUID,
            last_error TEXT,
            next_retry_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_activity_exception_events_v2 (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            asset TEXT,
            outcome TEXT,
            event_type TEXT,
            side TEXT,
            event_timestamp TIMESTAMPTZ,
            size NUMERIC,
            usdc_size NUMERIC,
            price NUMERIC,
            transaction_hash VARCHAR(66),
            event_sha256 TEXT NOT NULL,
            snapshot_id BIGINT REFERENCES wallet_source_snapshots_v2(id),
            classification TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (address, event_sha256)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_activity_exception_lookup_v2 ON wallet_activity_exception_events_v2 (address, condition_id, event_timestamp)")

    op.execute("""
        ALTER TABLE wallet_activity_only_markets_v2
            ADD COLUMN IF NOT EXISTS activity_status TEXT NOT NULL DEFAULT 'unknown',
            ADD COLUMN IF NOT EXISTS net_shares NUMERIC,
            ADD COLUMN IF NOT EXISTS buy_cost NUMERIC,
            ADD COLUMN IF NOT EXISTS average_buy_price NUMERIC,
            ADD COLUMN IF NOT EXISTS current_position_verified BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS is_redeemable BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS canonical_position_created BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_activity_archives_v2 (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            file_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            row_count BIGINT NOT NULL,
            minimum_timestamp TIMESTAMPTZ,
            maximum_timestamp TIMESTAMPTZ,
            schema_version TEXT NOT NULL,
            compression TEXT NOT NULL,
            baseline_complete BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            verified_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_activity_archives_address_v2 ON wallet_activity_archives_v2 (address, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_activity_archives_v2")
    op.execute("ALTER TABLE wallet_activity_only_markets_v2 DROP COLUMN IF EXISTS canonical_position_created, DROP COLUMN IF EXISTS last_checked_at, DROP COLUMN IF EXISTS is_redeemable, DROP COLUMN IF EXISTS current_position_verified, DROP COLUMN IF EXISTS average_buy_price, DROP COLUMN IF EXISTS buy_cost, DROP COLUMN IF EXISTS net_shares, DROP COLUMN IF EXISTS activity_status")
    op.execute("DROP TABLE IF EXISTS wallet_activity_exception_events_v2")
    op.execute("DROP TABLE IF EXISTS wallet_activity_scan_state_v2")
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            DROP COLUMN IF EXISTS baseline_complete,
            DROP COLUMN IF EXISTS position_recommendation,
            DROP COLUMN IF EXISTS acquisition_status,
            DROP COLUMN IF EXISTS activity_last_event_at,
            DROP COLUMN IF EXISTS activity_first_event_at,
            DROP COLUMN IF EXISTS activity_distinct_event_count,
            DROP COLUMN IF EXISTS activity_event_count,
            DROP COLUMN IF EXISTS activity_net_shares,
            DROP COLUMN IF EXISTS activity_yield_usdc,
            DROP COLUMN IF EXISTS activity_rebate_usdc,
            DROP COLUMN IF EXISTS activity_reward_usdc,
            DROP COLUMN IF EXISTS activity_conversion_usdc,
            DROP COLUMN IF EXISTS activity_conversion_shares,
            DROP COLUMN IF EXISTS activity_merge_usdc,
            DROP COLUMN IF EXISTS activity_merge_shares,
            DROP COLUMN IF EXISTS activity_split_usdc,
            DROP COLUMN IF EXISTS activity_split_shares,
            DROP COLUMN IF EXISTS activity_redeem_usdc,
            DROP COLUMN IF EXISTS activity_redeem_shares,
            DROP COLUMN IF EXISTS activity_avg_sell_price,
            DROP COLUMN IF EXISTS activity_sell_usdc,
            DROP COLUMN IF EXISTS activity_sell_shares
    """)
