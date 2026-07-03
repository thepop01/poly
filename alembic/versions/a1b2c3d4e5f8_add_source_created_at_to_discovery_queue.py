"""add_source_created_at_to_discovery_queue

Revision ID: a1b2c3d4e5f8
Revises: a1b2c3d4e5f7
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_discovery_queue ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'Unknown';")
    op.execute("ALTER TABLE wallet_discovery_queue ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();")


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_discovery_queue DROP COLUMN IF EXISTS source;")
    op.execute("ALTER TABLE wallet_discovery_queue DROP COLUMN IF EXISTS created_at;")
