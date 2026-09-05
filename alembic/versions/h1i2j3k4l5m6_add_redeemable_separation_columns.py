"""Add redeemable separation columns

Revision ID: h1i2j3k4l5m6
Revises: g7h8i9j0k1l2
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "h1i2j3k4l5m6"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wallet_closed_positions_v2",
        sa.Column("is_redeemable", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
    )
    op.add_column(
        "wallet_closed_positions_v2",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "wallet_positions_v2",
        sa.Column("is_resolved", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
    )
    op.add_column(
        "wallet_metrics_v2",
        sa.Column("redeemable_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "wallet_metrics_v2",
        sa.Column("redeemable_winning_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("wallet_metrics_v2", "redeemable_winning_count")
    op.drop_column("wallet_metrics_v2", "redeemable_count")
    op.drop_column("wallet_positions_v2", "is_resolved")
    op.drop_column("wallet_closed_positions_v2", "resolved_at")
    op.drop_column("wallet_closed_positions_v2", "is_redeemable")
