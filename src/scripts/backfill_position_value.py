import asyncio
import asyncpg
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def backfill():
    raise RuntimeError(
        "backfill_position_value is retired: open source fields are owned by "
        "positions_open_backfill"
    )
    logger.info("Connecting to database...")
    conn = await asyncpg.connect(DB_URL)
    
    logger.info("Updating position_value for wallets WITH open positions...")
    res1 = await conn.execute("""
        UPDATE wallet_metrics_v2 m
        SET position_value = p.total_val,
            unrealised_pnl = p.total_unreal,
            computed_at = NOW()
        FROM (
            SELECT address,
                   COALESCE(SUM(current_value), 0)   AS total_val,
                   COALESCE(SUM(unrealized_pnl), 0)  AS total_unreal
            FROM wallet_positions_v2
            GROUP BY address
        ) p
        WHERE m.address = p.address;
    """)
    logger.info(f"Result: {res1}")
    
    logger.info("Setting position_value to 0 for wallets WITHOUT open positions...")
    res2 = await conn.execute("""
        UPDATE wallet_metrics_v2
        SET position_value = 0,
            unrealised_pnl = 0,
            computed_at = NOW()
        WHERE address NOT IN (SELECT address FROM wallet_positions_v2)
          AND (position_value IS NULL OR position_value != 0);
    """)
    logger.info(f"Result: {res2}")
    
    await conn.close()
    logger.info("Done!")

if __name__ == "__main__":
    asyncio.run(backfill())
