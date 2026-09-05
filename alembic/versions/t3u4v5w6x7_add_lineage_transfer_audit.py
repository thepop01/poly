"""Add complete lineage-transfer scan state and position-grain audit facts.

Revision ID: t3u4v5w6x7
Revises: s2t3u4v5w6
Create Date: 2026-09-02
"""

from alembic import op


revision = "t3u4v5w6x7"
down_revision = "s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A transaction can emit more than one transfer of the same token between
    # the same wallets.  Log index is part of its on-chain identity.
    op.execute("ALTER TABLE wallet_position_transfers_v2 ADD COLUMN IF NOT EXISTS log_index INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE wallet_position_transfers_v2 DROP CONSTRAINT IF EXISTS uq_pos_transfer")
    op.execute("""
        ALTER TABLE wallet_position_transfers_v2
        ADD CONSTRAINT uq_pos_transfer UNIQUE (tx_hash, log_index, token_id, from_address, to_address)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_position_transfers_to_token_v2 ON wallet_position_transfers_v2 (to_address, token_id)")

    op.execute("""
        ALTER TABLE wallet_activity_scan_state_v2
            ADD COLUMN IF NOT EXISTS lineage_baseline_complete BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS lineage_last_scan_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS lineage_last_error TEXT
    """)
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            ADD COLUMN IF NOT EXISTS lineage_transfer_in_shares NUMERIC NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS lineage_transfer_in_count INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS lineage_first_transfer_at TIMESTAMPTZ
    """)
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            DROP CONSTRAINT IF EXISTS wallet_position_activity_reconciliations_v2_comparison_quality_check
    """)
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            ADD CONSTRAINT wallet_position_activity_reconciliations_v2_comparison_quality_check
            CHECK (comparison_quality IN (
                'exact_activity_buy', 'activity_buy_values_differ', 'nontrade_no_buy',
                'outcome_mismatch', 'activity_absent', 'lineage_transfer_in', 'not_evaluated'
            ))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_position_activity_reconciliations_v2 DROP CONSTRAINT IF EXISTS wallet_position_activity_reconciliations_v2_comparison_quality_check")
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            ADD CONSTRAINT wallet_position_activity_reconciliations_v2_comparison_quality_check
            CHECK (comparison_quality IN (
                'exact_activity_buy', 'activity_buy_values_differ', 'nontrade_no_buy',
                'outcome_mismatch', 'activity_absent', 'not_evaluated'
            ))
    """)
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
            DROP COLUMN IF EXISTS lineage_first_transfer_at,
            DROP COLUMN IF EXISTS lineage_transfer_in_count,
            DROP COLUMN IF EXISTS lineage_transfer_in_shares
    """)
    op.execute("""
        ALTER TABLE wallet_activity_scan_state_v2
            DROP COLUMN IF EXISTS lineage_last_error,
            DROP COLUMN IF EXISTS lineage_last_scan_at,
            DROP COLUMN IF EXISTS lineage_baseline_complete
    """)
    op.execute("DROP INDEX IF EXISTS idx_position_transfers_to_token_v2")
    op.execute("ALTER TABLE wallet_position_transfers_v2 DROP CONSTRAINT IF EXISTS uq_pos_transfer")
    op.execute("ALTER TABLE wallet_position_transfers_v2 DROP COLUMN IF EXISTS log_index")
