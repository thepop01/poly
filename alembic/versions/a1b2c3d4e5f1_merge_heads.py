"""merge leaderboard baseline snapshots and drop alpha calls

Revision ID: a1b2c3d4e5f1
Revises: a1b2c3d4e5f0, c4d892b7bd56
Create Date: 2026-06-30 12:30:00

Merge the two head revisions.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f1'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f0', 'c4d892b7bd56')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
