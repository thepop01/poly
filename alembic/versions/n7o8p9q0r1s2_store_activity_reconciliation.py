"""Retain raw Activity backfills and per-position reconciliation facts.

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-09-01
"""

from alembic import op


revision = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_activity_events_v2 (
            id BIGSERIAL PRIMARY KEY,
            snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
            address VARCHAR(42) NOT NULL,
            event_sha256 TEXT NOT NULL,
            condition_id VARCHAR(255),
            asset TEXT,
            outcome TEXT,
            event_type TEXT,
            side TEXT,
            event_timestamp TIMESTAMPTZ,
            size NUMERIC,
            usdc_size NUMERIC,
            price NUMERIC,
            transaction_hash VARCHAR(66),
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (snapshot_id, event_sha256)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_activity_events_market_v2 ON wallet_activity_events_v2 (address, condition_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_activity_events_snapshot_v2 ON wallet_activity_events_v2 (snapshot_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_position_activity_reconciliations_v2 (
            id BIGSERIAL PRIMARY KEY,
            audit_id UUID NOT NULL,
            snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            outcome TEXT NOT NULL,
            classification TEXT NOT NULL CHECK (classification IN (
                'direct_activity_buy', 'activity_same_leg_nontrade',
                'activity_outcome_differs', 'activity_absent'
            )),
            db_total_bought NUMERIC,
            db_avg_buy_price NUMERIC,
            db_cost_basis NUMERIC,
            db_realized_pnl NUMERIC,
            activity_buy_shares NUMERIC,
            activity_buy_usdc NUMERIC,
            activity_avg_buy_price NUMERIC,
            shares_delta NUMERIC,
            cost_basis_delta NUMERIC,
            activity_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (audit_id, address, condition_id, outcome)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_position_activity_reconciliation_lookup_v2 ON wallet_position_activity_reconciliations_v2 (address, classification, audit_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_activity_only_markets_v2 (
            id BIGSERIAL PRIMARY KEY,
            audit_id UUID NOT NULL,
            snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            event_count INTEGER NOT NULL,
            outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (audit_id, address, condition_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_activity_only_markets_lookup_v2 ON wallet_activity_only_markets_v2 (address, audit_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_activity_only_markets_v2")
    op.execute("DROP TABLE IF EXISTS wallet_position_activity_reconciliations_v2")
    op.execute("DROP TABLE IF EXISTS wallet_activity_events_v2")
