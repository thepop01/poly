"""merge heads for supabase winrate + realized_pnl

Revision ID: b0c1d2e3f4a5
Revises: a1b2c3d4e5f2, a3b4c5d6e7f8
Create Date: 2026-07-12
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f2', 'a3b4c5d6e7f8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
