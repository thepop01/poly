"""Activity analyzer worker: reconcile stored activity events against positions.

Reads already-fetched events from wallet_activity_events_v2 (stored by Worker 3),
compares to positions, and persists audit decisions and reconciliation rows.
This is the fast worker — no API calls, just DB reads and writes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

import asyncpg
from dotenv import load_dotenv

from src.scripts.audit_position_activity_coverage import analyze_activity

load_dotenv()
DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
logger = logging.getLogger("activity_analyzer")


async def select_candidates(conn: asyncpg.Connection, limit: int | None = None) -> list[str]:
    """Select staged Activity snapshots that have not been analyzed.

    Historical lineage is optional provenance. It must not block a complete
    Polymarket Activity snapshot from being reconciled.
    """
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    rows = await conn.fetch(f"""
        SELECT s.address
        FROM wallet_activity_scan_state_v2 s
        JOIN wallets_v2 w ON w.address = s.address
        WHERE s.baseline_complete = FALSE
          AND s.last_scan_at IS NOT NULL
          AND s.pending_snapshot_id IS NOT NULL
          AND w.is_dormant = FALSE
        ORDER BY s.last_scan_at ASC
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
                await analyze_activity(address, persist=True)
                completed += 1
                if completed % 10 == 0:
                    logger.info("Analysis progress: %d/%d (err=%d)", completed, len(wallets), failed)
            except Exception:
                failed += 1
                logger.exception("Activity analysis failed for %s", address)

    await asyncio.gather(*(process(address) for address in wallets))
    return {
        "selected": len(wallets), "completed": completed, "failed": failed,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


async def run_loop() -> None:
    interval = int(os.getenv("ACTIVITY_ANALYSIS_INTERVAL_SECONDS", "300"))
    # A full snapshot can contain hundreds of thousands of events.  Limiting
    # concurrent full reads prevents PostgreSQL ClientWrite/tuple-lock storms.
    batch_size = int(os.getenv("ACTIVITY_ANALYSIS_BATCH_SIZE", "100"))
    concurrency = int(os.getenv("ACTIVITY_ANALYSIS_CONCURRENCY", "20"))
    while True:
        try:
            result = await run(concurrency, batch_size)
            logger.info("Periodic Activity analysis: %s", result)
        except Exception:
            logger.exception("Periodic Activity analysis cycle failed")
        await asyncio.sleep(max(30, interval))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("ACTIVITY_ANALYSIS_CONCURRENCY", "20")))
    parser.add_argument(
        "--limit", type=int,
        default=int(os.getenv("ACTIVITY_ANALYSIS_BATCH_SIZE", "100")),
    )
    parser.add_argument("--loop", action="store_true", help="Run scheduled batches continuously")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.loop:
        await run_loop()
        return
    result = await run(args.concurrency, args.limit)
    logger.info("Activity analysis result: %s", result)


if __name__ == "__main__":
    asyncio.run(main())
