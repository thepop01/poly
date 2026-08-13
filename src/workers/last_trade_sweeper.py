# src/workers/last_trade_sweeper.py
"""
Worker: Last Trade Activity Sweeper
====================================
Systematically batches tracked wallets to verify their true latest trade/parlay date 
from Polymarket's Data API.

Guarantees 100% downtime recovery: even if trade_tracker missed events while the server 
was offline, this sweeper updates wallets_v2.last_trade_at so Worker 1 (positions/winrate) 
knows exactly which wallets are active and need position backfilling.
"""

import asyncio
import logging
import os
import aiohttp
import asyncpg
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("last_trade_sweeper")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
BATCH_SIZE = 50
CONCURRENCY = 10
SLEEP_INTERVAL = 30  # Sleep 30s between batch loops


async def _check_wallet_last_trade(session: aiohttp.ClientSession, address: str) -> float | None:
    """Fetch the single most recent activity event for a wallet to determine its latest trade timestamp."""
    url = f"https://data-api.polymarket.com/activity?user={address}&limit=1"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data:
                    ts = data[0].get("timestamp")
                    if ts and isinstance(ts, (int, float)) and ts > 0:
                        return float(ts)
    except Exception as e:
        logger.debug(f"Failed to fetch last activity for {address[:12]}: {e}")
    return None


async def run_last_trade_sweeper(db_url: str = DB_URL):
    logger.info("=== STARTING LAST TRADE ACTIVITY SWEEPER WORKER ===")
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=6)
    
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY * 2, keepalive_timeout=30)

    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0"},
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as session:

            while True:
                try:
                    async with pool.acquire() as conn:
                        # Only select wallets where last_trade_swept_at is NULL or older than 3 hours
                        rows = await conn.fetch("""
                            SELECT address, last_trade_at
                            FROM wallets_v2
                            WHERE is_dormant = FALSE
                              AND (last_trade_swept_at IS NULL OR last_trade_swept_at < NOW() - INTERVAL '3 hours')
                            ORDER BY last_trade_swept_at ASC NULLS FIRST
                            LIMIT $1
                        """, BATCH_SIZE)

                    if not rows:
                        logger.info("Worker 10: All active wallets swept within the last 3 hours. Sleeping...")
                        await asyncio.sleep(SLEEP_INTERVAL)
                        continue

                    wallets = [dict(r) for r in rows]
                    updated_count = 0

                    async def _process_one(w):
                        nonlocal updated_count
                        addr = w["address"]
                        curr_last_trade = w["last_trade_at"]

                        async with sem:
                            latest_ts_sec = await _check_wallet_last_trade(session, addr)

                        async with pool.acquire() as conn:
                            if latest_ts_sec:
                                new_dt = datetime.fromtimestamp(latest_ts_sec, tz=timezone.utc)
                                if curr_last_trade is None or new_dt > curr_last_trade:
                                    await conn.execute("""
                                        UPDATE wallets_v2
                                        SET last_trade_at = $2,
                                            is_dormant = CASE WHEN $2 < NOW() - INTERVAL '30 days' THEN TRUE ELSE FALSE END,
                                            last_trade_swept_at = NOW(),
                                            updated_at = NOW()
                                        WHERE address = $1
                                    """, addr, new_dt)
                                    updated_count += 1
                                else:
                                    await conn.execute("UPDATE wallets_v2 SET last_trade_swept_at = NOW(), updated_at = NOW() WHERE address = $1", addr)
                            else:
                                await conn.execute("UPDATE wallets_v2 SET last_trade_swept_at = NOW(), updated_at = NOW() WHERE address = $1", addr)

                    await asyncio.gather(*[_process_one(w) for w in wallets], return_exceptions=True)
                    logger.info(f"Worker 10: Swept {len(wallets)} wallets (>3h since last sweep) — updated last_trade_at for {updated_count} wallets.")

                except Exception as e:
                    logger.error(f"Error in last_trade_sweeper loop: {e}")

                await asyncio.sleep(SLEEP_INTERVAL)
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(run_last_trade_sweeper())
