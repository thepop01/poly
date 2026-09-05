"""
Turbo Recompute Metrics across Remaining Wallets (Option B).
Executes compute_metrics_for_wallet in parallel with 140 async workers.
"""
import asyncio
import os
import sys
import time
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()
import aiohttp
import asyncpg

from src.workers.positions_metrics_compute import compute_metrics_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recompute_metrics_turbo")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 150

async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=20, max_size=180)
    logger.info("Connected to database pool. Fetching remaining uncomputed wallets...")
    
    start_time = time.time()
    
    # Select active wallets prioritized by volume
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT address FROM wallet_metrics_v2 
            WHERE (resolved_count > 0 OR position_value > 0)
              AND (computed_at IS NULL OR computed_at < NOW() - INTERVAL '2 hours')
            ORDER BY COALESCE(pm_volume, total_volume, 0) DESC
        """)
        wallets = [r["address"] for r in rows]
        
    total = len(wallets)
    logger.info(f"Found {total:,} remaining uncomputed wallets. Launching Turbo Mode with {CONCURRENCY} workers...")
    
    if total == 0:
        logger.info("All wallets already computed! Exiting.")
        await pool.close()
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0
    last_log_time = time.time()
    last_log_processed = 0
    
    async def _worker(session: aiohttp.ClientSession, addr: str):
        nonlocal processed, last_log_time, last_log_processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_metrics_for_wallet(conn, session, addr)
                except Exception as e:
                    logger.error(f"Error computing metrics for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 2000 == 0 or processed == total:
                        now = time.time()
                        interval = now - last_log_time
                        cnt_interval = processed - last_log_processed
                        speed = cnt_interval / interval if interval > 0 else 0
                        eta_min = ((total - processed) / speed / 60.0) if speed > 0 else 0
                        logger.info(f"Turbo Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/sec ({speed*60:,.0f}/min) | ETA: {eta_min:.1f} mins")
                        last_log_time = now
                        last_log_processed = processed

    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [_worker(session, addr) for addr in wallets]
        await asyncio.gather(*tasks)
        
    elapsed = time.time() - start_time
    logger.info(f"\nTurbo Recomputation of {total:,} wallets completed in {elapsed/60.0:.2f} minutes ({total/elapsed:.1f} wallets/sec)!")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
