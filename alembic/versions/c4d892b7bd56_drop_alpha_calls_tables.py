"""drop alpha calls tables

Revision ID: c4d892b7bd56
Revises: d8c0223a903d
Create Date: 2026-06-30 00:07:05.931093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d892b7bd56'
down_revision: Union[str, Sequence[str], None] = 'd8c0223a903d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trigger_update_call_history ON alpha_calls;")
    op.execute("DROP FUNCTION IF EXISTS update_user_call_history();")
    op.execute("DROP TABLE IF EXISTS user_call_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS alpha_calls CASCADE;")
    op.execute("ALTER TABLE wallet_txn_windows ADD COLUMN IF NOT EXISTS position_value NUMERIC(18,2) DEFAULT 0;")

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE wallet_txn_windows DROP COLUMN IF EXISTS position_value;")
