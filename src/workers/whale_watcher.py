"""
Whale Watcher Worker

Monitors Polymarket's live trade feed (via polling the Etherscan API).
Aggregates fragmented orders by transactionHash.
Maintains a 12-hour rolling window to catch slow limit-order accumulations.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
import time
from datetime import datetime, timezone
from collections import defaultdict

from src.utils.etherscan_client import fetch_recent_trades_etherscan, get_latest_block_etherscan

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

WHALE_TRADE_THRESHOLD = 1_000
LARGE_TRADE_THRESHOLD = 5_000
POLL_INTERVAL = 15

LAST_BLOCK_FILE = ".whale_last_block"

_rolling_volumes = defaultdict(lambda: defaultdict(list))
ROLLING_WINDOW_SECS = 12 * 3600


def read_last_block():
    if os.path.exists(LAST_BLOCK_FILE):
        with open(LAST_BLOCK_FILE, "r") as f:
            return f.read().strip()
    return "latest"


def write_last_block(block_number: int):
    with open(LAST_BLOCK_FILE, "w") as f:
        f.write(str(block_number))


def clean_old_volumes(current_ts: int):
    cutoff = current_ts - ROLLING_WINDOW_SECS
    for wallet in list(_rolling_volumes.keys()):
        for market in list(_rolling_volumes[wallet].keys()):
            _rolling_volumes[wallet][market] = [t for t in _rolling_volumes[wallet][market] if t[0] >= cutoff]
            if not _rolling_volumes[wallet][market]:
                del _rolling_volumes[wallet][market]
        if not _rolling_volumes[wallet]:
            del _rolling_volumes[wallet]


async def add_to_discovery_queue(conn: asyncpg.Connection, addresses: list[str]):
    if not addresses:
        return
    for address in addresses:
        await conn.execute("""
            INSERT INTO wallet_discovery_queue (address, spotted_at, processed)
            VALUES ($1, NOW(), FALSE)
            ON CONFLICT (address) DO UPDATE
              SET processed = FALSE,
                  spotted_at = NOW()
            WHERE wallet_discovery_queue.processed = TRUE
        """, address.lower())


async def run_whale_watcher(pool: asyncpg.Pool):
    logger.info("Whale watcher started with 3-exchange monitoring and 12h accumulator.")
    last_block = read_last_block()

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        while True:
            try:
                trades = await fetch_recent_trades_etherscan(session, from_block=last_block, to_block="latest")

                if trades:
                    whale_wallets = []
                    highest_block = 0
                    current_ts = int(time.time())
                    clean_old_volumes(current_ts)

                    async with pool.acquire() as conn:
                        for trade in trades:
                            b_num = trade.get("blockNumber", 0)
                            if b_num > highest_block:
                                highest_block = b_num

                            wallet = trade.get("wallet", "").lower()
                            usd_value = float(trade.get("size", 0) or 0)
                            tx_hash = trade.get("transactionHash", "")
                            title = trade.get("title", "")
                            side = trade.get("side", "")
                            market_id = trade.get("market_id", "")
                            category = trade.get("category")
                            subcategory = trade.get("subcategory")
                            ts = trade.get("timestamp", 0)
                            dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)

                            if not wallet or usd_value <= 0:
                                continue

                            _rolling_volumes[wallet][market_id].append((ts, usd_value, tx_hash, side))
                            total_12h_vol = sum(t[1] for t in _rolling_volumes[wallet][market_id])

                            if usd_value >= WHALE_TRADE_THRESHOLD:
                                whale_wallets.append(wallet)
                                try:
                                    await conn.execute("""
                                        INSERT INTO smart_money_trades (wallet_address, tx_hash, market_name, side, amount_usdc, traded_at, category, subcategory)
                                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                        ON CONFLICT (tx_hash) DO NOTHING
                                    """, wallet, tx_hash, title, side, usd_value, dt, category, subcategory)
                                except Exception as e:
                                    logger.warning(f"Failed to insert smart money trade: {e}")

                            is_instant_whale = usd_value >= LARGE_TRADE_THRESHOLD
                            is_accumulated_whale = total_12h_vol >= LARGE_TRADE_THRESHOLD

                            if is_instant_whale or is_accumulated_whale:
                                whale_wallets.append(wallet)
                                alert_vol = usd_value if is_instant_whale else total_12h_vol
                                alert_side = side if is_instant_whale else f"{side} (ACCUMULATED)"

                                try:
                                    await conn.execute("""
                                        INSERT INTO smart_money_alerts
                                        (address, alert_type, amount_usdc, transaction_hash, market_id, market_title, side, created_at, category, subcategory)
                                        VALUES ($1, 'LARGE_TRADE', $2, $3, $4, $5, $6, $7, $8, $9)
                                        ON CONFLICT (transaction_hash) DO NOTHING
                                    """, wallet, alert_vol, tx_hash, market_id, title, alert_side, dt, category, subcategory)

                                    if is_accumulated_whale:
                                        _rolling_volumes[wallet][market_id].clear()

                                except Exception as e:
                                    logger.warning(f"Failed to insert smart money alert: {e}")

                    if whale_wallets:
                        whale_wallets = list(set(whale_wallets))
                        async with pool.acquire() as conn:
                            await add_to_discovery_queue(conn, whale_wallets)

                    if highest_block > 0:
                        last_block = str(highest_block + 1)
                        write_last_block(highest_block + 1)
                else:
                    current_tip = await get_latest_block_etherscan(session)
                    if current_tip and current_tip != "89410000":
                        last_block = current_tip
                        write_last_block(int(current_tip))

            except Exception as e:
                logger.error(f"Whale watcher error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


async def _standalone():
    pool = await asyncpg.create_pool(DB_URL)
    await run_whale_watcher(pool)
    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_standalone())
