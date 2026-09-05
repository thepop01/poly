"""Supervised, resumable materializer for the unified lineage trade ledger."""

from __future__ import annotations

import asyncio
import logging
import os

from src.scripts.backfill_lineage_trade_ledger import materialize


logger = logging.getLogger("lineage_ledger_backfill")


async def run_loop() -> None:
    batch_size = int(os.getenv("LINEAGE_LEDGER_BATCH_SIZE", "25000"))
    batches_per_cycle = int(os.getenv("LINEAGE_LEDGER_BATCHES_PER_CYCLE", "20"))
    idle_seconds = int(os.getenv("LINEAGE_LEDGER_IDLE_SECONDS", "300"))
    while True:
        try:
            result = await materialize(batch_size=batch_size, max_batches=batches_per_cycle)
            logger.info("Lineage-ledger materialization: %s", result)
            # Yield after a bounded write burst.  Once caught up, this worker
            # remains a cheap integrity check; the real-time tracker writes
            # new transfer rows immediately.
            await asyncio.sleep(idle_seconds if result["complete"] else 1)
        except Exception:
            logger.exception("Lineage-ledger materialization failed")
            await asyncio.sleep(30)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run_loop())
