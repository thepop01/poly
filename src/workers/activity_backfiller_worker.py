"""Worker 3A: fetch and store raw Activity snapshots.

This is the slow worker: recursive bisection to avoid the 5000 offset cap.
Stores raw events in wallet_activity_events_v2 and updates the scan-state
watermark. Historical lineage transfer scanning is paused: it is optional
provenance, not a prerequisite for Activity reconciliation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import asyncpg
from dotenv import load_dotenv

from src.scripts.audit_position_activity_coverage import backfill_activity
from src.scripts.backfill_market_activity import incremental_aggregate_wallet

load_dotenv()
DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
logger = logging.getLogger("activity_backfiller")


async def select_candidates(conn: asyncpg.Connection, limit: int | None = None) -> list[str]:
    """Select wallets needing activity backfill.

    Priority: wallets never scanned, then wallets with oldest scan time.
    The operational queue is deliberately limited to the approved divergence
    threshold; a full fleet sweep would create API load without audit value.
    """
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    rows = await conn.fetch(f"""
        SELECT m.address
        FROM wallet_metrics_v2 m
        JOIN wallets_v2 w ON w.address = m.address
        WHERE m.pm_pnl IS NOT NULL
          AND m.total_pnl IS NOT NULL
          AND w.is_dormant = FALSE
          AND (
              ABS(m.total_pnl - m.pm_pnl) >= 10000
              OR (
                  ABS(m.total_pnl - m.pm_pnl) >= 1000
                  AND ABS(m.total_pnl - m.pm_pnl) / GREATEST(ABS(m.pm_pnl), 1000) >= 0.10
              )
          )
          AND NOT EXISTS (
                  SELECT 1 FROM wallet_activity_scan_state_v2 pending
                  WHERE pending.address = m.address
                    AND pending.baseline_complete = FALSE
                    AND pending.pending_snapshot_id IS NOT NULL
                  )
        ORDER BY
          CASE
            WHEN EXISTS (
                SELECT 1 FROM wallet_activity_scan_state_v2 repair
                WHERE repair.address = m.address
                  AND repair.baseline_complete = FALSE
                  AND repair.pending_snapshot_id IS NULL
            ) THEN 0
            WHEN NOT EXISTS (
                SELECT 1 FROM wallet_activity_scan_state_v2 unseen
                WHERE unseen.address = m.address
            ) THEN 1
            ELSE 2
          END,
          (SELECT last_scan_at FROM wallet_activity_scan_state_v2 s WHERE s.address = m.address) NULLS FIRST,
          ABS(m.total_pnl - m.pm_pnl) DESC
        {limit_sql}
    """)
    return [str(row["address"]).lower() for row in rows]


async def run(concurrency: int, limit: int | None) -> dict[str, int | float]:
    conn = await asyncpg.connect(DB_URL)
    try:
        wallets = await select_candidates(conn, limit)
    finally:
        await conn.close()
    if not wallets:
        return {"selected": 0, "completed": 0, "failed": 0, "elapsed_seconds": 0.0}

    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=min(concurrency, 20),
                                     timeout=60, command_timeout=300)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    completed = failed = 0
    started = time.monotonic()

    async def process(address: str) -> None:
        nonlocal completed, failed
        async with semaphore:
            try:
                now = int(time.time())
                await backfill_activity(address, 1, now, persist=True)
                await incremental_aggregate_wallet(pool, address)
                completed += 1
                if completed % 10 == 0:
                    logger.info("Backfill progress: %d/%d (err=%d)", completed, len(wallets), failed)
            except Exception:
                failed += 1
                logger.exception("Activity backfill failed for %s", address)

    try:
        await asyncio.gather(*(process(address) for address in wallets))
    finally:
        await pool.close()
    return {
        "selected": len(wallets), "completed": completed, "failed": failed,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


async def run_loop() -> None:
    # When the queue is non-empty, continue promptly instead of sleeping for
    # the full idle interval between batches.  The long interval is retained
    # only when no candidate was found, which protects the API while still
    # draining an active backlog quickly.
    interval = int(os.getenv("ACTIVITY_BACKFILL_INTERVAL_SECONDS", "900"))
    active_interval = int(os.getenv("ACTIVITY_BACKFILL_ACTIVE_INTERVAL_SECONDS", "10"))
    batch_size = int(os.getenv("ACTIVITY_BACKFILL_BATCH_SIZE", "150"))
    concurrency = int(os.getenv("ACTIVITY_BACKFILL_CONCURRENCY", "100"))
    while True:
        result: dict[str, int | float] = {}
        try:
            result = await run(concurrency, batch_size)
            logger.info("Periodic Activity backfill: %s", result)
        except Exception:
            logger.exception("Periodic Activity backfill cycle failed")
        delay = active_interval if result.get("selected", 0) else interval
        await asyncio.sleep(max(5, delay))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument(
        "--limit", type=int,
        default=int(os.getenv("ACTIVITY_BACKFILL_BATCH_SIZE", "150")),
    )
    parser.add_argument("--loop", action="store_true", help="Run scheduled batches continuously")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.loop:
        await run_loop()
        return
    result = await run(args.concurrency, args.limit)
    logger.info("Activity backfill result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
