"""Preserve every asset emitted by one lineage transaction log.

Revision ID: u4v5w6x7y8
Revises: t3u4v5w6x7
Create Date: 2026-09-02
"""

from alembic import op


revision = "u4v5w6x7y8"
down_revision = "t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_lineage_trade_wallet_tx_log_v2")
    op.execute("""
        CREATE UNIQUE INDEX uq_lineage_trade_wallet_tx_log_v2
        ON wallet_lineage_trades_v2
        (wallet_address, tx_hash, log_index, event_type, COALESCE(asset, ''))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_lineage_trade_wallet_tx_log_v2")
    op.execute("""
        CREATE UNIQUE INDEX uq_lineage_trade_wallet_tx_log_v2
        ON wallet_lineage_trades_v2 (wallet_address, tx_hash, log_index)
    """)
