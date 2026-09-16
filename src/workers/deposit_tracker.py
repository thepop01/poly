"""
Deposit Tracker Worker

Monitors the Polygon blockchain for large pUSD mint events.
- Deposits >= $5k → add to wallets_v2 (source='deposit')
- Deposits >= $5k with 0 trades → set might_cook_type='deposit_no_trades' badge
"""
import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timezone
from src.utils.alchemy_client import alchemy_get_asset_transfers, PUSD_CONTRACT
from src.utils.etherscan_client import get_latest_block_etherscan

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
MIN_DEPOSIT = 5_000

POLL_INTERVAL = 60
LAST_BLOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", ".deposit_last_block")
INITIAL_LOOKBACK_BLOCKS = int(os.environ.get("DEPOSIT_INITIAL_LOOKBACK_BLOCKS", "10000"))
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SYSTEM_RECIPIENTS = {
    ZERO_ADDRESS,
    PUSD_CONTRACT.lower(),
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xe2222d279d744050d28e00520010520000310f59",
    "0xe3333700ca9d93003f00f0f71f8515005f6c00aa",
}


def _parse_block_ts(ts_raw) -> datetime:
    """Parse Alchemy blockTimestamp — may be hex string, int, or None."""
    if isinstance(ts_raw, str) and ts_raw.startswith("0x"):
        return datetime.fromtimestamp(int(ts_raw, 16), tz=timezone.utc)
    if isinstance(ts_raw, (int, float)) and ts_raw > 0:
        return datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
    return datetime.now(timezone.utc)


def read_last_block() -> int | None:
    if os.path.exists(LAST_BLOCK_FILE):
        try:
            return int(open(LAST_BLOCK_FILE, "r").read().strip())
        except (OSError, ValueError):
            return None
    return None


def write_last_block(block_number: int):
    with open(LAST_BLOCK_FILE, "w") as f:
        f.write(str(block_number))


async def fetch_onramp_wraps(session: aiohttp.ClientSession, last_block: int | None = None) -> list[dict]:
    """
    Fetch all large pUSD mints TO users.
    These are the current Polymarket deposit signal: pUSD is minted from
    the zero address directly to the user's proxy wallet.
    Returns deposits with to, value, hash, blockNum, and timestamp.

    When last_block is set, ONLY returns transfers from blocks STRICTLY
    GREATER than last_block (new since last poll). Transfers from blocks
    <= last_block are skipped entirely, and pagination stops as soon as
    an entire page is below the boundary.
    """
    transfers = []
    page_key = None

    try:
        while True:
            params: dict = {
                "from_address": ZERO_ADDRESS,
                "contract_addresses": [PUSD_CONTRACT],
                "max_count": 1000,
                "page_key": page_key,
                "order": "desc",
                "with_metadata": True,
            }

            result = await alchemy_get_asset_transfers(session, **params)
            chunk = result.get("transfers", [])

            # No more results on this page â€” we're done
            if not chunk:
                break

            # Track whether every transfer on this page is stale (<= last_block).
            # Since results are in descending block order, if the FIRST item
            # is stale, the entire page is stale and we can bail entirely.
            first_blk = int(chunk[0].get("blockNum", "0x0"), 16) if isinstance(chunk[0].get("blockNum"), str) else 0
            if last_block is not None and first_blk <= last_block:
                break  # All remaining pages will be even older

            for t in chunk:
                val = t.get("value", 0) or 0
                blk = int(t.get("blockNum", "0x0"), 16) if isinstance(t.get("blockNum"), str) else 0
                to_addr = (t.get("to") or "").lower()

                # Skip individual transfers we've already seen
                if last_block is not None and blk <= last_block:
                    continue

                if val >= MIN_DEPOSIT and to_addr and to_addr not in SYSTEM_RECIPIENTS:
                    ts_str = None
                    if t.get("metadata"):
                        ts_str = t["metadata"].get("blockTimestamp")

                    transfers.append({
                        "from": to_addr,  # The user proxy wallet receiving minted pUSD
                        "value": val,
                        "hash": t.get("hash", ""),
                        "blockNum": blk,
                        "timestamp": _parse_block_ts(ts_str),
                    })

            page_key = result.get("pageKey")
            if not page_key:
                break
    except Exception as e:
        logger.warning(f"Error fetching onramp wraps: {e}")

    return transfers


async def check_trade_count(session: aiohttp.ClientSession, address: str) -> int:
    """Check how many trades a wallet has on Polymarket."""
    try:
        url = f"https://data-api.polymarket.com/trades?user={address}&limit=1"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and len(data) > 0:
                    # Has trades — check total by fetching with higher limit
                    url2 = f"https://data-api.polymarket.com/trades?user={address}&limit=100"
                    async with session.get(url2, timeout=aiohttp.ClientTimeout(total=8)) as resp2:
                        if resp2.status == 200:
                            data2 = await resp2.json()
                            return len(data2) if isinstance(data2, list) else 0
                return 0
    except Exception:
        pass
    return 0


async def add_to_global(conn: asyncpg.Connection, address: str):
    """Add wallet to wallets_v2 and wallet_sources_v2 if not already tracked.

    Never touches last_trade_at — a deposit is not a trade; only the
    trade-based workers may stamp it.
    """
    exists = await conn.fetchval(
        "SELECT address FROM wallets_v2 WHERE address = $1", address
    )
    if exists:
        await conn.execute(
            """
            UPDATE wallets_v2
            SET is_dormant = FALSE,
                updated_at = NOW()
            WHERE address = $1
            """,
            address
        )
        return 2
    else:
        await conn.execute("""
            INSERT INTO wallets_v2 (address, tier, tier_reason, is_dormant, added_at)
            VALUES ($1, 'NEW', 'deposit >= $5k', FALSE, NOW())
            ON CONFLICT (address) DO NOTHING
        """, address)
        
        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, 'deposit', 'large deposit >= $5k', NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address)
        logger.info(f"New wallet from large deposit: {address[:10]}...")
        return 1


async def run_deposit_tracker(pool: asyncpg.Pool | None = None):
    logger.info("Starting Deposit Tracker Worker...")
    last_block = read_last_block()

    own_pool = False
    if pool is None:
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)
        own_pool = True

    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            while True:
                try:
                    async with pool.acquire() as conn:
                        latest_block = int(await get_latest_block_etherscan(session) or 0)
                        if latest_block > 0:
                            if last_block is None or (latest_block - last_block > 200):
                                logger.info(f"Deposit tracker anchoring to live tip (last block {last_block}, tip {latest_block}).")
                                last_block = latest_block - 200
                        elif last_block is None:
                            logger.warning("Deposit tracker could not fetch latest block tip and has no cached last_block. Retrying in 10s...")
                            await asyncio.sleep(10)
                            continue

                        transfers = await fetch_onramp_wraps(session, last_block)

                        if transfers:
                            highest_block = max(t["blockNum"] for t in transfers)
                            if last_block is None or highest_block > last_block:
                                last_block = highest_block
                                write_last_block(last_block)

                            logger.info(f"Found {len(transfers)} large pUSD deposits (>${MIN_DEPOSIT:,}).")

                            new_deposits = 0
                            for tx in transfers:
                                addr = tx["from"]
                                if not addr:
                                    continue

                                # Queue the wallet FIRST — wallet_activity_v2 has an
                                # FK to wallets_v2, so the row must exist before any
                                # activity insert for a brand-new address.
                                await conn.execute("""
                                    INSERT INTO wallets_v2 (address, username, tier, is_dormant, added_at)
                                    VALUES ($1, '', 'UNCLASSIFIED', FALSE, NOW())
                                    ON CONFLICT (address) DO UPDATE SET updated_at = NOW()
                                """, addr)

                                await conn.execute("""
                                    INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
                                    VALUES ($1, 'deposit', 'pUSD deposit', NOW())
                                    ON CONFLICT (address, source) DO NOTHING
                                """, addr)

                                exists = await conn.fetchval("SELECT id FROM wallet_activity_v2 WHERE tx_hash = $1 AND event_type = 'DEPOSIT'", tx["hash"])
                                if not exists:
                                    await conn.execute("""
                                        INSERT INTO wallet_activity_v2 (address, event_type, amount_usdc, tx_hash, event_at, created_at)
                                        VALUES ($1, 'DEPOSIT', $2, $3, $4, NOW())
                                    """, addr, tx["value"], tx["hash"], tx["timestamp"])
                                    new_deposits += 1

                                # Deposit >= $5k → add to global list
                                track_count = await add_to_global(conn, addr)
                                if track_count > 1:
                                    logger.info(f"Wallet re-detected: {addr[:10]}... | deposit ${tx['value']:,.0f}")

                            logger.info(f"Globally recorded {new_deposits} new deposits. Queued {len(transfers)} wallets for evaluation.")
                        else:
                            latest_block = int(await get_latest_block_etherscan(session) or 0)
                            if latest_block > last_block:
                                last_block = latest_block
                                write_last_block(last_block)
                except Exception as e:
                    logger.error(f"Deposit Tracker Error: {e}")

                await asyncio.sleep(POLL_INTERVAL)
    finally:
        if own_pool and pool:
            await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_deposit_tracker())
