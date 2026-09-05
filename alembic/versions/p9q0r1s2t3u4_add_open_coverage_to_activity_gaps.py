"""Record whether an Activity-only market is represented by an open position.

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-09-01
"""

from alembic import op


revision = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wallet_activity_only_markets_v2
        ADD COLUMN IF NOT EXISTS has_open_position BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_activity_only_markets_v2 DROP COLUMN IF EXISTS has_open_position")
