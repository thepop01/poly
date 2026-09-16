"""
Recompute Metrics across All Wallets (Option B).
Executes compute_metrics_for_wallet across all wallets in the database
to roll up clean position PnL into wallet_metrics_v2 and category_stats_v2.
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
logger = logging.getLogger("recompute_all_wallets")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 60

TARGET_WHALES = [
    "0xf0318c32136c2db7fec88b84869aee6a1106c80c", # BreakTheBank
    "0xb687f004b50d53c30664e320f7976e1074e4fe97", # alwayslatetotheparty
    "0xfe787d2d38562d515a8128527a29e9ae156b6851", # ferrariChampions2026
    "0x63d43bbb53a992a7e78ee291dfdfad988e05cb6b", # wokerjoesleeper
    "0x43372356ec39d52cffcf33d289fb0c8411d3efaa", # Anjun
    "0x9d84ce0368146cc2620fa9ebc37895f87b8f9e61", # ImJustKen
    "0x7ea571c4c161d7eb6b5c39ee3a7cf6196238b693", # Cannae
    "0x970367623fd8efbcbbcfc3a1ad7fa4a6d48cba47", # AnonymousUsername
    "0x7c1ee865a785de4c00ee90ed86a38489fb8bbab3",
    "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
]

async def recompute_all():
    pool = await asyncpg.create_pool(DB_URL, min_size=10, max_size=CONCURRENCY + 10)
    logger.info("Connected to database pool. Fetching wallets to recompute...")
    
    start_time = time.time()
    
    async with pool.acquire() as conn:
        # Get all distinct wallets with positions or metrics
        rows = await conn.fetch("""
            SELECT DISTINCT address FROM (
                SELECT address FROM wallet_closed_positions_v2
                UNION
                SELECT address FROM wallet_metrics_v2
            ) t
        """)
        wallets = [r["address"] for r in rows]
        
    logger.info(f"Found {len(wallets)} total wallets to recompute.")
    
    sem = asyncio.Semaphore(CONCURRENCY)
    processed = 0
    total = len(wallets)
    
    async def _worker(session: aiohttp.ClientSession, addr: str):
        nonlocal processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_metrics_for_wallet(conn, session, addr)
                except Exception as e:
                    logger.error(f"Error computing metrics for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 100 == 0 or processed == total:
                        logger.info(f"Progress: {processed}/{total} wallets computed ({processed/total*100:.1f}%)")

    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [_worker(session, addr) for addr in wallets]
        await asyncio.gather(*tasks)
        
    # Check target whales
    logger.info("\n" + "="*80)
    logger.info("TARGET WHALES POST-COMPUTE VERIFICATION")
    logger.info("="*80)
    
    async with pool.acquire() as conn:
        for addr in TARGET_WHALES:
            m = await conn.fetchrow("""
                SELECT address, pm_pnl, total_pnl, total_volume, win_rate, winning_count, resolved_count
                FROM wallet_metrics_v2
                WHERE address = $1
            """, addr)
            if m:
                pm_pnl = float(m["pm_pnl"] or 0)
                tot_pnl = float(m["total_pnl"] or 0)
                wr = float(m["win_rate"] or 0)
                logger.info(f"Wallet {addr[:14]}... | pm_pnl: ${pm_pnl:>14,.2f} | total_pnl: ${tot_pnl:>14,.2f} | win_rate: {wr:.2f}% ({m['winning_count']}/{m['resolved_count']})")
            else:
                logger.info(f"Wallet {addr[:14]}... | NOT FOUND")
                
    elapsed = time.time() - start_time
    logger.info(f"\nRecomputation of {total} wallets finished in {elapsed:.2f} seconds.")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(recompute_all())
