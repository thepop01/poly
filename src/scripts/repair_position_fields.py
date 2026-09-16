import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("repair_position_fields")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

async def repair_positions(wallet: str = None):
    conn = await asyncpg.connect(DB_URL)
    try:
        where_clause = "WHERE address = $1 AND (total_bought = 0 OR total_bought IS NULL) AND realized_pnl != 0" if wallet else "WHERE (total_bought = 0 OR total_bought IS NULL) AND realized_pnl != 0"
        args = [wallet] if wallet else []
        
        count = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_closed_positions_v2 {where_clause}", *args)
        logger.info(f"Found {count} positions with total_bought = 0 and non-zero realized_pnl")
        
        if count > 0:
            # Set data_quality_flag = 'missing_total_bought' instead of synthesizing fake numbers
            update_sql = f"""
                UPDATE wallet_closed_positions_v2
                SET data_quality_flag = 'missing_total_bought'
                {where_clause}
            """
            result = await conn.execute(update_sql, *args)
            logger.info(f"Flagged missing_total_bought positions: {result}")
            
        # Clean any corrupted rows where avg_buy_price was previously set to 1.0 by the old repair script
        cleanup_sql = "WHERE address = $1 AND avg_buy_price = 1.0 AND (total_bought = ABS(realized_pnl) OR total_bought = 0)" if wallet else "WHERE avg_buy_price = 1.0 AND (total_bought = ABS(realized_pnl) OR total_bought = 0)"
        cleanup_count = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_closed_positions_v2 {cleanup_sql}", *args)
        if cleanup_count > 0:
            await conn.execute(f"""
                UPDATE wallet_closed_positions_v2
                SET avg_buy_price = 0.0, total_bought = 0.0, data_quality_flag = 'missing_avg_price'
                {cleanup_sql}
            """, *args)
            logger.info(f"Reverted {cleanup_count} previously corrupted rows with guessed 1.0 avg_buy_price")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    wallet = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(repair_positions(wallet))
