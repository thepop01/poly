"""
Repair Phantom Losses across wallet_closed_positions_v2 (Option A).
Updates all is_redeemable = TRUE rows so that losses are strictly capped
at actual cash outlay (total_bought * avg_buy_price), setting zero-bought
unredeemed positions to $0.00 realized PnL.
"""
import asyncio
import os
import sys
import time
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("repair_phantom_losses")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

async def repair_all():
    conn = await asyncpg.connect(DB_URL)
    logger.info("Connected to database. Starting Option A phantom loss repair...")
    
    start_time = time.time()
    
    # 1. First, tag and zero-out pure minted shares (total_bought = 0 on losing redeemables)
    logger.info("Step 1: Repairing zero-bought minted positions (total_bought = 0)...")
    res1 = await conn.execute("""
        UPDATE wallet_closed_positions_v2
        SET 
            realized_pnl = 0.0,
            data_quality_flag = 'minted_shares'
        WHERE is_redeemable = TRUE 
          AND (total_bought = 0 OR data_quality_flag = 'minted_shares')
          AND avg_sell_price = 0
          AND realized_pnl < 0;
    """)
    logger.info(f"Step 1 Complete: {res1}")
    
    # 2. Repair mixed minted shares where loss exceeded actual cash outlay
    logger.info("Step 2: Repairing mixed minted positions (loss > total_bought * avg_buy_price)...")
    res2 = await conn.execute("""
        UPDATE wallet_closed_positions_v2
        SET 
            realized_pnl = -(total_bought * avg_buy_price),
            data_quality_flag = 'mixed_minted_shares'
        WHERE is_redeemable = TRUE
          AND avg_sell_price = 0
          AND avg_buy_price > 0
          AND total_bought > 0
          AND realized_pnl < -(total_bought * avg_buy_price + 0.01);
    """)
    logger.info(f"Step 2 Complete: {res2}")
    
    # 3. Get summary of repaired rows
    summary = await conn.fetch("""
        SELECT 
            data_quality_flag,
            count(*) as count,
            sum(realized_pnl) as current_rpnl_sum
        FROM wallet_closed_positions_v2
        WHERE is_redeemable = TRUE
        GROUP BY data_quality_flag;
    """)
    
    logger.info("--- OPTION A POST-REPAIR SUMMARY ---")
    for s in summary:
        logger.info(f"Flag: {s['data_quality_flag']!r:24} Rows: {s['count']:<8} Sum PnL: ${float(s['current_rpnl_sum'] or 0):>15,.2f}")
        
    elapsed = time.time() - start_time
    logger.info(f"Option A Repair finished in {elapsed:.2f} seconds.")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(repair_all())
