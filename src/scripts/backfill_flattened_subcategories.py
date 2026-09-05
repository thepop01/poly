"""
Backfill wallet_tags with flattened subcategories.

Processes in batches of 50 with 5-second delays to avoid API limits.
Run as a one-time script: python -m src.scripts.backfill_flattened_subcategories
"""

import asyncio
import asyncpg
import os
import logging

from src.utils.category_classifier import flatten_subcategory

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

BATCH_SIZE = 50
DELAY_BETWEEN_BATCHES = 5  # seconds


async def backfill():
    """Backfill wallet_tags with flattened subcategories."""
    conn = await asyncpg.connect(DB_URL)
    total_updated = 0
    total_checked = 0

    logger.info("Starting backfill of flattened subcategories...")

    while True:
        rows = await conn.fetch("""
            SELECT address, category, subcategory
            FROM wallet_tags
            WHERE subcategory IS NOT NULL
            ORDER BY computed_at ASC NULLS FIRST
            LIMIT $1
        """, BATCH_SIZE)

        if not rows:
            break

        updated_in_batch = 0
        for row in rows:
            flat = flatten_subcategory(row["category"], row["subcategory"])
            if flat != row["subcategory"]:
                await conn.execute(
                    "UPDATE wallet_tags SET subcategory = $1 WHERE address = $2",
                    flat, row["address"],
                )
                updated_in_batch += 1

        total_checked += len(rows)
        total_updated += updated_in_batch
        logger.info(f"Batch: {len(rows)} checked, {updated_in_batch} updated, total_checked={total_checked}, total_updated={total_updated}")

        if len(rows) < BATCH_SIZE:
            break

        await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    await conn.close()
    logger.info(f"Backfill complete. Total checked: {total_checked}, Total updated: {total_updated}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(backfill())
