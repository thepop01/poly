"""drop tier column from wallet_stats

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("ALTER TABLE wallet_stats DROP COLUMN IF EXISTS tier;")

def downgrade() -> None:
    op.execute("ALTER TABLE wallet_stats ADD COLUMN tier VARCHAR(32) DEFAULT 'Silver';")
