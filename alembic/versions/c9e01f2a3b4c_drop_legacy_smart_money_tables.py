"""drop_legacy_smart_money_tables

Revision ID: c9e01f2a3b4c
Revises: c8d84b631772
Create Date: 2026-08-09 02:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9e01f2a3b4c'
down_revision: Union[str, None] = 'c8d84b631772'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS smart_money_trades CASCADE")
    op.execute("DROP TABLE IF EXISTS smart_money_alerts CASCADE")


def downgrade() -> None:
    pass
