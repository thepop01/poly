"""
Robust Worker Orchestrator.

Supervises all background workers and bots. If a worker crashes, it is automatically
restarted with exponential backoff.
"""

import asyncio
import logging
import signal
import sys
import traceback

from src.workers.trade_tracker import _standalone as trade_tracker_main
from src.workers.wallet_trade_history import main as wallet_trade_history_main
from src.workers.leaderboard_stats_v2 import run_leaderboard_stats_v2 as leaderboard_stats_main
from src.workers.deposit_tracker import run_deposit_tracker as deposit_tracker_main
from src.workers.stats_refresher import main as stats_refresher_main
from src.workers.poly_leaderboard_sync import main as poly_leaderboard_sync_main
from src.workers.agent_evaluator import main as agent_evaluator_main

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
        logger.info(f"[{name}] Starting...")
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


async def supervise_subprocess(module_name: str, name: str, shutdown_event: asyncio.Event):
    backoff = 1.0
    max_backoff = 60.0

    while not shutdown_event.is_set():
        logger.info(f"[{name}] Starting subprocess (python -m {module_name})...")
        try:
            proc = await asyncio.create_subprocess_exec(sys.executable, "-m", module_name)

            while not shutdown_event.is_set() and proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

            if shutdown_event.is_set():
                if proc.returncode is None:
                    logger.info(f"[{name}] Terminating subprocess...")
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[{name}] Subprocess did not terminate, killing...")
                        proc.kill()
                break

            if proc.returncode != 0:
                logger.error(f"[{name}] Subprocess crashed with exit code {proc.returncode}")
                logger.info(f"[{name}] Restarting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            else:
                logger.warning(f"[{name}] Subprocess exited cleanly unexpectedly. Restarting in {backoff}s...")
                await asyncio.sleep(backoff)

        except asyncio.CancelledError:
            logger.info(f"[{name}] Supervisor cancelled via shutdown.")
            break
        except Exception as e:
            logger.error(f"[{name}] Subprocess supervisor error: {e}")
            if not shutdown_event.is_set():
                await asyncio.sleep(backoff)


async def main():
    logger.info("Initializing Worker Orchestrator...")
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

    internal_workers = [
        (leaderboard_stats_main, "leaderboard_stats"),
        (trade_tracker_main, "trade_tracker"),
        (wallet_trade_history_main, "wallet_trade_history"),
        (deposit_tracker_main, "deposit_tracker"),
        (stats_refresher_main, "stats_refresher"),
        (poly_leaderboard_sync_main, "poly_leaderboard_sync"),
        (agent_evaluator_main, "agent_evaluator"),
    ]

    external_bots = [
    ]

    tasks = []

    for func, name in internal_workers:
        t = asyncio.create_task(supervise_task(func, name, shutdown_event), name=name)
        tasks.append(t)

    for module_name, name in external_bots:
        t = asyncio.create_task(supervise_subprocess(module_name, name, shutdown_event), name=name)
        tasks.append(t)

    logger.info(f"All {len(tasks)} workers supervised and running.")

    await shutdown_event.wait()

    logger.info("Waiting for tasks to wind down (up to 10s)...")
    done, pending = await asyncio.wait(tasks, timeout=10)
    for t in pending:
        t.cancel()

    logger.info("Orchestrator cleanly shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received at outer loop. Exiting.")
