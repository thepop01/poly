"""add_wallet_tracking_tables

Revision ID: 397e853462b3
Revises: 5dcace8f62d6
Create Date: 2026-06-22 00:40:42.538335

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '397e853462b3'
down_revision: Union[str, Sequence[str], None] = '5dcace8f62d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_watchlist (
            wallet_address VARCHAR(42) PRIMARY KEY REFERENCES wallet_stats(address),
            reason TEXT,
            added_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_wallet_watchlists (
            user_id UUID REFERENCES users(user_id),
            wallet_address VARCHAR(42) REFERENCES wallet_stats(address),
            notify_trade BOOLEAN DEFAULT true,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, wallet_address)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_wallet_watchlists;")
    op.execute("DROP TABLE IF EXISTS platform_watchlist;")
