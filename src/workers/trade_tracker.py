"""
Trade Tracker Worker

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
from src.utils.category_classifier import classify_tags

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
            INSERT INTO wallets_v2 (address, tier, is_dormant, added_at, updated_at, next_check_at, tier_reason)
            VALUES ($1, 'UNCLASSIFIED', FALSE, NOW(), NOW(), NOW(), 'trade_tracker')
            ON CONFLICT (address) DO UPDATE SET next_check_at = NOW()
        """, address.lower())
        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, 'trade', 'trade_tracker discovery queue', NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address.lower())



async def maybe_add_to_global(conn: asyncpg.Connection, address: str, trade_dt: datetime):
    """If whale trade >= $1k and wallet not yet tracked, add to wallets_v2.
    If already tracked, update last trade."""
    exists = await conn.fetchval(
        "SELECT address FROM wallets_v2 WHERE address = $1", address
    )
    if exists:
        await conn.execute(
            """
            UPDATE wallets_v2 
            SET is_dormant = FALSE,
                updated_at = NOW(),
                last_trade_at = GREATEST(last_trade_at, $2)
            WHERE address = $1
            """,
            address, trade_dt,
        )
        return 2  # Return >1 to signify existing
    else:
        # New wallet
        await conn.execute("""
            INSERT INTO wallets_v2 (address, tier, tier_reason, is_dormant, added_at, last_trade_at)
            VALUES ($1, 'NEW', 'whale trade >= $1k', FALSE, NOW(), $2)
            ON CONFLICT (address) DO NOTHING
        """, address, trade_dt)
        
        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, 'trade', 'whale trade >= $1k', NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address)
        logger.info(f"New wallet from whale trade: {address[:10]}... (trade at {trade_dt})")
        return 1



async def run_trade_tracker(pool: asyncpg.Pool):
    logger.info("Trade tracker started with 3-exchange monitoring and 12h accumulator.")
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
                            usd_value = float(trade.get("usd_volume", 0) or 0)
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
                                    exists = await conn.fetchval("SELECT id FROM wallet_activity_v2 WHERE tx_hash = $1 AND event_type = 'TRADE'", tx_hash)
                                    if not exists:
                                        if market_id:
                                            cat, sub = classify_tags([title]) if title else ("Other", "General")
                                            cat = category or cat
                                            sub = subcategory or sub
                                            await conn.execute("""
                                                INSERT INTO markets_v2 (condition_id, title, category, subcategory)
                                                VALUES ($1, $2, $3, $4)
                                                ON CONFLICT (condition_id) DO NOTHING
                                            """, market_id, title or f"Unknown Market ({market_id[:8]})", cat, sub)

                                        await conn.execute("""
                                            INSERT INTO wallet_activity_v2 (address, event_type, amount_usdc, tx_hash, condition_id, outcome, title, event_at, created_at)
                                            VALUES ($1, 'TRADE', $2, $3, $4, $5, $6, $7, NOW())
                                        """, wallet, usd_value, tx_hash, market_id, side, title, dt)
                                except Exception as e:
                                    logger.warning(f"Failed to insert smart money trade into activity v2: {e}")

                            is_instant_whale = usd_value >= LARGE_TRADE_THRESHOLD
                            is_accumulated_whale = total_12h_vol >= LARGE_TRADE_THRESHOLD

                            if is_instant_whale or is_accumulated_whale:
                                whale_wallets.append(wallet)
                                if is_accumulated_whale:
                                    _rolling_volumes[wallet][market_id].clear()

                            # Whale trade >= $1k → add to global list
                            if usd_value >= WHALE_TRADE_THRESHOLD:
                                try:
                                    track_count = await maybe_add_to_global(conn, wallet, dt)
                                    if track_count > 1:
                                        logger.info(f"Wallet re-detected: A{track_count} | {wallet[:10]}... | ${usd_value:,.0f}")
                                except Exception as e:
                                    logger.warning(f"Failed to add {wallet[:10]} to global: {e}")

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
                logger.error(f"Trade tracker error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


async def _standalone():
    pool = await asyncpg.create_pool(DB_URL)
    await run_trade_tracker(pool)
    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_standalone())
