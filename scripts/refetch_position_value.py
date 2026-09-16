import asyncio
import asyncpg
import aiohttp
import argparse
import logging
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")

async def process_wallet(pool: asyncpg.Pool, session: aiohttp.ClientSession, address: str):
    from src.workers.leaderboard_stats import fetch_positions, _parse
    
    try:
        open_positions = await fetch_positions(session, address)
        position_value = 0.0
        if open_positions:
            for p in open_positions:
                curr_val = _parse(p.get("size")) * _parse(p.get("price"))
                position_value += curr_val
                
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE tracked_wallets SET
                    position_value = $2
                WHERE address = $1
            """, address, position_value)
            
        logger.info(f"Updated {address[:8]}: pos_val=${position_value:.0f}")
    except Exception as e:
        logger.error(f"Error fetching position_value for {address}: {e}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000, help="Max wallets to process")
    parser.add_argument("--all", action="store_true", help="Process all wallets instead of just missing")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL)
    
    async with pool.acquire() as conn:
        if args.all:
            rows = await conn.fetch("""
                SELECT address FROM tracked_wallets 
                WHERE is_zero_balance = FALSE
                ORDER BY balance DESC NULLS LAST
                LIMIT $1
            """, args.limit)
        else:
            rows = await conn.fetch("""
                SELECT address FROM tracked_wallets 
                WHERE is_zero_balance = FALSE AND position_value IS NULL
                ORDER BY balance DESC NULLS LAST
                LIMIT $1
            """, args.limit)
        
    addresses = [r["address"] for r in rows]
    logger.info(f"Found {len(addresses)} wallets to process")
    
    sem = asyncio.Semaphore(10) # 10 concurrent requests
    
    async with aiohttp.ClientSession() as session:
        async def bounded_process(addr):
            async with sem:
                await process_wallet(pool, session, addr)
                
        tasks = [bounded_process(addr) for addr in addresses]
        await asyncio.gather(*tasks)

    await pool.close()
    logger.info("Done!")

if __name__ == "__main__":
    asyncio.run(main())
