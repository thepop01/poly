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
    from src.workers.leaderboard_stats import fetch_balance, fetch_website_pnl
    
    # Run requests concurrently for speed
    balance_task = fetch_balance(session, address)
    pnl_task = fetch_website_pnl(session, address)
    
    balance, pnl_data = await asyncio.gather(balance_task, pnl_task, return_exceptions=True)
    
    if isinstance(balance, Exception):
        logger.error(f"Error fetching balance for {address}: {balance}")
        balance = 0.0
        
    if isinstance(pnl_data, Exception):
        logger.error(f"Error fetching PnL for {address}: {pnl_data}")
        pnl_data = None

    is_zero_balance = (balance < 1.0)
    
    async with pool.acquire() as conn:
        if pnl_data:
            total_pnl = pnl_data.get("pnl", 0)
            total_volume = pnl_data.get("volume", 0)
            username = pnl_data.get("username", "")
            
            await conn.execute("""
                UPDATE tracked_wallets SET
                    balance = $2,
                    total_pnl = $3,
                    website_pnl = $3,
                    total_volume = $4,
                    is_zero_balance = $5,
                    username = COALESCE(NULLIF($6, ''), username)
                WHERE address = $1
            """, address, balance, total_pnl, total_volume, is_zero_balance, username)
            
            logger.info(f"Updated {address[:8]}: bal=${balance:.0f} pnl=${total_pnl:.0f} vol=${total_volume:.0f}")
        else:
            # Just update balance
            await conn.execute("""
                UPDATE tracked_wallets SET
                    balance = $2,
                    is_zero_balance = $3
                WHERE address = $1
            """, address, balance, is_zero_balance)
            logger.info(f"Updated {address[:8]}: bal=${balance:.0f} (No PnL data)")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000, help="Max wallets to process")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL)
    
    # Fetch all active wallets, prioritizing those with largest balance or older updates
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT address FROM tracked_wallets 
            ORDER BY balance DESC NULLS LAST
            LIMIT $1
        """, args.limit)
        
    addresses = [r["address"] for r in rows]
    logger.info(f"Found {len(addresses)} wallets to process")
    
    sem = asyncio.Semaphore(15) # 15 concurrent requests to avoid rate limits
    
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
