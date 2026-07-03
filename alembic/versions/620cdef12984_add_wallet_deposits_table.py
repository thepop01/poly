"""add_wallet_deposits_table

Revision ID: 620cdef12984
Revises: f1a2b3c4d5e6
Create Date: 2026-06-28 11:21:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '620cdef12984'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_deposits (
            id BIGSERIAL PRIMARY KEY,
            wallet_address VARCHAR(42) NOT NULL,
            tx_hash VARCHAR(66) UNIQUE NOT NULL,
            amount_usdc NUMERIC NOT NULL,
            deposited_at TIMESTAMPTZ NOT NULL,
            flagged_single BOOLEAN DEFAULT FALSE,
            flagged_cumulative BOOLEAN DEFAULT FALSE,
            alerted BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallet_deposits_address_time ON wallet_deposits(wallet_address, deposited_at);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_deposits;")
