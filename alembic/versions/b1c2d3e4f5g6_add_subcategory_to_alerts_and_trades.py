"""Add subcategory column to smart_money_alerts and smart_money_trades

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f3
Create Date: 2026-07-01 23:30:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE smart_money_alerts ADD COLUMN IF NOT EXISTS subcategory VARCHAR(100);")
    op.execute("ALTER TABLE smart_money_trades ADD COLUMN IF NOT EXISTS subcategory VARCHAR(100);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_smart_money_alerts_subcategory ON smart_money_alerts(subcategory);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_smart_money_alerts_subcategory;")
    op.execute("ALTER TABLE smart_money_trades DROP COLUMN IF EXISTS subcategory;")
    op.execute("ALTER TABLE smart_money_alerts DROP COLUMN IF EXISTS subcategory;")
