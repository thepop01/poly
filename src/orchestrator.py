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

from src.workers.whale_watcher import _standalone as whale_watcher_main
from src.workers.deposit_watcher import run_deposit_watcher as deposit_watcher_main
from src.workers.wallet_discovery import main as discovery_queue_processor_main
from src.workers.leaderboard_stats import main as leaderboard_stats_main
from src.workers.global_discovery import run_global_discovery as global_discovery_main
from src.workers.stats_refresher import main as stats_refresher_main

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
        (whale_watcher_main, "whale_watcher"),
        (deposit_watcher_main, "deposit_watcher"),
        (discovery_queue_processor_main, "discovery_queue_processor"),
        (global_discovery_main, "global_discovery"),
        (stats_refresher_main, "stats_refresher"),
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
