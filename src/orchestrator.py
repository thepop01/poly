# src/orchestrator.py
"""
Robust Worker Orchestrator
==========================
Supervises all specialized background workers and services.
Automatically restarts crashed workers with exponential backoff.

Decoupled Workers Managed:
1. Worker 1: Positions & Win-Rate Sync (Polymarket REST API + 10-Window PnLs)
2. Worker 2: Capital Metrics Worker (Alchemy RPC USDC Deposits, Peak Capital, ROI %)
3. Worker 3: On-Chain Verifier (Polygonscan Cross-Checker for 0-vol wallets)
4. Worker 4: Leaderboard Discovery Sync (Daily 3 AM UTC Leaderboard & Hibernation Sync)
"""

import asyncio
import logging
import signal
import sys
import traceback

from src.workers.positions_winrate_backfill import run_positions_winrate_backfill
from src.workers.capital_metrics_backfill import run_capital_metrics_backfill
from src.workers.onchain_verifier import run_onchain_verifier
from src.workers.poly_leaderboard_sync import main as poly_leaderboard_sync_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")


async def supervise_task(task_func, name: str, shutdown_event: asyncio.Event):
    backoff = 1.0
    max_backoff = 60.0

    while not shutdown_event.is_set():
        logger.info(f"[{name}] Starting worker...")
        try:
            await task_func()

            if not shutdown_event.is_set():
                logger.warning(f"[{name}] Exited cleanly unexpectedly. Restarting in {backoff}s...")
                await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            logger.info(f"[{name}] Cancelled via shutdown.")
            break
        except Exception as e:
            logger.error(f"[{name}] CRASHED: {e}")
            logger.debug(traceback.format_exc())

            if not shutdown_event.is_set():
                logger.info(f"[{name}] Restarting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            else:
                break
        else:
            backoff = 1.0


async def main():
    logger.info("=== INITIALIZING ORCHESTRATOR (4 SPECIALIZED WORKERS) ===")
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    workers = [
        (run_positions_winrate_backfill, "Worker 1: Polymarket REST Sync & 10-Window PnLs"),
        (run_capital_metrics_backfill,  "Worker 2: Alchemy Capital Metrics"),
        (run_onchain_verifier,          "Worker 3: Polygonscan On-Chain Verifier"),
        (poly_leaderboard_sync_main,     "Worker 4: Leaderboard Discovery Sync"),
    ]

    tasks = []
    for func, name in workers:
        t = asyncio.create_task(supervise_task(func, name, shutdown_event), name=name)
        tasks.append(t)

    logger.info(f"All {len(tasks)} specialized workers supervised and running.")

    await shutdown_event.wait()

    logger.info("Waiting for workers to wind down (up to 10s)...")
    done, pending = await asyncio.wait(tasks, timeout=10)
    for t in pending:
        t.cancel()
    logger.info("Orchestrator shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
