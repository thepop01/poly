# src/workers/positions_metrics_compute.py
"""
Master Metrics Computation Coordinator
========================================
Orchestrates the 3 decoupled modular computation workers:
1. Worker A: compute_core_metrics.py (Win rate, price buckets, parlay, volume, ROI)
2. Worker B: compute_category_stats.py (Unscaled position-row category metrics)
3. Worker C: compute_historical_windows.py (Historical 10-window progression pnl_100..pnl_5000)
"""

import asyncio
import argparse
import logging
import os
import sys
import time
from typing import Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

import aiohttp
import asyncpg

from src.workers.compute_core_metrics import compute_core_metrics_for_wallet
from src.workers.compute_category_stats import compute_category_stats_for_wallet
from src.workers.compute_historical_windows import compute_historical_windows_for_wallet

logger = logging.getLogger("positions_metrics_compute")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 150

async def compute_metrics_for_wallet(
    conn: asyncpg.Connection,
    session: Optional[aiohttp.ClientSession],
    address: str,
):
    """Executes all 3 modular computation passes for a wallet."""
    # 1. Worker A: Core Metrics (win rate, price buckets, parlay, volume)
    await compute_core_metrics_for_wallet(conn, address)
    # 2. Worker B: Category & League Returns (unscaled position ledger)
    await compute_category_stats_for_wallet(conn, address)
    # 3. Worker C: Historical 10-Window Progression (pnl_100..pnl_5000)
    await compute_historical_windows_for_wallet(conn, address)

async def main():
    parser = argparse.ArgumentParser(description="Master Metrics Computation Coordinator")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY, help="Number of concurrent workers")
    parser.add_argument("--wallet", type=str, default=None, help="Specific wallet address to compute")
    parser.add_argument("--limit", type=int, default=None, help="Max wallets to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pool = await asyncpg.create_pool(DB_URL, min_size=20, max_size=args.concurrency + 30)

    if args.wallet:
        async with pool.acquire() as conn:
            await compute_metrics_for_wallet(conn, None, args.wallet.lower())
            logger.info(f"Successfully computed all 3 sections for {args.wallet}!")
        await pool.close()
        return

    logger.info(f"Fetching active wallets for Master Metrics Compute (Concurrency: {args.concurrency})...")
    async with pool.acquire() as conn:
        limit_clause = f"LIMIT {args.limit}" if args.limit else ""
        rows = await conn.fetch(f"""
            SELECT w.address
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
            WHERE NOT w.is_dormant
              AND (
                    EXISTS (
                        SELECT 1
                        FROM wallet_closed_positions_v2 c
                        WHERE c.address = w.address
                          AND COALESCE(c.metrics_eligible, TRUE)
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM wallet_positions_v2 p
                        WHERE p.address = w.address
                    )
              )
              AND (
                    m.computed_at IS NULL
                    OR m.closed_synced_at IS NULL
                    OR m.open_synced_at IS NULL
                    OR m.closed_synced_at > m.computed_at
                    OR m.open_synced_at > m.computed_at
              )
            ORDER BY COALESCE(m.closed_synced_at, m.open_synced_at, '1970-01-01'::timestamptz) DESC,
                     w.address
            {limit_clause};
        """)
        wallets = [r["address"] for r in rows]

    total = len(wallets)
    logger.info(f"Found {total:,} active wallets to process.")

    sem = asyncio.Semaphore(args.concurrency)
    processed = 0
    start_t = time.time()

    async def _worker(addr: str):
        nonlocal processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_metrics_for_wallet(conn, None, addr)
                except Exception as e:
                    logger.error(f"Error computing metrics for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 1000 == 0 or processed == total:
                        elapsed = time.time() - start_t
                        speed = processed / elapsed if elapsed > 0 else 0
                        logger.info(f"Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/s")

    await asyncio.gather(*[_worker(addr) for addr in wallets])
    logger.info(f"All 3 computation stages finished in {(time.time() - start_t)/60:.2f} minutes!")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
