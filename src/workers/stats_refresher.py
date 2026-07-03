import asyncio
import asyncpg
import aiohttp
import os
import signal
import logging
from datetime import datetime, timezone, timedelta

from src.workers.wallet_discovery import fetch_positions, _parse
from src.utils.alchemy_client import (
    fetch_usdc_deposits,
    fetch_usdc_withdrawals,
    alchemy_get_token_balances,
    USDC_CONTRACT,
)

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

REFRESH_STALE_AFTER_HOURS = 1
BATCH_SIZE = 100
POLL_INTERVAL = 600  # run every 10 minutes

async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    try:
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance for {address}: {e}")
    return 0.0

async def refresh_tracked_wallets(conn: asyncpg.Connection, session: aiohttp.ClientSession):
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=REFRESH_STALE_AFTER_HOURS)
    rows = await conn.fetch(
        "SELECT address FROM tracked_wallets WHERE last_indexed < $1 ORDER BY last_indexed ASC LIMIT $2",
        stale_cutoff, BATCH_SIZE,
    )
    if not rows:
        logger.info("No stale tracked wallets to refresh.")
        return

    wallets = [r["address"] for r in rows]
    logger.info(f"Refreshing {len(wallets)} stale tracked wallets...")
    refreshed = 0

    for address in wallets:
        try:
            deposits = await fetch_usdc_deposits(session, address)
            withdrawals = await fetch_usdc_withdrawals(session, address)

            if deposits is None or withdrawals is None:
                logger.warning(f"Skipping {address[:10]}... — could not fetch deposits/withdrawals")
                continue

            positions = await fetch_positions(session, address)
            balance = await fetch_balance(session, address)

            # Compute position_value from open positions
            position_value = 0.0
            for pos in (positions or []):
                curr_val = _parse(pos.get("currentValue"))
                if curr_val > 0:
                    position_value += curr_val

            await conn.execute("""
                UPDATE tracked_wallets SET
                    balance          = $2,
                    deposits         = $3,
                    withdrawals      = $4,
                    position_value   = $5,
                    last_indexed     = NOW()
                WHERE address = $1
            """, address, balance, deposits, withdrawals, position_value)

            refreshed += 1
            logger.info(f"Refreshed {address[:10]}... | pos_val={position_value:.0f} bal={balance:.0f}")
        except Exception as e:
            logger.warning(f"Error refreshing {address[:10]}...: {e}")

        await asyncio.sleep(0.5)

    logger.info(f"Refreshed {refreshed}/{len(wallets)} wallets.")

async def run_stats_refresher(db_url: str = DB_URL):
    logger.info("Starting Stats Refresher worker...")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return

    while True:
        try:
            async with pool.acquire() as conn:
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    await refresh_tracked_wallets(conn, session)
        except Exception as e:
            logger.error(f"Stats refresher error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

async def main():
    shutdown = asyncio.Event()

    def _handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except NotImplementedError:
            pass

    logger.info(f"Starting Stats Refresher (interval={POLL_INTERVAL}s)")
    while not shutdown.is_set():
        try:
            await run_stats_refresher()
        except Exception:
            logger.exception("Error in stats refresher loop")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass

    logger.info("Stats Refresher shut down cleanly")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
