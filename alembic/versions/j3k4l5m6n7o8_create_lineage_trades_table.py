"""Create wallet_lineage_trades_v2, prune trades to 500, feed to 24h

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create wallet_lineage_trades_v2 — unified lineage table (transfers + P2P + deposits)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_lineage_trades_v2 (
            id             BIGSERIAL PRIMARY KEY,
            wallet_address VARCHAR(42) NOT NULL,
            event_type     VARCHAR(20) NOT NULL,
            counterparty   VARCHAR(42),
            asset          VARCHAR(78),
            amount         NUMERIC NOT NULL DEFAULT 0,
            amount_usd     NUMERIC NOT NULL DEFAULT 0,
            condition_id   VARCHAR(255),
            market_name    TEXT,
            outcome        TEXT,
            tx_hash        VARCHAR(66) NOT NULL,
            block_number   BIGINT NOT NULL,
            event_at       TIMESTAMPTZ NOT NULL,
            created_at     TIMESTAMPTZ DEFAULT now()
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lineage_v2_wallet_time
        ON wallet_lineage_trades_v2 (wallet_address, event_at DESC);
    """)

    # 2. Populate from wallet_position_transfers_v2 (P2P transfers)
    op.execute("""
        INSERT INTO wallet_lineage_trades_v2
            (wallet_address, event_type, counterparty, asset, amount, amount_usd,
             condition_id, market_name, outcome, tx_hash, block_number, event_at)
        SELECT
            from_address, 'TRANSFER_OUT', to_address, token_id, amount, 0,
            condition_id, market_name, outcome, tx_hash, block_number, transferred_at
        FROM wallet_position_transfers_v2;
    """)

    op.execute("""
        INSERT INTO wallet_lineage_trades_v2
            (wallet_address, event_type, counterparty, asset, amount, amount_usd,
             condition_id, market_name, outcome, tx_hash, block_number, event_at)
        SELECT
            to_address, 'TRANSFER_IN', from_address, token_id, amount, 0,
            condition_id, market_name, outcome, tx_hash, block_number, transferred_at
        FROM wallet_position_transfers_v2;
    """)

    # 3. Populate from wallet_internal_funding_v2 (deposits)
    op.execute("""
        INSERT INTO wallet_lineage_trades_v2
            (wallet_address, event_type, counterparty, asset, amount, amount_usd,
             tx_hash, block_number, event_at)
        SELECT
            funded_address, 'DEPOSIT', funder_address, asset, amount, amount_usd,
            tx_hash, block_number, funded_at
        FROM wallet_internal_funding_v2;
    """)

    op.execute("""
        INSERT INTO wallet_lineage_trades_v2
            (wallet_address, event_type, counterparty, asset, amount, amount_usd,
             tx_hash, block_number, event_at)
        SELECT
            funder_address, 'WITHDRAWAL', funded_address, asset, amount, amount_usd,
            tx_hash, block_number, funded_at
        FROM wallet_internal_funding_v2;
    """)

    # 4. Prune wallet_trades_v2 to max 500 per wallet (normal trades only)
    op.execute("""
        WITH ranked AS (
            SELECT ctid,
                   ROW_NUMBER() OVER (PARTITION BY wallet_address ORDER BY traded_at DESC) AS rn
            FROM wallet_trades_v2
        )
        DELETE FROM wallet_trades_v2 WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 500);
    """)

    # 5. Prune wallet_activity_v2 to 24 hours
    op.execute("""
        DELETE FROM wallet_activity_v2 WHERE event_at < NOW() - INTERVAL '1 day';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_lineage_trades_v2;")
