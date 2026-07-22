#!/usr/bin/env python3
"""
Robust batch refresh script for wallets with zero balance or position.
Improved error handling and progress tracking.
"""
import asyncio
import asyncpg
import aiohttp
import os
import sys
import logging
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.utils.alchemy_client import (
    alchemy_get_token_balances,
    PUSD_CONTRACT,
)
from src.workers.wallet_trade_history import fetch_positions, _parse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    logger.error("DATABASE_URL not set in environment")
    sys.exit(1)

ALCHEMY_CONCURRENCY = 9
POLY_CONCURRENCY = 15
BATCH_DB_SIZE = 100  # Smaller batches for better feedback


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch USDC balance from Alchemy."""
    try:
        b = await alchemy_get_token_balances(session, address, [PUSD_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.debug(f"balance fetch failed for {address[:10]}: {type(e).__name__}: {e}")
    return 0.0


async def fetch_one(
    sem_alchemy: asyncio.Semaphore,
    sem_poly: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    address: str,
) -> dict:
    """Fetch balance + positions for a single wallet."""
    try:
        async with sem_alchemy:
            balance = await fetch_balance(session, address)
            await asyncio.sleep(0.05)  # Rate limit

        async with sem_poly:
            positions = await fetch_positions(session, address)

        position_value = 0.0
        for pos in (positions or []):
            cv = _parse(pos.get("currentValue"))
            if cv > 0:
                position_value += cv

        return {
            "address": address,
            "balance": balance,
            "position_value": position_value,
            "success": True
        }
    except Exception as e:
        logger.warning(f"fetch_one failed for {address[:10]}: {e}")
        return {
            "address": address,
            "balance": 0.0,
            "position_value": 0.0,
            "success": False,
            "error": str(e)
        }


async def main():
    conn = await asyncpg.connect(DB_URL)
    logger.info("Database connected")

    # Get all wallets with zero balance OR zero position
    rows = await conn.fetch("""
        SELECT w.address
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE w.tier NOT IN ('DEAD', 'UNCLASSIFIED')
          AND (COALESCE(m.balance, 0) = 0 OR COALESCE(m.position_value, 0) = 0)
        ORDER BY m.computed_at ASC NULLS FIRST
    """)

    addresses = [r["address"] for r in rows]
    total = len(addresses)
    logger.info(f"Found {total} wallets to refresh (zero balance or position)")

    if total == 0:
        logger.info("Nothing to do")
        await conn.close()
        return

    sem_alchemy = asyncio.Semaphore(ALCHEMY_CONCURRENCY)
    sem_poly = asyncio.Semaphore(POLY_CONCURRENCY)

    refreshed = 0
    failed = 0
    start_time = time.time()

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # Process in batches
        for batch_start in range(0, total, BATCH_DB_SIZE):
            batch_end = min(batch_start + BATCH_DB_SIZE, total)
            batch = addresses[batch_start:batch_end]
            batch_num = (batch_start // BATCH_DB_SIZE) + 1

            logger.info(f"[BATCH {batch_num}] Processing {len(batch)} wallets ({batch_start}-{batch_end}/{total})")

            # Fetch all in this batch concurrently
            tasks = [
                fetch_one(sem_alchemy, sem_poly, session, addr)
                for addr in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=False)

            # Separate successes and failures
            upserts = []
            for result in results:
                if result.get("success"):
                    upserts.append(result)
                    refreshed += 1
                else:
                    failed += 1
                    logger.debug(f"  Failed: {result['address'][:10]}")

            if upserts:
                try:
                    await conn.executemany("""
                        INSERT INTO wallet_metrics_v2 (address, balance, position_value, computed_at)
                        VALUES ($1, $2, $3, NOW())
                        ON CONFLICT (address) DO UPDATE SET
                            balance = EXCLUDED.balance,
                            position_value = EXCLUDED.position_value,
                            computed_at = NOW()
                    """, [(u["address"], u["balance"], u["position_value"]) for u in upserts])
                    logger.debug(f"  DB upsert: {len(upserts)} wallets")
                except Exception as e:
                    logger.error(f"DB upsert failed: {e}")
                    failed += len(upserts)
                    continue

                # Reclassify tiers
                for u in upserts:
                    total_val = u["balance"] + u["position_value"]
                    try:
                        await conn.execute("""
                            UPDATE wallets_v2
                            SET tier = CASE
                                    WHEN $2 <= 0 THEN
                                        CASE WHEN last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                                    WHEN $2 < 1000 THEN 'LOW_BALANCE'
                                    WHEN last_trade_at IS NULL THEN 'NEW'
                                    ELSE 'STANDARD'
                                END,
                                tier_reason = 'balance_refresh',
                                updated_at = NOW()
                            WHERE address = $1
                              AND tier NOT IN ('CURATED', 'UNCLASSIFIED')
                        """, u["address"], total_val)
                    except Exception as e:
                        logger.debug(f"Tier update failed for {u['address'][:10]}: {e}")

            elapsed = time.time() - start_time
            rate = refreshed / elapsed if elapsed > 0 else 0
            eta_remaining = (total - refreshed) / rate if rate > 0 else 0

            logger.info(
                f"[BATCH {batch_num}] {refreshed}/{total} done | "
                f"fail={failed} | "
                f"{rate:.1f} w/s | "
                f"elapsed={elapsed:.0f}s | "
                f"ETA={eta_remaining:.0f}s"
            )

            await asyncio.sleep(1)  # Small pause between batches

    elapsed = time.time() - start_time
    logger.info(f"DONE: refreshed {refreshed}/{total} wallets in {elapsed:.0f}s ({failed} failed)")

    # Summary stats
    try:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE COALESCE(balance, 0) > 0) as has_balance,
                COUNT(*) FILTER (WHERE COALESCE(position_value, 0) > 0) as has_position,
                COUNT(*) as total_tracked
            FROM wallet_metrics_v2
        """)
        logger.info(f"DB Summary: {row['has_balance']} wallets with balance > 0, "
                   f"{row['has_position']} with position > 0, "
                   f"{row['total_tracked']} total tracked")
    except Exception as e:
        logger.warning(f"Could not fetch summary: {e}")

    await conn.close()
    logger.info("Database connection closed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
