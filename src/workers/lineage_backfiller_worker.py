"""Worker 3B: backfill per-wallet CTF lineage transfer evidence.

This worker consumes wallets with a staged Activity snapshot but no completed
lineage baseline. It scans incoming/outgoing ERC-1155 CTF transfers only;
Worker 4 remains gated until this wallet-level flag is complete.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import asyncpg
from dotenv import load_dotenv

from src.workers.lineage_transfer_backfill import backfill_lineage_transfers

load_dotenv()
DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
logger = logging.getLogger("lineage_backfiller")


async def select_candidates(conn: asyncpg.Connection, limit: int | None = None) -> list[str]:
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    rows = await conn.fetch(f"""
        SELECT s.address
        FROM wallet_activity_scan_state_v2 s
        JOIN wallets_v2 w ON w.address = s.address
        JOIN wallet_metrics_v2 m ON m.address = s.address
        WHERE s.pending_snapshot_id IS NOT NULL
          AND s.baseline_complete = FALSE
          AND s.lineage_baseline_complete = FALSE
          AND m.pm_pnl IS NOT NULL
          AND m.total_pnl IS NOT NULL
          AND w.is_dormant = FALSE
        ORDER BY s.last_scan_at ASC NULLS FIRST
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

    semaphore = asyncio.Semaphore(max(1, concurrency))
    completed = failed = 0
    started = time.monotonic()

    async def process(address: str) -> None:
        nonlocal completed, failed
        async with semaphore:
            try:
                await backfill_lineage_transfers(address)
                completed += 1
                if completed % 10 == 0:
                    logger.info("Lineage progress: %d/%d (err=%d)", completed, len(wallets), failed)
            except Exception:
                failed += 1
                logger.exception("Lineage backfill failed for %s", address)

    await asyncio.gather(*(process(address) for address in wallets))
    return {
        "selected": len(wallets), "completed": completed, "failed": failed,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


async def run_loop() -> None:
    interval = int(os.getenv("LINEAGE_BACKFILL_INTERVAL_SECONDS", "900"))
    active_interval = int(os.getenv("LINEAGE_BACKFILL_ACTIVE_INTERVAL_SECONDS", "10"))
    batch_size = int(os.getenv("LINEAGE_BACKFILL_BATCH_SIZE", "150"))
    concurrency = int(os.getenv("LINEAGE_BACKFILL_CONCURRENCY", "100"))
    while True:
        result: dict[str, int | float] = {}
        try:
            result = await run(concurrency, batch_size)
            logger.info("Periodic lineage backfill: %s", result)
        except Exception:
            logger.exception("Periodic lineage backfill cycle failed")
        delay = active_interval if result.get("selected", 0) else interval
        await asyncio.sleep(max(5, delay))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--limit", type=int, default=int(os.getenv("LINEAGE_BACKFILL_BATCH_SIZE", "150")))
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.loop:
        await run_loop()
    else:
        logger.info("Lineage backfill result: %s", await run(args.concurrency, args.limit))


if __name__ == "__main__":
    asyncio.run(main())
