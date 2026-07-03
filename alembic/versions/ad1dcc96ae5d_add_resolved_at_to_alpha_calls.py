"""add_resolved_at_to_alpha_calls

Revision ID: ad1dcc96ae5d
Revises: 8f870b34e4bc
Create Date: 2026-06-25 13:30:08.806748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad1dcc96ae5d'
down_revision: Union[str, Sequence[str], None] = '8f870b34e4bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE alpha_calls ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE alpha_calls DROP COLUMN IF EXISTS resolved_at;")
