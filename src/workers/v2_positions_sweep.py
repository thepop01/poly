"""Tier 1: v2 positions sweep with per-wallet watermark."""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import asyncpg
from dotenv import load_dotenv
from src.pnl.v2_adapter import V2Adapter
from src.workers.positions_open_backfill import upsert_position_with_quarantine

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
logger = logging.getLogger("v2_positions_sweep")


async def sweep_wallet(conn: asyncpg.Connection, address: str) -> dict:
    ok = quarantined = 0
    async with V2Adapter() as adapter:
        for status in ("OPEN", "CLOSED"):
            rows = await adapter.fetch_positions(address, status=status)
            for row in rows:
                d = {
                    "address": address, "status": status,
                    "condition_id": row.condition_id, "event_id": row.event_id,
                    "outcome_index": row.outcome_index,
                    "source_total_pnl": row.source_total_pnl,
                    "realized_pnl": row.realized_pnl,
                    "unrealized_pnl": row.unrealized_pnl,
                    "entry_cost_usdc": row.entry_cost_usdc,
                    "total_cost_usdc": row.total_cost_usdc,
                    "entry_fees_usdc": row.entry_fees_usdc,
                    "avg_price": row.avg_price,
                    "current_size": row.current_size,
                    "total_size": row.total_size,
                    "mergeable": row.mergeable,
                }
                result = await upsert_position_with_quarantine(conn, d)
                if result == "ok":
                    ok += 1
                else:
                    quarantined += 1

    await conn.execute("""
        INSERT INTO wallet_v2_sweep_watermarks (address, last_swept_at, rows_ok, rows_quarantined)
        VALUES ($1, NOW(), $2, $3)
        ON CONFLICT (address) DO UPDATE SET last_swept_at=NOW(), rows_ok=$2, rows_quarantined=$3
    """, address, ok, quarantined)
    return {"ok": ok, "quarantined": quarantined}


async def run_fleet_sweep(concurrency: int = 100, limit: int | None = None) -> None:
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=min(concurrency, 20))
    try:
        async with pool.acquire() as conn:
            q = f"SELECT address FROM wallets_v2 WHERE is_dormant=FALSE ORDER BY last_active_at DESC NULLS LAST"
            if limit:
                q += f" LIMIT {int(limit)}"
            rows = await conn.fetch(q)
        wallets = [r["address"] for r in rows]
        sem = asyncio.Semaphore(concurrency)

        async def _do(addr):
            async with sem:
                async with pool.acquire() as conn:
                    try:
                        await sweep_wallet(conn, addr)
                    except Exception:
                        logger.exception("Sweep failed: %s", addr)

        await asyncio.gather(*(_do(a) for a in wallets))
    finally:
        await pool.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep-history", action="store_true",
                        help="Fetch pre-2026-09-07 data. EXPLICIT OPT-IN ONLY.")
    parser.add_argument("--wallet", help="Single wallet targeted sweep")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.deep_history:
        logger.warning("DEEP HISTORY MODE — fetching pre-Sept-7 data (explicit opt-in)")
    if args.wallet:
        pool = await asyncpg.create_pool(DB_URL)
        async with pool.acquire() as conn:
            result = await sweep_wallet(conn, args.wallet)
        print(result)
        await pool.close()
    else:
        await run_fleet_sweep(concurrency=args.concurrency, limit=args.limit)

if __name__ == "__main__":
    import asyncio, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
