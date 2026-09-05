"""
Turbo Recompute Metrics for CURATED and STANDARD Wallets.
Runs with 150 parallel async workers for maximum throughput.
"""
import asyncio
import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()
import aiohttp
import asyncpg

from src.workers.positions_metrics_compute import compute_metrics_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recompute_curated_standard")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 250
CUTOFF = "2026-08-29 15:55:00+05:30"

async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=20, max_size=CONCURRENCY + 20)
    logger.info("Connected to database pool. Fetching CURATED, STANDARD, and PREVIOUSLY_CURATED uncomputed wallets...")
    
    start_time = time.time()
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.address, w.tier
            FROM wallet_metrics_v2 m
            JOIN wallets_v2 w ON m.address = w.address
            WHERE w.tier IN ('CURATED', 'STANDARD', 'PREVIOUSLY_CURATED', 'NEW')
              AND m.resolved_count > 0 
              AND (m.computed_at IS NULL OR m.computed_at < $1)
            ORDER BY 
                CASE w.tier 
                    WHEN 'CURATED' THEN 1 
                    WHEN 'STANDARD' THEN 2 
                    WHEN 'PREVIOUSLY_CURATED' THEN 3 
                    ELSE 4 
                END ASC
        """, datetime.fromisoformat(CUTOFF))
        wallets = [r["address"] for r in rows]
        
    total = len(wallets)
    logger.info(f"Targeting {total:,} prioritized wallets (CURATED + STANDARD + PREV_CURATED + NEW).")
    logger.info(f"Launching Turbo Mode with {CONCURRENCY} parallel workers...")
    
    if total == 0:
        logger.info("All target wallets are already computed! Exiting.")
        await pool.close()
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0
    errors = 0
    last_log_time = time.time()
    last_log_processed = 0
    
    async def _worker(session: aiohttp.ClientSession, addr: str):
        nonlocal processed, errors, last_log_time, last_log_processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_metrics_for_wallet(conn, session, addr)
                except Exception as e:
                    errors += 1
                    logger.error(f"Error computing metrics for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 100 == 0 or processed == total:
                        now = time.time()
                        interval = now - last_log_time
                        cnt_interval = processed - last_log_processed
                        speed = cnt_interval / interval if interval > 0 else 0
                        eta_sec = ((total - processed) / speed) if speed > 0 else 0
                        logger.info(f"Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/sec | ETA: {eta_sec:.1f}s | Errors: {errors}")
                        last_log_time = now
                        last_log_processed = processed

    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [_worker(session, addr) for addr in wallets]
        await asyncio.gather(*tasks)
        
    elapsed = time.time() - start_time
    logger.info(f"\n=======================================================")
    logger.info(f"SUCCESS: Completed {total:,} priority wallets in {elapsed:.1f}s ({total/elapsed:.1f} wallets/sec)!")
    logger.info(f"=======================================================")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
