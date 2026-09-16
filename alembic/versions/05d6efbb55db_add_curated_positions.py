"""add curated_positions

Revision ID: 05d6efbb55db
Revises: b1a2g3e4n5t6
Create Date: 2026-07-20 23:27:45.488760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05d6efbb55db'
down_revision: Union[str, Sequence[str], None] = 'b1a2g3e4n5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "curated_positions",
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("condition_id", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False, server_default=""),
        sa.Column("total_bought", sa.Numeric, server_default="0"),
        sa.Column("total_sold", sa.Numeric, server_default="0"),
        sa.Column("net_tokens", sa.Numeric, server_default="0"),
        sa.Column("market_resolved", sa.Boolean, server_default=sa.text("false")),
        sa.Column("won", sa.Boolean, server_default=sa.text("false")),
        sa.Column("payout", sa.Numeric, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric, server_default="0"),
        sa.Column("is_resolved", sa.Boolean, server_default=sa.text("false")),
        sa.Column("is_win", sa.Boolean, server_default=sa.text("false")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("subcategory", sa.Text, nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("address", "condition_id", "outcome"),
    )
    op.create_index("ix_curated_positions_addr_resolved",
                    "curated_positions", ["address", "resolved_at"],
                    postgresql_using="btree")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_curated_positions_addr_resolved", table_name="curated_positions")
    op.drop_table("curated_positions")
