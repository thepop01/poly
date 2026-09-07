import asyncio
import asyncpg
import aiohttp
import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_wins")

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL")
CONCURRENCY = 15

async def fetch_all_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    positions = []
    limit = 500
    offset = 0
    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        async with session.get(url) as resp:
            if resp.status != 200:
                break
            data = await resp.json()
            if not data:
                break
            positions.extend(data)
            if len(data) < limit:
                break
            offset += limit
            if offset >= 75000:
                break
    return positions

async def process_wallet(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    positions = await fetch_all_positions(session, address)
    if not positions:
        return
        
    resolved_count = 0
    winning_count = 0
    
    for p in positions:
        cur_val = p.get("currentValue", 1)
        if cur_val == 0:
            resolved_count += 1
            realized_pnl = float(p.get("realizedPnl", 0))
            cash_pnl = float(p.get("cashPnl", 0))
            if (realized_pnl + cash_pnl) > 0:
                winning_count += 1
        else:
            # Triangle Logic: Near-worthless open position -> Loss (matching leaderboard_stats.py)
            cur_price = float(p.get("curPrice", 1))
            if cur_price < 0.03:
                resolved_count += 1
                # loss
                
    win_rate = (winning_count / resolved_count) if resolved_count > 0 else 0.0
    
    await conn.execute('''
        UPDATE wallet_metrics_v2
        SET resolved_count = $1, winning_count = $2, win_rate = $3
        WHERE address = $4
    ''', resolved_count, winning_count, win_rate, address)

async def main():
    raise RuntimeError(
        "backfill_missing_wins is retired: counts are reconstructed from "
        "eligible wallet_closed_positions_v2 by positions_metrics_compute"
    )
    logger.info("Connecting to database...")
    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=20)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.address
            FROM wallets_v2 w
        """)
        addresses = [r["address"] for r in rows]
        
    logger.info(f"Found {len(addresses)} wallets missing resolved counts.")
    
    sem = asyncio.Semaphore(CONCURRENCY)
    done, errors = 0, 0
    
    async def _process(addr):
        nonlocal done, errors
        async with sem:
            try:
                async with aiohttp.ClientSession() as session:
                    async with pool.acquire() as conn:
                        await process_wallet(conn, session, addr)
                done += 1
            except Exception as e:
                logger.error(f"Error on {addr}: {e}")
                errors += 1
            if (done + errors) % 50 == 0:
                logger.info(f"Progress: {done + errors}/{len(addresses)} (ok={done} err={errors})")

    tasks = [_process(addr) for addr in addresses]
    await asyncio.gather(*tasks)
    logger.info(f"Done! {done} succeeded, {errors} failed.")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
