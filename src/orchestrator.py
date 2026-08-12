# src/orchestrator.py
"""
Robust Master Worker Orchestrator
=================================
Supervises all background workers and services in a single managed process:
1. Worker 1: Positions & Win-Rate Sync (Polymarket REST API + 10-Window PnLs)
2. Worker 2: Capital Metrics Worker (Alchemy RPC USDC Deposits, Peak Capital, ROI %)
3. Worker 3: On-Chain Verifier (Polygonscan Cross-Checker for 0-vol wallets)
4. Worker 4: Leaderboard Discovery Sync (Weekly Monday 2 PM UTC Sync)
5. Stats Refresher: 12-Hour Active Wallet Staleness Refresher
6. Trade Tracker: Real-Time EVM Log Trade Stream (Every 15s)
7. Redemption Tracker: Real-Time Payout Redemptions Stream (Continuous)
8. Deposit Tracker: On-ramp Whale Deposit Alerts (Every 60s)
9. Wallet Discovery: Unclassified Candidate Vetting Gate (Every 60s)

Automatically restarts any crashed worker with exponential backoff.
"""

import asyncio
import logging
import os
import signal
import sys
import traceback
import asyncpg

from src.workers.positions_winrate_backfill import run_positions_winrate_backfill
from src.workers.capital_metrics_backfill import run_capital_metrics_backfill
from src.workers.onchain_verifier import run_onchain_verifier
from src.workers.poly_leaderboard_sync import main as poly_leaderboard_sync_main
from src.workers.stats_refresher import run_stats_refresher
from src.workers.trade_tracker import run_trade_tracker
from src.workers.redemption_tracker import run_redemption_tracker
from src.workers.deposit_tracker import run_deposit_tracker
from src.workers.wallet_trade_history import run_discovery

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")


async def _wrapped_trade_tracker():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    try:
        await run_trade_tracker(pool)
    finally:
        await pool.close()


async def _wrapped_redemption_tracker():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    try:
        await run_redemption_tracker(pool)
    finally:
        await pool.close()


async def _wrapped_discovery():
    while True:
        await run_discovery()
        await asyncio.sleep(60)


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
    logger.info("=== INITIALIZING MASTER ORCHESTRATOR (9 BACKGROUND WORKERS) ===")
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
        (run_stats_refresher,           "Worker 5: Stats Refresher (12h Staleness)"),
        (_wrapped_trade_tracker,        "Worker 6: Real-Time Trade Stream Tracker"),
        (_wrapped_redemption_tracker,   "Worker 7: Real-Time Payout Redemption Tracker"),
        (run_deposit_tracker,           "Worker 8: On-Ramp Whale Deposit Tracker"),
        (_wrapped_discovery,            "Worker 9: Wallet Discovery Vetting Gate"),
    ]

    tasks = []
    for func, name in workers:
        t = asyncio.create_task(supervise_task(func, name, shutdown_event), name=name)
        tasks.append(t)

    logger.info(f"All {len(tasks)} background workers supervised and running.")

    await shutdown_event.wait()

    logger.info("Waiting for workers to wind down (up to 10s)...")
    done, pending = await asyncio.wait(tasks, timeout=10)
    for t in pending:
        t.cancel()
    logger.info("Orchestrator shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
