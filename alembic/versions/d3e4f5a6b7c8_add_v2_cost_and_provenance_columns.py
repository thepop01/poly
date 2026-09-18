"""Add v2 cost columns, residual columns, position_quarantine, and sweep_watermarks tables.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-18

This migration adds:
- event_id to markets_v2 with index
- Cost and provenance columns to wallet_positions_v2 (event_id, entry_cost_usdc, total_cost_usdc,
  entry_fees_usdc, source_total_pnl, outcome_index, mergeable, cost_basis_confidence) with index
- Cost and provenance columns to wallet_closed_positions_v2 (same minus outcome_index and mergeable)
- Residual and position_pnl analysis columns to wallet_metrics_v2
- New position_quarantine table for tracking failed position imports with address index
- New wallet_v2_sweep_watermarks table for tracking sweep progress per wallet

All columns are nullable and additive only. Migration supports downgrade.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: str = "c2d3e4f5a6b7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add event_id to markets_v2
    op.add_column("markets_v2", sa.Column("event_id", sa.Text(), nullable=True))
    op.create_index("ix_markets_v2_event_id", "markets_v2", ["event_id"])

    # Add cost and provenance columns to wallet_positions_v2
    for col, typ in [
        ("event_id", sa.Text()),
        ("entry_cost_usdc", sa.Numeric()),
        ("total_cost_usdc", sa.Numeric()),
        ("entry_fees_usdc", sa.Numeric()),
        ("source_total_pnl", sa.Numeric()),
        ("outcome_index", sa.SmallInteger()),
        ("mergeable", sa.Boolean()),
        ("cost_basis_confidence", sa.Text()),
    ]:
        op.add_column("wallet_positions_v2", sa.Column(col, typ, nullable=True))
    op.create_index("ix_wp_v2_event_id", "wallet_positions_v2", ["event_id"])

    # Add cost and provenance columns to wallet_closed_positions_v2
    for col, typ in [
        ("event_id", sa.Text()),
        ("entry_cost_usdc", sa.Numeric()),
        ("total_cost_usdc", sa.Numeric()),
        ("entry_fees_usdc", sa.Numeric()),
        ("source_total_pnl", sa.Numeric()),
        ("cost_basis_confidence", sa.Text()),
    ]:
        op.add_column("wallet_closed_positions_v2", sa.Column(col, typ, nullable=True))

    # Add residual and position_pnl analysis columns to wallet_metrics_v2
    for col in [
        "residual",
        "residual_explained_rewards",
        "residual_explained_rebates",
        "residual_explained_yield",
        "unexplained_residual",
        "position_pnl",
    ]:
        op.add_column("wallet_metrics_v2", sa.Column(col, sa.Numeric(), nullable=True))

    # Create position_quarantine table
    op.create_table(
        "position_quarantine",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("condition_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("raw_row", sa.JSON()),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pq_address", "position_quarantine", ["address"])

    # Create wallet_v2_sweep_watermarks table
    op.create_table(
        "wallet_v2_sweep_watermarks",
        sa.Column("address", sa.Text(), primary_key=True),
        sa.Column("last_swept_at", sa.DateTime(timezone=True)),
        sa.Column("rows_ok", sa.Integer(), server_default="0"),
        sa.Column("rows_quarantined", sa.Integer(), server_default="0"),
    )


def downgrade() -> None:
    # Drop wallet_v2_sweep_watermarks table
    op.drop_table("wallet_v2_sweep_watermarks")

    # Drop position_quarantine table
    op.drop_index("ix_pq_address", table_name="position_quarantine")
    op.drop_table("position_quarantine")

    # Remove residual and position_pnl columns from wallet_metrics_v2
    for col in [
        "residual",
        "residual_explained_rewards",
        "residual_explained_rebates",
        "residual_explained_yield",
        "unexplained_residual",
        "position_pnl",
    ]:
        op.drop_column("wallet_metrics_v2", col)

    # Remove cost and provenance columns from wallet_closed_positions_v2
    for col in [
        "cost_basis_confidence",
        "source_total_pnl",
        "entry_fees_usdc",
        "total_cost_usdc",
        "entry_cost_usdc",
        "event_id",
    ]:
        op.drop_column("wallet_closed_positions_v2", col)

    # Remove cost and provenance columns from wallet_positions_v2
    op.drop_index("ix_wp_v2_event_id", table_name="wallet_positions_v2")
    for col in [
        "cost_basis_confidence",
        "mergeable",
        "outcome_index",
        "source_total_pnl",
        "entry_fees_usdc",
        "total_cost_usdc",
        "entry_cost_usdc",
        "event_id",
    ]:
        op.drop_column("wallet_positions_v2", col)

    # Remove event_id from markets_v2
    op.drop_index("ix_markets_v2_event_id", table_name="markets_v2")
    op.drop_column("markets_v2", "event_id")
