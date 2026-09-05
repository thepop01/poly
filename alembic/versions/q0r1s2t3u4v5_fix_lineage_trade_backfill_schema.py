"""Make lineage trade storage compatible with the Polymarket trade backfiller.

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-09-01
"""

from alembic import op


revision = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS log_index INTEGER")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS side VARCHAR(16)")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS price NUMERIC")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS size NUMERIC")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS amount_usdc NUMERIC")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS traded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS category TEXT")
    op.execute("ALTER TABLE wallet_lineage_trades_v2 ADD COLUMN IF NOT EXISTS subcategory TEXT")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_lineage_trade_wallet_tx_log_v2
        ON wallet_lineage_trades_v2 (wallet_address, tx_hash, log_index)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_lineage_trade_wallet_tx_log_v2")
    for column in ("subcategory", "category", "traded_at", "amount_usdc", "size", "price", "side", "log_index"):
        op.execute(f"ALTER TABLE wallet_lineage_trades_v2 DROP COLUMN IF EXISTS {column}")
