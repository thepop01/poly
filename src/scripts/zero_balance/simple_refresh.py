#!/usr/bin/env python3
"""
Simple, direct refresh script - batch updates without async complexity.
"""
import asyncpg
import aiohttp
import asyncio
import os
import sys
import logging
import time
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")
DATA_API = "https://data-api.polymarket.com"


async def fetch_positions(session, address):
    """Fetch positions from Polymarket API."""
    try:
        url = f"{DATA_API}/positions?user={address}&limit=500"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.debug(f"Position fetch failed: {e}")
    return []


async def process_batch(conn, addresses, session):
    """Process a batch of addresses."""
    results = []

    for addr in addresses:
        try:
            # Fetch positions
            positions = await fetch_positions(session, addr)

            # Sum position values
            position_value = 0.0
            if positions:
                for p in positions:
                    cv = p.get('currentValue')
                    if cv and isinstance(cv, (int, float)):
                        position_value += float(cv)

            results.append({
                'address': addr,
                'position_value': position_value
            })
        except Exception as e:
            logger.warning(f"Error processing {addr}: {e}")
            results.append({'address': addr, 'position_value': 0.0})

    # Update database
    if results:
        try:
            await conn.executemany("""
                UPDATE wallet_metrics_v2
                SET position_value = $2, computed_at = NOW()
                WHERE address = $1
            """, [(r['address'], r['position_value']) for r in results])
            logger.info(f"Updated {len(results)} wallets in DB")
        except Exception as e:
            logger.error(f"DB update failed: {e}")

    return len(results)


async def main():
    conn = await asyncpg.connect(DB_URL)
    logger.info("Connected to database")

    # Get wallets with 0 balance
    rows = await conn.fetch("""
        SELECT w.address
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE w.tier NOT IN ('DEAD', 'UNCLASSIFIED')
          AND COALESCE(m.balance, 0) = 0
        LIMIT 14118
    """)

    addresses = [r['address'] for r in rows]
    total = len(addresses)
    logger.info(f"Found {total} wallets with zero balance to refresh")

    if total == 0:
        await conn.close()
        return

    batch_size = 50
    processed = 0
    start = time.time()

    async with aiohttp.ClientSession() as session:
        for i in range(0, total, batch_size):
            batch = addresses[i:i+batch_size]
            count = await process_batch(conn, batch, session)
            processed += count

            elapsed = time.time() - start
            rate = processed / elapsed if elapsed > 0 else 0
            pct = (i + batch_size) / total * 100

            logger.info(f"Progress: {processed}/{total} ({pct:.1f}%) | {rate:.1f} w/s | Elapsed: {elapsed:.0f}s")
            await asyncio.sleep(0.5)

    elapsed = time.time() - start
    logger.info(f"COMPLETE: Processed {processed} wallets in {elapsed:.0f}s")

    await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
        sys.exit(1)
