"""Tier 1: v2 positions sweep worker.

Modes:
  --read-only   Print a report; do not write to the database.
  --shadow      Fetch + stage raw; do not update canonical tables.
  (default)     Full upsert with watermark update.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any

import asyncpg
from dotenv import load_dotenv

from src.pnl.v2_adapter import V2Adapter, PositionRow
from src.workers.positions_open_backfill import upsert_position_with_quarantine

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
logger = logging.getLogger("v2_positions_sweep")

ALL_STATUSES = ("OPEN", "REDEEMABLE", "CLOSED")


def detect_status_overlap(
    open_rows: list[PositionRow],
    redeemable_rows: list[PositionRow],
    closed_rows: list[PositionRow],
) -> list[dict[str, Any]]:
    """Return rows appearing in more than one status bucket by (condition_id, asset_token_id)."""
    def key(r: PositionRow) -> tuple:
        return (r.condition_id, r.asset_token_id or r.outcome_index)

    seen: dict[tuple, str] = {}
    overlaps: list[dict] = []
    for status, rows in [("OPEN", open_rows), ("REDEEMABLE", redeemable_rows),
                         ("CLOSED", closed_rows)]:
        for row in rows:
            k = key(row)
            if k in seen:
                overlaps.append({
                    "condition_id": row.condition_id,
                    "asset_token_id": row.asset_token_id,
                    "status_a": seen[k],
                    "status_b": status,
                })
            else:
                seen[k] = status
    return overlaps


async def sweep_wallet_read_only(address: str) -> dict[str, Any]:
    """Fetch v2 positions for one wallet, return a report dict. No DB writes."""
    async with V2Adapter() as adapter:
        open_rows = await adapter.fetch_positions(address, status="OPEN")
        redeemable_rows = await adapter.fetch_positions(address, status="REDEEMABLE")
        closed_rows = await adapter.fetch_positions(address, status="CLOSED")

    overlaps = detect_status_overlap(open_rows, redeemable_rows, closed_rows)

    invalid_rows = [
        r for r in open_rows + redeemable_rows + closed_rows
        if not r.source_total_pnl_valid
    ]

    # Canonical sum: OPEN + REDEEMABLE + CLOSED, deduplicating overlaps
    # Precedence for overlap: CLOSED > REDEEMABLE > OPEN
    seen_keys: set = set()
    position_pnl = 0.0
    for status, rows in [("CLOSED", closed_rows), ("REDEEMABLE", redeemable_rows),
                         ("OPEN", open_rows)]:
        for row in rows:
            k = (row.condition_id, row.asset_token_id or row.outcome_index)
            if k not in seen_keys:
                seen_keys.add(k)
                if row.source_total_pnl_valid and row.source_total_pnl is not None:
                    position_pnl += row.source_total_pnl

    return {
        "address": address,
        "open_rows": len(open_rows),
        "redeemable_rows": len(redeemable_rows),
        "closed_rows": len(closed_rows),
        "total_rows": len(open_rows) + len(redeemable_rows) + len(closed_rows),
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "invalid_rows": len(invalid_rows),
        "position_pnl": round(position_pnl, 2),
        "complete": len(invalid_rows) == 0 and len(overlaps) == 0,
    }


async def sweep_wallet(
    conn: asyncpg.Connection,
    address: str,
    read_only: bool = False,
) -> dict[str, Any]:
    """Full sweep: read-only report or persistent upsert + watermark."""
    if read_only:
        return await sweep_wallet_read_only(address)

    report = await sweep_wallet_read_only(address)
    ok = quarantined = 0

    async with V2Adapter() as adapter:
        for status in ALL_STATUSES:
            rows = await adapter.fetch_positions(address, status=status)
            for row in rows:
                d = {
                    "address": address, "status": status,
                    "condition_id": row.condition_id,
                    "outcome": row.outcome,
                    "outcome_index": row.outcome_index,
                    "asset_token_id": row.asset_token_id,
                    "event_id": row.event_id,
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
        INSERT INTO wallet_v2_sweep_watermarks
            (address, last_swept_at, rows_ok, rows_quarantined)
        VALUES ($1, NOW(), $2, $3)
        ON CONFLICT (address) DO UPDATE SET
            last_swept_at = NOW(),
            rows_ok = $2,
            rows_quarantined = $3
    """, address, ok, quarantined)

    return {**report, "rows_ok": ok, "rows_quarantined": quarantined}


async def run_fleet_sweep(
    concurrency: int = 10,   # start low, benchmark before increasing
    limit: int | None = None,
) -> None:
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=min(concurrency, 20))
    try:
        async with pool.acquire() as conn:
            q = ("SELECT address FROM wallets_v2 WHERE is_dormant=FALSE "
                 "ORDER BY last_active_at DESC NULLS LAST")
            if limit:
                q += f" LIMIT {int(limit)}"
            rows = await conn.fetch(q)
        wallets = [r["address"] for r in rows]
        sem = asyncio.Semaphore(concurrency)

        async def _do(addr: str) -> None:
            async with sem:
                async with pool.acquire() as conn:
                    try:
                        result = await sweep_wallet(conn, addr)
                        logger.info("sweep %s ok=%s quarantined=%s pnl=%s",
                                    addr[:12], result.get("rows_ok"),
                                    result.get("rows_quarantined"),
                                    result.get("position_pnl"))
                    except Exception:
                        logger.exception("Sweep failed: %s", addr)

        await asyncio.gather(*(_do(a) for a in wallets))
    finally:
        await pool.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true",
                        help="Report only — no DB writes")
    parser.add_argument("--deep-history", action="store_true",
                        help="Fetch pre-2026-09-07 data. EXPLICIT OPT-IN ONLY.")
    parser.add_argument("--wallet", help="Single wallet address")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if args.deep_history:
        logger.warning("DEEP HISTORY MODE — fetching pre-Sept-7 data")

    if args.wallet:
        if args.read_only:
            report = await sweep_wallet_read_only(args.wallet)
        else:
            pool = await asyncpg.create_pool(DB_URL)
            async with pool.acquire() as conn:
                report = await sweep_wallet(conn, args.wallet)
            await pool.close()
        import json
        print(json.dumps(report, indent=2))
    else:
        await run_fleet_sweep(concurrency=args.concurrency, limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
