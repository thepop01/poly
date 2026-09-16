"""
fetch_last_trade_at.py  — bulk-fetch real last_trade_at for all wallets

Hits Polymarket /trades?user={addr}&limit=1 for every wallet with NULL
last_trade_at. Writes the result directly (not GREATEST) so old corrupt
values can also be corrected.

Concurrency: 20 workers (Polymarket has no strict rate limit for this).
Progress printed every 200 wallets.

Usage:
    python src/scripts/fetch_last_trade_at.py
"""

import asyncio
import os
from datetime import datetime, timezone

import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = "postgres://poly_user:poly_password@localhost:5432/poly_db"
POLYMARKET_TRADES = "https://data-api.polymarket.com/trades"
CONCURRENCY = 20


def _parse_dt(val) -> datetime | None:
    if not val:
        return None
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


async def fetch_last_trade(session: aiohttp.ClientSession, address: str) -> datetime | None:
    url = f"{POLYMARKET_TRADES}?user={address}&limit=1"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                return None
            trade = data[0]
            # Try timestamp field first, then created_at
            ts = trade.get("timestamp") or trade.get("created_at")
            return _parse_dt(ts)
    except Exception:
        return None


async def worker(queue: asyncio.Queue, session: aiohttp.ClientSession, conn, stats: dict):
    while True:
        address = await queue.get()
        try:
            last_trade = await fetch_last_trade(session, address)
            if last_trade is not None:
                # Direct write — NOT GREATEST — so we can overwrite corrupt values
                await conn.execute(
                    "UPDATE tracked_wallets SET last_trade_at = $2 WHERE address = $1",
                    address, last_trade
                )
                stats["filled"] += 1
            else:
                stats["no_trade"] += 1
        except Exception as e:
            stats["failed"] += 1
        finally:
            stats["done"] += 1
            queue.task_done()

            done = stats["done"]
            if done % 200 == 0:
                total = stats["total"]
                pct = done / total * 100
                print(f"  [{done}/{total} {pct:.1f}%] filled={stats['filled']} no_trade={stats['no_trade']} fail={stats['failed']}")


async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    # Fetch ALL wallets (not just NULL ones) so we overwrite any corrupt values too
    rows = await conn.fetch("SELECT address FROM tracked_wallets ORDER BY address")
    addresses = [r["address"] for r in rows]
    total = len(addresses)

    print(f"Fetching last_trade_at for {total} wallets with {CONCURRENCY} workers...")

    queue = asyncio.Queue()
    for addr in addresses:
        await queue.put(addr)

    stats = {"done": 0, "filled": 0, "no_trade": 0, "failed": 0, "total": total}

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = [asyncio.create_task(worker(queue, session, conn, stats)) for _ in range(CONCURRENCY)]
        await queue.join()
        for w in workers:
            w.cancel()

    await conn.close()
    print(f"\nDone! filled={stats['filled']} no_trade={stats['no_trade']} fail={stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
