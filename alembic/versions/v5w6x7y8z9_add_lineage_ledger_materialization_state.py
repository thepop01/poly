"""Track resumable materialization of canonical P2P transfers.

Revision ID: v5w6x7y8z9
Revises: u4v5w6x7y8
Create Date: 2026-09-02
"""

from alembic import op


revision = "v5w6x7y8z9"
down_revision = "u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS lineage_ledger_materialization_state_v2 (
            source_name TEXT PRIMARY KEY,
            last_source_id BIGINT NOT NULL DEFAULT 0,
            complete BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lineage_ledger_materialization_state_v2")
