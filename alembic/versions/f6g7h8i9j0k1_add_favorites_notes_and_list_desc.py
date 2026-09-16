"""add favorites notes and list description

Revision ID: f6g7h8i9j0k1
Revises: e6f7a8b9c0d1
Create Date: 2026-08-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("ALTER TABLE user_watchlists ADD COLUMN IF NOT EXISTS display_name VARCHAR;")
    op.execute("ALTER TABLE user_watchlists ADD COLUMN IF NOT EXISTS notes TEXT;")
    op.execute("ALTER TABLE tracker_lists ADD COLUMN IF NOT EXISTS description TEXT;")

def downgrade() -> None:
    op.execute("ALTER TABLE user_watchlists DROP COLUMN IF EXISTS display_name;")
    op.execute("ALTER TABLE user_watchlists DROP COLUMN IF EXISTS notes;")
    op.execute("ALTER TABLE tracker_lists DROP COLUMN IF EXISTS description;")
