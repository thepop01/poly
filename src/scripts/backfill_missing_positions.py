"""Re-fetch open positions for wallets whose position_value is missing.

Ordered by |pm_pnl| so the wallets that distort headline numbers most are
repaired first. Reuses the existing worker so there is one ingestion path.
"""
import argparse
import asyncio
import logging
import os

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.workers.positions_open_backfill import process_wallet_open

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))

SELECT_TARGETS = """
SELECT address FROM wallet_metrics_v2
WHERE pm_pnl IS NOT NULL
  AND abs(pm_pnl) >= $1
  AND (position_value IS NULL OR position_value = 0)
ORDER BY abs(pm_pnl) DESC
LIMIT $2
"""


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pnl", type=float, default=10_000.0)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    conn = await asyncpg.connect(DB_URL)
    targets = [r["address"]
               for r in await conn.fetch(SELECT_TARGETS, args.min_pnl, args.limit)]
    await conn.close()
    logger.info("wallets to backfill: %d", len(targets))

    pool = await asyncpg.create_pool(DB_URL, min_size=2,
                                     max_size=args.concurrency + 2)
    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=300, connect=30)
    done = 0

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def run_one(address):
            nonlocal done
            async with semaphore:
                try:
                    async with pool.acquire() as conn_inner:
                        await process_wallet_open(
                            conn_inner, session, address)
                except Exception as exc:
                    logger.warning("%s failed: %s", address[:12], exc)
                done += 1
                if done % 100 == 0:
                    logger.info("progress %d/%d", done, len(targets))

        await asyncio.gather(*(run_one(a) for a in targets))

    await pool.close()
    logger.info("backfill complete: %d wallets", done)


if __name__ == "__main__":
    asyncio.run(main())
