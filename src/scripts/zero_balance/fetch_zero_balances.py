"""
One-shot script: fetch balance + position for all wallets showing $0.
Processes in batches with rate-limit-aware concurrency.
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
    fetch_usdc_deposits,
    fetch_usdc_withdrawals,
)
from src.workers.wallet_trade_history import fetch_positions, _parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")
ALCHEMY_CONCURRENCY = 9  # 3 keys x 3
POLY_CONCURRENCY = 15
BATCH_DB_SIZE = 500       # wallets to upsert per DB commit


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    try:
        b = await alchemy_get_token_balances(session, address, [PUSD_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"balance fail {address[:10]}: {e}")
    return 0.0


async def fetch_one(
    sem_alchemy: asyncio.Semaphore,
    sem_poly: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    address: str,
) -> dict:
    """Fetch balance + positions for a single wallet."""
    async with sem_alchemy:
        balance = await fetch_balance(session, address)
        await asyncio.sleep(0.05)  # rate limit courtesy

    async with sem_poly:
        positions = await fetch_positions(session, address)

    position_value = 0.0
    for pos in (positions or []):
        cv = _parse(pos.get("currentValue"))
        if cv > 0:
            position_value += cv

    return {"address": address, "balance": balance, "position_value": position_value}


async def main():
    conn = await asyncpg.connect(DB_URL)

    # Get all wallets with zero balance OR zero position (non-DEAD, non-UNCLASSIFIED)
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
        logger.info("Nothing to do.")
        await conn.close()
        return

    sem_alchemy = asyncio.Semaphore(ALCHEMY_CONCURRENCY)
    sem_poly = asyncio.Semaphore(POLY_CONCURRENCY)

    refreshed = 0
    failed = 0
    start = time.time()

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # Process in sub-batches to allow DB commits
        for batch_start in range(0, total, BATCH_DB_SIZE):
            batch = addresses[batch_start:batch_start + BATCH_DB_SIZE]
            tasks = [
                fetch_one(sem_alchemy, sem_poly, session, addr)
                for addr in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # DB upsert
            upserts = []
            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                    continue
                upserts.append(r)

            if upserts:
                await conn.executemany("""
                    INSERT INTO wallet_metrics_v2 (address, balance, position_value, computed_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (address) DO UPDATE SET
                        balance = EXCLUDED.balance,
                        position_value = EXCLUDED.position_value,
                        computed_at = NOW()
                """, [(u["address"], u["balance"], u["position_value"]) for u in upserts])

                # Reclassify tiers based on fresh data
                for u in upserts:
                    total_val = u["balance"] + u["position_value"]
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

            refreshed += len(upserts)
            elapsed = time.time() - start
            rate = refreshed / elapsed if elapsed > 0 else 0
            logger.info(
                f"[{refreshed}/{total}] batch done | "
                f"fail={failed} | "
                f"{rate:.1f} wallets/sec | "
                f"elapsed={elapsed:.0f}s"
            )

    elapsed = time.time() - start
    logger.info(f"DONE: refreshed {refreshed}/{total} wallets in {elapsed:.0f}s ({failed} failed)")

    # Summary
    row = await conn.fetchrow("""
        SELECT
            COUNT(*) FILTER (WHERE COALESCE(balance, 0) > 0) as has_balance,
            COUNT(*) FILTER (WHERE COALESCE(position_value, 0) > 0) as has_position
        FROM wallet_metrics_v2
    """)
    logger.info(f"Final: {row['has_balance']} wallets with balance > 0, {row['has_position']} with position > 0")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
