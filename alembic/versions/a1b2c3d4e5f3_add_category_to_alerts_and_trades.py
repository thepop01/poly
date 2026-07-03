"""Add category column to smart_money_alerts and smart_money_trades

Revision ID: a1b2c3d4e5f3
Revises: a1b2c3d4e5f2
Create Date: 2026-06-30 21:50:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f3'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE smart_money_alerts ADD COLUMN IF NOT EXISTS category VARCHAR(100);")
    op.execute("ALTER TABLE smart_money_trades ADD COLUMN IF NOT EXISTS category VARCHAR(100);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_smart_money_alerts_category ON smart_money_alerts(category);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_smart_money_alerts_category;")
    op.execute("ALTER TABLE smart_money_trades DROP COLUMN IF EXISTS category;")
    op.execute("ALTER TABLE smart_money_alerts DROP COLUMN IF EXISTS category;")
