"""add events table

Revision ID: 47d850caf3df
Revises: 19c895f4fbbb
Create Date: 2026-06-21 13:40:29.713537

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47d850caf3df'
down_revision: Union[str, Sequence[str], None] = '19c895f4fbbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        slug TEXT,
        title TEXT,
        category TEXT,
        tags JSONB,
        topic_cluster TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        resolved_at TIMESTAMP WITH TIME ZONE
    );
    """)

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF NOT EXISTS events;")
