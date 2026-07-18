import asyncio
import asyncpg
import aiohttp
import logging
import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")
POLYMARKET_DATA_API = "https://data-api.polymarket.com"

async def _get(session: aiohttp.ClientSession, url: str):
    for attempt in range(2):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            if attempt == 0:
                await asyncio.sleep(0.5)
    return None

async def fetch_positions_value(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch open positions and calculate total current value using currentValue field."""
    all_positions = []
    offset = 0
    limit = 500
    while True:
        data = await _get(session, f"{POLYMARKET_DATA_API}/positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_positions.extend(data)
        if len(data) < limit:
            break
        offset += limit
        await asyncio.sleep(0.05)

    position_value = 0.0
    for p in all_positions:
        # Use currentValue (the market value), not size * price which can be None
        curr_val = p.get("currentValue")
        if curr_val is not None:
            try:
                position_value += float(curr_val)
            except (TypeError, ValueError):
                pass
    return position_value

async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch USDC balance from Alchemy."""
    from src.utils.alchemy_client import alchemy_get_token_balances, PUSD_CONTRACT
    try:
        b = await asyncio.wait_for(
            alchemy_get_token_balances(session, address, [PUSD_CONTRACT]),
            timeout=10,
        )
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.error(f"Balance fetch error for {address}: {e}")
    return 0.0

async def fetch_last_trade(session: aiohttp.ClientSession, address: str) -> datetime | None:
    """Fetch the most recent trade timestamp from the Polymarket data API."""
    last_ts = 0
    for role in ("maker", "taker"):
        data = await _get(session, f"{POLYMARKET_DATA_API}/trades?{role}={address}&limit=10")
        if data and isinstance(data, list):
            for t in data:
                try:
                    ts = int(t.get("timestamp", 0))
                    if ts > last_ts:
                        last_ts = ts
                except (TypeError, ValueError):
                    pass
    if last_ts:
        return datetime.fromtimestamp(last_ts, tz=timezone.utc)
    return None

async def process_wallet(pool: asyncpg.Pool, session: aiohttp.ClientSession, address: str):
    try:
        # Fetch all three concurrently
        balance, position_value, last_trade_dt = await asyncio.gather(
            fetch_balance(session, address),
            fetch_positions_value(session, address),
            fetch_last_trade(session, address),
        )

        async with pool.acquire() as conn:
            if last_trade_dt is not None:
                await conn.execute("""
                    UPDATE tracked_wallets SET
                        balance = $2,
                        position_value = $3,
                        last_trade_at = $4
                    WHERE address = $1
                """, address, balance, position_value, last_trade_dt)
            else:
                await conn.execute("""
                    UPDATE tracked_wallets SET
                        balance = $2,
                        position_value = $3
                    WHERE address = $1
                """, address, balance, position_value)

        logger.info(
            f"Updated {address[:8]}: bal=${balance:.0f}, pos_val=${position_value:.0f}, "
            f"last_trade={last_trade_dt.strftime('%Y-%m-%d') if last_trade_dt else 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Error fetching for {address}: {e}")

async def main():
    pool = await asyncpg.create_pool(DB_URL)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT address FROM tracked_wallets 
            WHERE 
                (COALESCE(balance, 0) + COALESCE(position_value, 0)) < 1000
        """)

    addresses = [r["address"] for r in rows]
    logger.info(f"Found {len(addresses)} might-cook wallets to process")

    sem = asyncio.Semaphore(15)  # 15 concurrent requests

    async with aiohttp.ClientSession() as session:
        async def bounded_process(addr):
            async with sem:
                await process_wallet(pool, session, addr)

        tasks = [bounded_process(addr) for addr in addresses]
        await asyncio.gather(*tasks)

    await pool.close()
    logger.info("Done!")

if __name__ == "__main__":
    asyncio.run(main())
