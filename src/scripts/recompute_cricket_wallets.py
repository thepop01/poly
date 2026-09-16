"""Resume wallet category-stats recompute for Cricket league backfill.

Recomputes category_stats_v2 (via Worker B) for every wallet holding a
Cricket market that now has a league. Progress is tracked in a scratch file
so interrupted runs resume where they left off. Idempotent: recomputing a
wallet twice is harmless.

Kept for history; new scopes should use recompute_scope_wallets.py.

Usage:
    python src/scripts/recompute_cricket_wallets.py [--concurrency 20]
"""

import argparse
import asyncio
import logging
import os
import sys
import time

import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.workers.compute_category_stats import compute_category_stats_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("recompute_cricket_wallets")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace(
    "localhost", "127.0.0.1")
PROGRESS_FILE = os.path.join("scratch", "cricket_recompute_progress.txt")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=40)
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=50,
                                     timeout=30, command_timeout=300)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT m.condition_id FROM markets_v2 m
                   WHERE m.category = 'SPORTS' AND m.subcategory = 'Cricket'
                     AND COALESCE(m.league, '') <> ''""")
        cids = [r["condition_id"] for r in rows]
        logger.info(f"{len(cids)} league-bearing Cricket markets.")

        done_cids: set[str] = set()
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE) as f:
                done_cids = {line.strip() for line in f if line.strip()}
        pending = [c for c in cids if c not in done_cids]
        logger.info(f"{len(pending)} markets pending recompute.")

        sem = asyncio.Semaphore(args.concurrency)
        recomputed = 0
        t0 = time.time()

        async def _recompute(addr: str):
            async with sem:
                async with pool.acquire() as conn:
                    try:
                        await compute_category_stats_for_wallet(conn, addr)
                    except Exception as e:
                        logger.warning(f"Recompute failed for {addr[:10]}: {e}")

        batch = 50
        for i in range(0, len(pending), batch):
            chunk = pending[i:i + batch]
            async with pool.acquire() as conn:
                addrs = await conn.fetch(
                    """SELECT DISTINCT address FROM (
                         SELECT address FROM wallet_closed_positions_v2 WHERE condition_id = ANY($1)
                         UNION
                         SELECT address FROM wallet_positions_v2 WHERE condition_id = ANY($1)
                       ) t""", chunk)
            await asyncio.gather(*[_recompute(r["address"]) for r in addrs])
            recomputed += len(addrs)
            with open(PROGRESS_FILE, "a") as f:
                f.write("\n".join(chunk) + "\n")
            dt = time.time() - t0
            logger.info(f"Markets {min(i + batch, len(pending))}/{len(pending)} | "
                        f"wallets {recomputed} ({recomputed / dt:.1f}/s).")
        logger.info(f"Done. {recomputed} wallets in {(time.time() - t0) / 60:.1f} min.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
