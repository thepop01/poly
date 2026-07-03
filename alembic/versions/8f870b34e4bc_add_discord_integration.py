"""add_discord_integration

Revision ID: 8f870b34e4bc
Revises: 00860174323b
Create Date: 2026-06-24 20:21:53.758518

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f870b34e4bc'
down_revision: Union[str, Sequence[str], None] = '00860174323b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discord_id VARCHAR(255) UNIQUE;")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS discord_id;")
    # Cannot safely add NOT NULL back to password_hash without setting a default,
    # so we leave it nullable on downgrade, or assume no Discord-only users remain.
    # op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;")
