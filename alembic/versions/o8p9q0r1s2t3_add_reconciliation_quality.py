"""Add numerical comparison quality to retained position reconciliations.

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-09-01
"""

from alembic import op


revision = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wallet_position_activity_reconciliations_v2
        ADD COLUMN IF NOT EXISTS comparison_quality TEXT NOT NULL DEFAULT 'not_evaluated'
        CHECK (comparison_quality IN (
            'exact_activity_buy', 'activity_buy_values_differ',
            'nontrade_no_buy', 'outcome_mismatch', 'activity_absent', 'not_evaluated'
        ))
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_position_activity_reconciliation_quality_v2 ON wallet_position_activity_reconciliations_v2 (address, comparison_quality, audit_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_position_activity_reconciliation_quality_v2")
    op.execute("ALTER TABLE wallet_position_activity_reconciliations_v2 DROP COLUMN IF EXISTS comparison_quality")
