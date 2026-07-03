"""Expand side column to 255 — accumulated alerts exceed VARCHAR(10)

Revision ID: a1b2c3d4e5f2
Revises: a1b2c3d4e5f1
Create Date: 2026-06-30 17:15:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE smart_money_alerts ALTER COLUMN side TYPE VARCHAR(255);")
    op.execute("ALTER TABLE smart_money_trades ALTER COLUMN side TYPE VARCHAR(255);")


def downgrade() -> None:
    op.execute("ALTER TABLE smart_money_trades ALTER COLUMN side TYPE VARCHAR(10);")
    op.execute("ALTER TABLE smart_money_alerts ALTER COLUMN side TYPE VARCHAR(10);")
