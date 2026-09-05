"""Drop per-fill exception evidence; aggregates are the permanent store.

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-09-06
"""

from alembic import op

revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_activity_exception_events_v2")


def downgrade() -> None:
    raise NotImplementedError(
        "Evidence rows cannot be restored without API refetch.")
