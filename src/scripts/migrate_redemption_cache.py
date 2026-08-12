"""
Migration: Create wallet_redemptions_cache and redemption_sync tables.

wallet_redemptions_cache — stores already-fetched on-chain redemption logs per wallet.
redemption_sync          — stores the last fetched blockNumber per (wallet, contract) pair,
                           so future fetches only pull new blocks (incremental).
"""
import asyncio
import asyncpg
import os

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def main():
    conn = await asyncpg.connect(DB_URL)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_redemptions_cache (
            address         VARCHAR NOT NULL,
            contract        VARCHAR NOT NULL,
            condition_id    VARCHAR NOT NULL,
            payout          DOUBLE PRECISION,
            timestamp       BIGINT,
            tx_hash         VARCHAR,
            block_number    BIGINT,
            fetched_at      TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, contract, tx_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_redemptions_cache_address
            ON wallet_redemptions_cache (address);
    """)
    print("Created wallet_redemptions_cache")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS redemption_sync (
            address         VARCHAR NOT NULL,
            contract        VARCHAR NOT NULL,
            last_block      BIGINT NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, contract)
        );
    """)
    print("Created redemption_sync")

    await conn.close()
    print("Done.")

asyncio.run(main())
