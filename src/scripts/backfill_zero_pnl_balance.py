import asyncio
import asyncpg
import aiohttp
import os
import logging
import sys
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.workers.leaderboard_stats import fetch_website_pnl
from src.workers.stats_refresher import fetch_balance

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def backfill():
    raise RuntimeError(
        "backfill_zero_pnl_balance is retired: official PnL must remain in "
        "pm_pnl and canonical totals come from the position ledger"
    )
    logger.info("Connecting to database...")
    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=20)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT address, total_pnl, balance 
            FROM wallet_metrics_v2 
            WHERE total_pnl IS NULL OR total_pnl = 0 
               OR balance IS NULL OR balance = 0
        """)
        addresses = [r["address"] for r in rows]
        
    logger.info(f"Found {len(addresses)} wallets with missing or 0 PnL/Balance.")
    
    if not addresses:
        logger.info("Nothing to do.")
        await pool.close()
        return

    sem = asyncio.Semaphore(15)  # Fetch up to 15 concurrently
    
    async def process_wallet(session, address, pool):
        async with sem:
            try:
                # Fetch balance and PnL concurrently for the wallet
                balance_f, pnl_f = await asyncio.gather(
                    fetch_balance(session, address),
                    fetch_website_pnl(session, address),
                    return_exceptions=True
                )
                
                balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
                website_data = pnl_f if isinstance(pnl_f, dict) else None
                
                pnl = website_data["pnl"] if website_data else 0.0
                volume = website_data["volume"] if website_data else 0.0
                
                # Only update if we successfully fetched non-zero data
                if balance != 0.0 or pnl != 0.0 or volume != 0.0:
                    async with pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE wallet_metrics_v2
                            SET balance = $1, total_pnl = $2, total_volume = $3
                            WHERE address = $4
                        """, balance, pnl, volume, address)
                    logger.info(f"✅ Updated {address[:8]}: PnL=${pnl:.2f}, Bal=${balance:.2f}")
                else:
                    logger.debug(f"ℹ️ Still zero for {address[:8]}")

            except Exception as e:
                logger.error(f"❌ Failed to process {address[:8]}: {e}")

    async with aiohttp.ClientSession() as session:
        batch_size = 500
        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(addresses) + batch_size - 1)//batch_size}...")
            
            tasks = [process_wallet(session, addr, pool) for addr in batch]
            await asyncio.gather(*tasks)
                
    await pool.close()
    logger.info("Backfill complete!")

if __name__ == "__main__":
    asyncio.run(backfill())
