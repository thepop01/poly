# src/workers/curated_trade_feed.py
"""Incremental per-wallet trade feed for curated wallets. Independent of the
win-rate pipeline — feeds a future trade-feed UI only."""
import logging
from datetime import datetime, timezone

import aiohttp
import asyncpg

from src.utils.etherscan_client import fetch_historical_trades_polygonscan

logger = logging.getLogger(__name__)


def trade_to_row(t: dict, log_index: int) -> dict:
    ts = t.get("timestamp")
    traded_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    return {
        "tx_hash": t.get("transactionHash") or "",
        "log_index": log_index,
        "wallet_address": (t.get("wallet") or "").lower(),
        "condition_id": t.get("conditionId") or t.get("market_id"),
        "outcome": t.get("outcome"),
        "side": t.get("side"),
        "price": float(t.get("price") or 0),
        "size": float(t.get("size") or 0),
        "amount_usdc": float(t.get("usd_volume") or 0),
        "traded_at": traded_at,
        "market_name": t.get("title"),
        "category": t.get("category"),
        "subcategory": t.get("subcategory"),
        "block_number": t.get("blockNumber"),
    }


async def sync_wallet_trades(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Fetch new fills for one curated wallet since its cursor, upsert, advance."""
    address = address.lower()
    cursor = await conn.fetchval(
        "SELECT last_synced_block FROM curated_trade_sync WHERE wallet_address = $1",
        address,
    )
    start_block = (cursor + 1) if cursor else 0
    trades = await fetch_historical_trades_polygonscan(session, [address], start_block=start_block)
    if not trades:
        return 0
    max_block = 0
    inserted = 0
    # log_index is not returned by the parser; synthesize a stable per-tx index
    # by ordering fills within a tx. Two fills sharing (tx_hash) get 0,1,2...
    seen_tx: dict[str, int] = {}
    for t in sorted(trades, key=lambda x: (x.get("transactionHash") or "", x.get("blockNumber") or 0)):
        txh = t.get("transactionHash") or ""
        idx = seen_tx.get(txh, 0)
        seen_tx[txh] = idx + 1
        row = trade_to_row(t, idx)
        if not row["tx_hash"] or row["wallet_address"] != address:
            continue
        await conn.execute(
            """
            INSERT INTO curated_trades
                (tx_hash, log_index, wallet_address, condition_id, outcome, side,
                 price, size, amount_usdc, traded_at, market_name, category,
                 subcategory, block_number)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (tx_hash, log_index) DO NOTHING
            """,
            row["tx_hash"], row["log_index"], row["wallet_address"], row["condition_id"],
            row["outcome"], row["side"], row["price"], row["size"], row["amount_usdc"],
            row["traded_at"], row["market_name"], row["category"], row["subcategory"],
            row["block_number"],
        )
        inserted += 1
        max_block = max(max_block, int(row["block_number"] or 0))
    await conn.execute(
        """
        INSERT INTO curated_trade_sync (wallet_address, last_synced_block, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (wallet_address) DO UPDATE SET
            last_synced_block = GREATEST(curated_trade_sync.last_synced_block, EXCLUDED.last_synced_block),
            updated_at = NOW()
        """,
        address, max_block,
    )
    return inserted
