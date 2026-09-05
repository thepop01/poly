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

from src.db import DATABASE_URL as DB_URL, DB_SSL_CONFIG
from src.workers.positions_open_backfill import main_loop as run_positions_open_backfill
from src.workers.positions_closed_backfill import main_loop as run_positions_closed_backfill
from src.workers.positions_metrics_compute import main_loop as run_positions_metrics_compute
from src.workers.onchain_verifier import run_onchain_verifier
from src.workers.poly_leaderboard_sync import main as poly_leaderboard_sync_main
from src.workers.stats_refresher import run_stats_refresher
from src.workers.trade_tracker import run_trade_tracker
from src.workers.redemption_tracker import run_redemption_tracker
from src.workers.deposit_tracker import run_deposit_tracker
from src.workers.wallet_trade_history import run_discovery
from src.workers.last_trade_sweeper import run_last_trade_sweeper
from src.workers.live_wallet_listener import run_live_listener
from src.workers.polymarket_trade_backfiller import run_backfill as run_polymarket_trade_backfill
from src.workers.position_and_funding_tracker import run_tracker_loop as run_position_and_funding_tracker
from src.workers.activity_backfiller_worker import run_loop as run_activity_backfiller
from src.workers.activity_analyzer_worker import run_loop as run_activity_analyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")


async def _wrapped_trade_tracker():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5, ssl=DB_SSL_CONFIG)
    try:
        await run_trade_tracker(pool)
    finally:
        await pool.close()


async def _wrapped_redemption_tracker():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5, ssl=DB_SSL_CONFIG)
    try:
        await run_redemption_tracker(pool)
    finally:
        await pool.close()


async def _wrapped_discovery():
    while True:
        await run_discovery()
        await asyncio.sleep(60)


import time

WORKER_HEARTBEATS: dict[str, float] = {}

def touch_heartbeat(name: str) -> None:
    """Record heartbeat for a worker to inform watchdog of active progress."""
    WORKER_HEARTBEATS[name] = time.time()


async def supervise_task(task_func, name: str, shutdown_event: asyncio.Event):
    backoff = 1.0
    max_backoff = 60.0

    while not shutdown_event.is_set():
        touch_heartbeat(name)
        logger.info(f"[{name}] Starting worker...")
        
        # Periodic ticker to keep heartbeat alive as long as task_func is healthy and progressing
        async def _ticker():
            while not shutdown_event.is_set():
                await asyncio.sleep(60)
                touch_heartbeat(name)

        ticker_task = asyncio.create_task(_ticker())
        try:
            await task_func()

            touch_heartbeat(name)
            if not shutdown_event.is_set():
                logger.info(f"[{name}] Cycle completed cleanly. Restarting next cycle in {backoff}s...")
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
        finally:
            ticker_task.cancel()
            try:
                await ticker_task
            except (asyncio.CancelledError, Exception):
                pass


async def watchdog_monitor(
    shutdown_event: asyncio.Event,
    worker_tasks: dict[str, asyncio.Task],
    worker_funcs: dict[str, callable],
):
    """Master Watchdog: Scans all active workers every 30s. If any worker task has died or stalled > 6 mins without progress, restarts it."""
    while not shutdown_event.is_set():
        await asyncio.sleep(30)
        now = time.time()
        for name, last_active in list(WORKER_HEARTBEATS.items()):
            task = worker_tasks.get(name)
            is_dead = task is not None and task.done()
            is_stalled = (now - last_active > 360)

            if is_dead or is_stalled:
                reason = "task ended unexpectedly" if is_dead else f"silent for {int(now - last_active)}s"
                logger.error(f"[WATCHDOG ALERT] Worker '{name}' {reason}! Triggering self-healing restart...")
                if task and not task.done():
                    logger.info(f"[WATCHDOG] Cancelling stale supervise_task for '{name}'...")
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                func = worker_funcs.get(name)
                if func is not None and not shutdown_event.is_set():
                    new_task = asyncio.create_task(supervise_task(func, name, shutdown_event), name=name)
                    worker_tasks[name] = new_task
                    logger.info(f"[WATCHDOG] Respawning worker '{name}'...")
                touch_heartbeat(name)


async def main():
    logger.info("=== INITIALIZING MASTER ORCHESTRATOR WITH SELF-HEALING WATCHDOG (12 BACKGROUND WORKERS) ===")
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
        (run_positions_open_backfill,      "Worker 1: Open Positions & Portfolio Syncer"),
        (run_positions_closed_backfill,    "Worker 2: Closed Positions Incremental Fetcher"),
        (run_positions_metrics_compute,    "Worker 3: Offline Win Rate & Metrics Computer"),
        (poly_leaderboard_sync_main,       "Worker 4: Leaderboard Discovery Sync"),
        (run_stats_refresher,              "Worker 5: Stats Refresher (12h Staleness)"),
        (_wrapped_trade_tracker,           "Worker 6: Real-Time Trade Stream Tracker"),
        (_wrapped_redemption_tracker,      "Worker 7: Real-Time Payout Redemption Tracker"),
        (run_deposit_tracker,              "Worker 8: On-Ramp Whale Deposit Tracker"),
        (_wrapped_discovery,               "Worker 9: Wallet Discovery Vetting Gate"),
        (run_last_trade_sweeper,           "Worker 10: Last Trade Activity Sweeper"),
        (run_live_listener,                "Worker 11: Live Real-Time Wallet Creation Listener"),
        (run_polymarket_trade_backfill,    "Worker 12: Polymarket Trade Backfiller (3.5k trades)"),
        (run_position_and_funding_tracker, "Worker 13: P2P Transfer & Internal Funding Tracker"),
        (run_onchain_verifier,             "Worker 14: Polygonscan On-Chain Verifier"),
        (run_activity_backfiller,          "Worker 15 / 3: Activity Snapshot Backfiller"),
        (run_activity_analyzer,            "Worker 16 / 4: Activity Snapshot Analyzer"),
    ]

    worker_funcs = {name: func for func, name in workers}
    worker_tasks: dict[str, asyncio.Task] = {}

    watchdog_task = asyncio.create_task(
        watchdog_monitor(shutdown_event, worker_tasks, worker_funcs), name="WatchdogMonitor"
    )
    tasks = [watchdog_task]
    for _, name in workers:
        t = asyncio.create_task(supervise_task(worker_funcs[name], name, shutdown_event), name=name)
        worker_tasks[name] = t
        tasks.append(t)

    logger.info(f"All {len(workers)} background workers supervised + Watchdog running.")

    await shutdown_event.wait()

    logger.info("Waiting for workers to wind down (up to 10s)...")
    done, pending = await asyncio.wait(tasks, timeout=10)
    for t in pending:
        t.cancel()
    logger.info("Orchestrator shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
