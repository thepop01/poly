# src/workers/onchain_verifier.py
"""
Worker 3: On-Chain Polygonscan Verifier
=======================================
Cross-checks wallets that returned $0 volume / 0 positions from Polymarket REST API
against Polygonscan to verify if they have any hidden on-chain trades/redemptions.

Runs gently at 1 request/sec to observe Polygonscan API limits.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging

from src.utils.etherscan_client import fetch_historical_trades_polygonscan

logger = logging.getLogger("onchain_verifier")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
SLEEP_INTERVAL_SEC = 1.0


async def verify_wallet_onchain(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    logger.info(f"Checking Polygonscan on-chain history for {address[:12]}...")
    try:
        trades = await fetch_historical_trades_polygonscan(session, [address])
        tx_count = len(trades) if isinstance(trades, list) else 0

        if tx_count > 0:
            logger.info(f"On-chain trades found for {address[:12]}... ({tx_count} trades) — verified active")
        else:
            logger.info(f"Zero on-chain transactions confirmed for {address[:12]}...")

        await conn.execute("""
            UPDATE wallets_v2
            SET onchain_verify_pending = FALSE,
                onchain_verified_at = NOW()
            WHERE address = $1
        """, address)

        await conn.execute("""
            UPDATE wallet_metrics_v2
            SET onchain_verify_pending = FALSE,
                onchain_verified_at = NOW()
            WHERE address = $1
        """, address)

    except Exception as e:
        logger.warning(f"Error verifying {address[:12]}... on Polygonscan: {e}")


async def run_onchain_verifier(db_url: str = DB_URL):
    logger.info("=== WORKER 3: ON-CHAIN POLYGONSCAN VERIFIER STARTED ===")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)
    except Exception as e:
        logger.error(f"DB pool failed: {e}")
        return

    async with aiohttp.ClientSession() as session:
        try:
            while True:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT address
                        FROM wallets_v2
                        WHERE onchain_verify_pending = TRUE
                        ORDER BY last_trade_at DESC NULLS LAST
                        LIMIT 20
                    """)

                    if not rows:
                        await asyncio.sleep(10)
                        continue

                    for r in rows:
                        addr = r["address"]
                        await verify_wallet_onchain(conn, session, addr)
                        await asyncio.sleep(SLEEP_INTERVAL_SEC)

        except asyncio.CancelledError:
            logger.info("Worker 3 stopped.")
        finally:
            await pool.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(run_onchain_verifier())
