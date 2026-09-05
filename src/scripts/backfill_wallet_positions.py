import asyncio
import asyncpg
import aiohttp
import os
import logging
import sys
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.workers.wallet_trade_history import fetch_positions
from src.workers.leaderboard_stats_v2 import aggregate_and_upsert_positions_v2

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def safe_fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_positions = []
    offset = 0
    limit = 500
    while offset < 20000:  # safety cap
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data or not isinstance(data, list):
                        break
                    all_positions.extend(data)
                    if len(data) < limit:
                        break
                    offset += limit
                else:
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch positions for {address} at offset {offset}: {e}")
            break
    return all_positions

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def backfill_positions():
    logger.info("Connecting to database...")
    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=20)
    
    async with pool.acquire() as conn:
        # Fetch active wallets that DO NOT have any positions recorded in wallet_positions_v2 yet.
        # This honors the request to "fetch the ones that we dont have".
        rows = await conn.fetch("""
            SELECT w.address 
            FROM wallets_v2 w
            WHERE w.is_dormant = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM wallet_positions_v2 p WHERE p.address = w.address
              )
        """)
        addresses = [r["address"] for r in rows]
        
    logger.info(f"Found {len(addresses)} active wallets missing from wallet_positions_v2.")
    
    if not addresses:
        logger.info("Nothing to do.")
        await pool.close()
        return

    # Use a semaphore to limit concurrent API requests
    sem = asyncio.Semaphore(10)
    
    async def process_wallet(session, address, pool):
        async with sem:
            try:
                positions = await safe_fetch_positions(session, address)
                if positions:
                    async with pool.acquire() as conn:
                        await aggregate_and_upsert_positions_v2(conn, address, positions)
                    logger.info(f"✅ Fetched and saved {len(positions)} positions for {address[:8]}")
                else:
                    logger.debug(f"ℹ️ No open positions found for {address[:8]}")
            except Exception as e:
                logger.error(f"❌ Failed to process {address[:8]}: {e}")

    async with aiohttp.ClientSession() as session:
        # Process in batches 
        batch_size = 500
        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(addresses) + batch_size - 1)//batch_size}...")
            
            tasks = [process_wallet(session, addr, pool) for addr in batch]
            await asyncio.gather(*tasks)
                
    await pool.close()
    logger.info("Backfill complete!")

if __name__ == "__main__":
    asyncio.run(backfill_positions())
