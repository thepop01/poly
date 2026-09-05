"""Add evidence-backed eligibility for wallet position rows.

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-09-01
"""

from alembic import op


revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_closed_positions_v2 ADD COLUMN IF NOT EXISTS metrics_eligible BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE wallet_closed_positions_v2 ADD COLUMN IF NOT EXISTS exclusion_reason TEXT")
    op.execute("ALTER TABLE wallet_closed_positions_v2 ADD COLUMN IF NOT EXISTS excluded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE wallet_closed_positions_v2 ADD COLUMN IF NOT EXISTS source_asset TEXT")
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_source_snapshots_v2 (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            source TEXT NOT NULL,
            complete BOOLEAN NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payload_sha256 TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_source_snapshots_address_v2 ON wallet_source_snapshots_v2 (address, fetched_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_position_evidence_v2 (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            asset TEXT,
            outcome TEXT,
            evidence_type TEXT NOT NULL,
            transaction_hash VARCHAR(66),
            snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_position_evidence_lookup_v2 ON wallet_position_evidence_v2 (address, condition_id, asset)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_position_audit_decisions_v2 (
            id BIGSERIAL PRIMARY KEY,
            audit_id UUID NOT NULL,
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            outcome TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('eligible', 'review_required', 'excluded_proven')),
            reason TEXT NOT NULL,
            evidence_id BIGINT REFERENCES wallet_position_evidence_v2(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_position_audit_decisions_audit_v2 ON wallet_position_audit_decisions_v2 (audit_id, address)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_api_rate_limit_buckets (
            endpoint TEXT PRIMARY KEY,
            tokens NUMERIC NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_api_rate_limit_buckets;")
    op.execute("DROP TABLE IF EXISTS wallet_position_audit_decisions_v2;")
    op.execute("DROP TABLE IF EXISTS wallet_position_evidence_v2;")
    op.execute("DROP TABLE IF EXISTS wallet_source_snapshots_v2;")
    op.execute("ALTER TABLE wallet_closed_positions_v2 DROP COLUMN IF EXISTS source_asset")
    op.execute("ALTER TABLE wallet_closed_positions_v2 DROP COLUMN IF EXISTS excluded_at")
    op.execute("ALTER TABLE wallet_closed_positions_v2 DROP COLUMN IF EXISTS exclusion_reason")
    op.execute("ALTER TABLE wallet_closed_positions_v2 DROP COLUMN IF EXISTS metrics_eligible")
