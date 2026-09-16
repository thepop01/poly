import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

import aiohttp
import asyncpg
from src.db import get_pool
from src.workers.positions_open_backfill import process_wallet_open
from src.workers.positions_closed_backfill import process_wallet_closed
from src.workers.positions_metrics_compute import compute_metrics_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backfill_single_wallet")

async def full_backfill(wallet: str):
    clean_addr = wallet.lower().strip()
    pool = await get_pool()
    
    logger.info(f"=== STARTING FULL BACKFILL FOR {clean_addr} ===")
    
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        async with pool.acquire() as conn:
            # 1. Backfill Open Positions & Concluded Redeemables
            logger.info("1/3. Ingesting Open Positions & Concluded Markets...")
            await process_wallet_open(conn, session, clean_addr)
            
            # 2. Backfill Closed Positions
            logger.info("2/3. Ingesting Closed Positions...")
            await process_wallet_closed(conn, session, clean_addr)
            
            # 3. Compute Metrics & Category Stats
            logger.info("3/3. Computing Metrics & Category Rollups...")
            await compute_metrics_for_wallet(conn, session, clean_addr)
            
            # 4. Fetch Summary from DB
            metrics = await conn.fetchrow("SELECT * FROM wallet_metrics_v2 WHERE address = $1", clean_addr)
            open_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_positions_v2 WHERE address = $1 AND COALESCE(current_value, 0) > 0", clean_addr)
            closed_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_closed_positions_v2 WHERE address = $1", clean_addr)
            
            print("\n=======================================================")
            print(f"       BACKFILL COMPLETE FOR {clean_addr}        ")
            print("=======================================================")
            print(f"  Active Open Positions in DB:    {open_count}")
            print(f"  Closed & Concluded Rows in DB:  {closed_count}")
            if metrics:
                print(f"  DB Computed Total PnL:          ${float(metrics['total_pnl'] or 0):>15,.2f}")
                print(f"  Polymarket Leaderboard (pm_pnl):${float(metrics['pm_pnl'] or 0):>15,.2f}")
                print(f"  Win Rate:                       {float(metrics['win_rate'] or 0):.2f}% ({metrics['winning_count']}W / {max(0, (metrics['resolved_count'] or 0) - (metrics['winning_count'] or 0))}L)")
                print(f"  Last 100 PnL (pnl_100):         ${float(metrics['pnl_100'] or 0):>15,.2f}")
                print(f"  Last 500 PnL (pnl_500):         ${float(metrics['pnl_500'] or 0):>15,.2f}")
                print(f"  Last 5000+ PnL (pnl_5000):      ${float(metrics['pnl_5000'] or 0):>15,.2f}")
            print("=======================================================\n")

if __name__ == "__main__":
    wallet_arg = sys.argv[1] if len(sys.argv) > 1 else "0xf0318c32136c2db7fec88b84869aee6a1106c80c"
    asyncio.run(full_backfill(wallet_arg))
