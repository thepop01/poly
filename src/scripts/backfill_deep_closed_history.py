"""Explicitly recover a wallet whose closed-position history exceeds offset 100,000.

The command fetches first and writes only with --apply.  It never deletes
ledger rows, and it advances closed_synced_at only after both Activity market
discovery and all per-market closed-position reads prove complete.
"""

from __future__ import annotations

import argparse
import asyncio
import os

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.utils.polymarket_rate_limit import PostgresRateLimiter
from src.workers.compute_category_stats import compute_category_stats_for_wallet
from src.workers.compute_core_metrics import compute_core_metrics_for_wallet
from src.workers.compute_historical_windows import compute_historical_windows_for_wallet
from src.workers.positions_winrate_backfill import upsert_closed_positions_v2
from src.workers.wallet_trade_history import fetch_closed_positions

load_dotenv()
DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")


async def run(address: str, apply: bool) -> dict:
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    try:
        limiter = PostgresRateLimiter(pool)
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            positions, complete = await fetch_closed_positions(
                session, address, rate_limiter=limiter, recover_deep_history=True
            )
        result = {"address": address, "rows": len(positions), "complete": complete, "applied": apply}
        if not apply:
            return result
        if not complete:
            raise RuntimeError("refusing to write incomplete deep closed history")
        async with pool.acquire() as conn:
            async with conn.transaction():
                await upsert_closed_positions_v2(conn, address, positions)
                await conn.execute("""
                    INSERT INTO wallet_metrics_v2 (address, closed_synced_at)
                    VALUES ($1, NOW())
                    ON CONFLICT (address) DO UPDATE SET closed_synced_at=NOW()
                """, address)
                await compute_core_metrics_for_wallet(conn, address)
                await compute_category_stats_for_wallet(conn, address)
                await compute_historical_windows_for_wallet(conn, address)
        return result
    finally:
        await pool.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--apply", action="store_true", help="Upsert only a proven-complete recovered history")
    args = parser.parse_args()
    print(await run(args.address.lower(), args.apply))


if __name__ == "__main__":
    asyncio.run(main())
