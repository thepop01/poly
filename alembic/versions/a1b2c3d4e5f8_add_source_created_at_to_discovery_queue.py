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


# wallet_discovery_queue is created later in history (f1a2b3c4d5e6) and dropped
# by the v2 schema; guard so a from-zero replay doesn't fail on the missing table.
def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('wallet_discovery_queue') IS NOT NULL THEN
                ALTER TABLE wallet_discovery_queue ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'Unknown';
                ALTER TABLE wallet_discovery_queue ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('wallet_discovery_queue') IS NOT NULL THEN
                ALTER TABLE wallet_discovery_queue DROP COLUMN IF EXISTS source;
                ALTER TABLE wallet_discovery_queue DROP COLUMN IF EXISTS created_at;
            END IF;
        END $$;
    """)
