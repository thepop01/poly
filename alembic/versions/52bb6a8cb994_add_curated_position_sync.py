"""add curated_position_sync

Revision ID: 52bb6a8cb994
Revises: 805e4fd77203
Create Date: 2026-07-21 04:14:33.692205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52bb6a8cb994'
down_revision: Union[str, Sequence[str], None] = '805e4fd77203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-wallet incremental cursor for closed-positions fetching.

    last_closed_ts = the newest API `timestamp` seen in the last COMPLETE
    fetch. Advanced only after a full successful pass, so interrupted runs
    re-fetch the same gap and self-heal (upserts are idempotent).
    """
    op.create_table(
        "curated_position_sync",
        sa.Column("wallet_address", sa.Text, primary_key=True),
        sa.Column("last_closed_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("curated_position_sync")
