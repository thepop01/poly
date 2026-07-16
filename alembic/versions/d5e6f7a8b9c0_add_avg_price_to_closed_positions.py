"""add avg_price to wallet_closed_positions

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_closed_positions ADD COLUMN IF NOT EXISTS avg_price NUMERIC(10,6) DEFAULT 0;")


def downgrade() -> None:
    op.execute("ALTER TABLE wallet_closed_positions DROP COLUMN IF EXISTS avg_price;")
