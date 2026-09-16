"""add avg_sell_price to wallet_closed_positions and wallet_position_outcomes

Revision ID: e5f6a7b8c9d0
Revises: d5e6f7a8b9c0
Create Date: 2026-07-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


# wallet_position_outcomes is created outside alembic (ad-hoc on dev); guard so
# a from-zero replay doesn't fail on the missing table.
def upgrade() -> None:
    op.execute("ALTER TABLE wallet_closed_positions ADD COLUMN IF NOT EXISTS avg_sell_price NUMERIC(10,6) DEFAULT 0;")
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('wallet_position_outcomes') IS NOT NULL THEN
                ALTER TABLE wallet_position_outcomes ADD COLUMN IF NOT EXISTS avg_sell_price NUMERIC;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('wallet_position_outcomes') IS NOT NULL THEN
                ALTER TABLE wallet_position_outcomes DROP COLUMN IF EXISTS avg_sell_price;
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE wallet_closed_positions DROP COLUMN IF EXISTS avg_sell_price;")
