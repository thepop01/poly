"""
Global Discovery Worker

Monitors the Polygon blockchain for any massive deposits (Wraps)
into Polymarket's CollateralOnramp contract.
Globally records EVERY on-chain deposit >= $10k into wallet_deposits,
regardless of whether the wallet is tracked.
"""
import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timezone
from src.utils.alchemy_client import alchemy_get_asset_transfers, USDC_CONTRACT, COLLATERAL_ONRAMP

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
MIN_DEPOSIT = 10_000


async def fetch_onramp_wraps(session: aiohttp.ClientSession, last_block: int | None = None) -> list[dict]:
    """
    Fetch all pUSD transfers FROM the CollateralOnramp TO users.
    These are guaranteed to be Polymarket deposits (wraps).
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
                "to_address": COLLATERAL_ONRAMP,
                "contract_addresses": [USDC_CONTRACT],
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

                # Skip individual transfers we've already seen
                if last_block is not None and blk <= last_block:
                    continue

                if val >= MIN_DEPOSIT:
                    ts_str = None
                    if t.get("metadata"):
                        ts_str = t["metadata"].get("blockTimestamp")

                    transfers.append({
                        "from": t.get("from", ""),  # The user who deposited
                        "value": val,
                        "hash": t.get("hash", ""),
                        "blockNum": blk,
                        "timestamp": ts_str,
                    })

            page_key = result.get("pageKey")
            if not page_key:
                break
    except Exception as e:
        logger.warning(f"Error fetching onramp wraps: {e}")

    return transfers


async def run_global_discovery():
    logger.info("Starting Global Discovery Worker...")
    last_block = None

    while True:
        try:
            conn = await asyncpg.connect(DB_URL)
            try:
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:

                    if last_block is None:
                        transfers = await fetch_onramp_wraps(session)
                    else:
                        transfers = await fetch_onramp_wraps(session, last_block)

                    if transfers:
                        highest_block = max(t["blockNum"] for t in transfers)
                        if last_block is None or highest_block > last_block:
                            last_block = highest_block

                        logger.info(f"Found {len(transfers)} large pUSD deposits (>$10k).")

                        new_deposits = 0
                        for tx in transfers:
                            addr = tx["from"]
                            if not addr:
                                continue

                            if tx["hash"]:
                                if tx.get("timestamp"):
                                    ts = tx["timestamp"]
                                    if ts.endswith("Z"):
                                        ts = ts[:-1] + "+00:00"
                                    deposited_at = ts
                                    res = await conn.execute("""
                                        INSERT INTO wallet_deposits (wallet_address, tx_hash, amount_usdc, deposited_at, flagged_single, alerted)
                                        VALUES ($1, $2, $3, $4::timestamptz, TRUE, TRUE)
                                        ON CONFLICT (tx_hash) DO NOTHING
                                    """, addr, tx["hash"], tx["value"], deposited_at)
                                else:
                                    res = await conn.execute("""
                                        INSERT INTO wallet_deposits (wallet_address, tx_hash, amount_usdc, deposited_at, flagged_single, alerted)
                                        VALUES ($1, $2, $3, NOW(), TRUE, TRUE)
                                        ON CONFLICT (tx_hash) DO NOTHING
                                    """, addr, tx["hash"], tx["value"])

                                if res == "INSERT 0 1":
                                    new_deposits += 1

                            await conn.execute("""
                                INSERT INTO wallet_discovery_queue (address, spotted_at, processed, source)
                                VALUES ($1, NOW(), FALSE, 'Huge Deposit')
                                ON CONFLICT (address) DO UPDATE SET
                                    processed = FALSE,
                                    source = CASE WHEN wallet_discovery_queue.source = 'Unknown' THEN 'Huge Deposit' ELSE wallet_discovery_queue.source END
                            """, addr)

                            if tx["hash"]:
                                await conn.execute("""
                                    INSERT INTO smart_money_alerts (address, alert_type, amount_usdc, transaction_hash, created_at)
                                    VALUES ($1, 'LARGE_DEPOSIT', $2, $3, EXTRACT(EPOCH FROM NOW()))
                                    ON CONFLICT (transaction_hash) DO NOTHING
                                """, addr, tx["value"], tx["hash"])

                        logger.info(f"Globally recorded {new_deposits} new deposits. Queued {len(transfers)} wallets for evaluation.")
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Global Discovery Error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_global_discovery())

