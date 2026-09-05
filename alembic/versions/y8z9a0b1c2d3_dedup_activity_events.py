"""Deduplicate activity events across snapshots.

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-09-05
"""

from alembic import op

revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Production built this CONCURRENTLY via script (non-blocking on 37M
    # rows); plain CREATE is fine for fresh environments. Writers insert
    # ON CONFLICT (address, event_sha256) so incremental resume overlap
    # never stores the same event twice.
    op.execute("""
        DELETE FROM wallet_activity_events_v2 a
        USING wallet_activity_events_v2 b
        WHERE b.address = a.address
          AND b.event_sha256 = a.event_sha256
          AND b.id > a.id
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_events_address_sha
        ON wallet_activity_events_v2 (address, event_sha256)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_activity_events_address_sha")
