"""add wallet_tags table

Revision ID: a1b2c3d4e5fa
Revises: d2e3f4a5b6c7
Create Date: 2026-07-03 14:00:00

Stores category tags for wallets based on the markets they trade in.
Computed from trade event slugs using the category_classifier.

NOTE: This revision was originally authored as 'a1b2c3d4e5f9', which collided
with the earlier 'a1b2c3d4e5f9_add_user_id_to_watchlists' revision. It has been
renamed to 'a1b2c3d4e5fa' to make `alembic upgrade head` resolvable on a fresh DB.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5fa'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tags (
            address        VARCHAR(42) PRIMARY KEY REFERENCES tracked_wallets(address) ON DELETE CASCADE,
            category       VARCHAR(50) NOT NULL DEFAULT 'Other',
            subcategory    VARCHAR(100) NOT NULL DEFAULT 'General',
            trade_count    INTEGER NOT NULL DEFAULT 0,
            top_markets    TEXT[] DEFAULT '{}',
            computed_at    TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_tags_category ON wallet_tags(category);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_tags;")
