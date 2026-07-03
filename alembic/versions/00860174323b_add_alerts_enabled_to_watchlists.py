"""add_alerts_enabled_to_watchlists

Revision ID: 00860174323b
Revises: 4291a0403dcd
Create Date: 2026-06-22 20:05:11.091347

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00860174323b'
down_revision: Union[str, Sequence[str], None] = '4291a0403dcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_watchlists ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN DEFAULT false;")

def downgrade() -> None:
    op.execute("ALTER TABLE user_watchlists DROP COLUMN IF EXISTS alerts_enabled;")
