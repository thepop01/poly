"""Keep the exact full Activity snapshot pending analysis.

Revision ID: s2t3u4v5w6
Revises: r1s2t3u4v5
Create Date: 2026-09-02
"""

from alembic import op


revision = "s2t3u4v5w6"
down_revision = "r1s2t3u4v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wallet_activity_scan_state_v2
            ADD COLUMN IF NOT EXISTS pending_snapshot_id BIGINT
                REFERENCES wallet_source_snapshots_v2(id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_activity_scan_pending_snapshot_v2
            ON wallet_activity_scan_state_v2 (pending_snapshot_id)
            WHERE pending_snapshot_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_activity_scan_pending_snapshot_v2")
    op.execute("""
        ALTER TABLE wallet_activity_scan_state_v2
            DROP COLUMN IF EXISTS pending_snapshot_id
    """)
