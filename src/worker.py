"""
Gamma API Polling Worker — Phase 1 Ingestion.

Continuously polls the Polymarket Gamma API for events and markets,
upserting them into the local Postgres database.

Usage:
    python -m src.worker
"""

import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

from src.db import get_pool, init_db, close_pool
from src.gamma_client import fetch_active_events, ParsedEvent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("worker")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))

# --- SQL Statements ---

UPSERT_EVENT = """
INSERT INTO events (event_id, slug, title, category, status, created_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (event_id) DO UPDATE SET
    title    = EXCLUDED.title,
    category = EXCLUDED.category,
    status   = EXCLUDED.status,
    fetched_at = NOW()
"""

UPSERT_MARKET = """
INSERT INTO markets (
    market_id, event_id, token_id, slug, title, outcome_label,
    status, enable_order_book, current_price, total_volume,
    liquidity, created_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
ON CONFLICT (market_id) DO UPDATE SET
    title            = EXCLUDED.title,
    status           = EXCLUDED.status,
    enable_order_book = EXCLUDED.enable_order_book,
    current_price    = EXCLUDED.current_price,
    total_volume     = EXCLUDED.total_volume,
    liquidity        = EXCLUDED.liquidity,
    last_updated     = NOW(),
    fetched_at       = NOW()
"""


async def upsert_event_and_markets(pool, event: ParsedEvent) -> int:
    """Upsert one event and all its markets. Returns count of markets upserted."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                UPSERT_EVENT,
                event.event_id,
                event.slug,
                event.title,
                event.category,
                event.status,
                event.created_at,
            )
            for mkt in event.markets:
                await conn.execute(
                    UPSERT_MARKET,
                    mkt.market_id,
                    mkt.event_id,
                    mkt.token_id,
                    mkt.slug,
                    mkt.title,
                    mkt.outcome_label,
                    mkt.status,
                    mkt.enable_order_book,
                    mkt.current_price,
                    mkt.total_volume,
                    mkt.liquidity,
                    mkt.created_at,
                )
    return len(event.markets)


async def run_poll_cycle(pool) -> None:
    """Execute one full poll-parse-upsert cycle."""
    events = await fetch_active_events()
    total_markets = 0
    for event in events:
        try:
            n = await upsert_event_and_markets(pool, event)
            total_markets += n
        except Exception:
            logger.exception("Failed to upsert event %s", event.event_id)
    logger.info(
        "Poll cycle complete: %d events, %d markets upserted",
        len(events),
        total_markets,
    )


async def main() -> None:
    """Entry point: init DB, then poll in a loop."""
    logger.info("Starting Gamma polling worker (interval=%ds)", POLL_INTERVAL)

    pool = await get_pool()
    await init_db(pool)
    logger.info("Database schema applied successfully")

    shutdown = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM
            pass

    try:
        while not shutdown.is_set():
            try:
                await run_poll_cycle(pool)
            except Exception:
                logger.exception("Error in poll cycle")
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass  # Normal — timeout means poll again
    finally:
        await close_pool()
        logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
