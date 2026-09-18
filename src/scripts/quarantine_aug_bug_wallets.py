"""Flag wallets affected by the Aug 7/24/31 Polymarket settlement bug.
Populate AUG_BUG_CONDITIONS when Polymarket provides the correction list.
"""
import asyncio, logging, os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
logger = logging.getLogger("aug_bug_quarantine")

AUG_BUG_CONDITIONS: list[str] = []  # populate from Polymarket correction list

async def run() -> None:
    if not AUG_BUG_CONDITIONS:
        logger.warning("AUG_BUG_CONDITIONS empty — awaiting Polymarket correction list")
        return
    conn = await asyncpg.connect(DB_URL)
    try:
        affected = await conn.fetch("""
            SELECT DISTINCT address FROM wallet_positions_v2
            WHERE condition_id = ANY($1::text[])
            UNION
            SELECT DISTINCT address FROM wallet_closed_positions_v2
            WHERE condition_id = ANY($1::text[])
        """, AUG_BUG_CONDITIONS)
        for row in affected:
            await conn.execute("""
                INSERT INTO position_quarantine (address, condition_id, outcome, status, failure_reason)
                SELECT $1, condition_id, outcome, status, 'polymarket_settlement_bug_aug_2026'
                FROM wallet_positions_v2 WHERE address=$1 AND condition_id=ANY($2::text[])
                ON CONFLICT DO NOTHING
            """, row["address"], AUG_BUG_CONDITIONS)
        logger.info("Quarantined %d wallets", len(affected))
    finally:
        await conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
