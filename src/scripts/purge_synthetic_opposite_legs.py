"""Remove fabricated opposite-leg rows from the old reconcile script."""
import argparse, asyncio, logging, os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL environment variable not set")
logger = logging.getLogger("purge_synthetic")

FILTER = """
    data_quality_flag IN ('minted_shares', 'synthetic_liquidation_artifact', 'synthetic_mint')
    OR provenance = 'synthetic_artifact'
    OR synthetic_artifact = TRUE
"""

async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(DB_URL)
    try:
        n_open   = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_positions_v2 WHERE {FILTER}")
        n_closed = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_closed_positions_v2 WHERE {FILTER}")
        logger.info("Synthetic rows — open: %d  closed: %d", n_open, n_closed)
        if dry_run:
            logger.info("DRY RUN — no rows deleted"); return
        await conn.execute(f"DELETE FROM wallet_positions_v2 WHERE {FILTER}")
        await conn.execute(f"DELETE FROM wallet_closed_positions_v2 WHERE {FILTER}")
        logger.info("Purge complete")
    finally:
        await conn.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(p.parse_args().dry_run))
