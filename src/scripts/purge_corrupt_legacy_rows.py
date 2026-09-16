import asyncio
import os
import sys
import logging
import time

sys.path.insert(0, r"D:\project\poly")
from dotenv import load_dotenv
load_dotenv()
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = (os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@127.0.0.1:5432/polymarket").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

async def purge_corrupt_rows():
    logger.info("Connecting to PostgreSQL...")
    conn = await asyncpg.connect(DB_URL)
    
    logger.info("Checking for corrupt legacy blank-outcome rows in wallet_closed_positions_v2...")
    t0 = time.perf_counter()
    
    # We target rows where:
    # 1. outcome is blank/null
    # 2. OR (total_bought = 0 AND avg_buy_price = 0 AND is_redeemable is not true)
    res = await conn.execute("""
        DELETE FROM wallet_closed_positions_v2
        WHERE outcome = '' 
           OR outcome IS NULL 
           OR (total_bought = 0 AND avg_buy_price = 0 AND (is_redeemable IS NULL OR is_redeemable = false));
    """)
    t1 = time.perf_counter()
    
    logger.info(f"Database Cleanup Complete in {(t1 - t0):.2f}s: {res}")
    
    # Verify remaining rows
    remaining = await conn.fetchval("SELECT COUNT(*) FROM wallet_closed_positions_v2")
    logger.info(f"Remaining Clean Positions in wallet_closed_positions_v2: {remaining:,}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(purge_corrupt_rows())
