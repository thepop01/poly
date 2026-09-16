"""
retry_last_trade_at.py  — retry failed + no-trade wallets (Polymarket only)

For wallets that still have NULL last_trade_at, tries 3 Polymarket params:
  1. ?user={addr}   — primary, correct
  2. ?maker={addr}  — older pre-CLOB trades
  3. ?taker={addr}  — older pre-CLOB trades

No Supabase. Runs at 5 workers with 20s timeout per request.

Usage:
    python src/scripts/retry_last_trade_at.py
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
CONCURRENCY = 5


def _parse_dt(val) -> datetime | None:
    if not val:
        return None
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


async def fetch_polymarket(session: aiohttp.ClientSession, address: str) -> datetime | None:
    """Try user, maker, taker params in order — return first hit."""
    for param in [f"user={address}", f"maker={address}", f"taker={address}"]:
        url = f"{POLYMARKET_TRADES}?{param}&limit=1"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        ts = data[0].get("timestamp") or data[0].get("created_at")
                        dt = _parse_dt(ts)
                        if dt:
                            return dt
        except Exception:
            pass
    return None


async def worker(queue: asyncio.Queue, session: aiohttp.ClientSession, conn, stats: dict):
    while True:
        address = await queue.get()
        try:
            dt = await fetch_polymarket(session, address)
            if dt is not None:
                await conn.execute(
                    "UPDATE tracked_wallets SET last_trade_at = $2 WHERE address = $1",
                    address, dt
                )
                stats["filled"] += 1
            else:
                stats["still_null"] += 1
        except Exception:
            stats["failed"] += 1
        finally:
            stats["done"] += 1
            queue.task_done()
            done = stats["done"]
            total = stats["total"]
            if done % 100 == 0 or done == total:
                print(f"  [{done}/{total} {done/total*100:.1f}%] filled={stats['filled']} still_null={stats['still_null']} fail={stats['failed']}")


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        "SELECT address FROM tracked_wallets WHERE last_trade_at IS NULL ORDER BY address"
    )
    addresses = [r["address"] for r in rows]
    total = len(addresses)
    print(f"Retrying {total} wallets with NULL last_trade_at ({CONCURRENCY} workers, Polymarket only)...")

    if total == 0:
        print("Nothing to do!")
        await conn.close()
        return

    queue = asyncio.Queue()
    for addr in addresses:
        await queue.put(addr)

    stats = {"done": 0, "filled": 0, "still_null": 0, "failed": 0, "total": total}

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 5)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = [asyncio.create_task(worker(queue, session, conn, stats)) for _ in range(CONCURRENCY)]
        await queue.join()
        for w in workers:
            w.cancel()

    await conn.close()
    print(f"\nDone! filled={stats['filled']} still_null={stats['still_null']} fail={stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
