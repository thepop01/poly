"""
High-Performance Polymarket Trade Backfiller Worker.

Fetches up to 3,500 trades per wallet directly from the Polymarket Data API
and populates wallet_trades_v2 and curated_trade_sync in PostgreSQL.

Usage:
  python src/workers/polymarket_trade_backfiller.py                   # Run on all wallets
  python src/workers/polymarket_trade_backfiller.py --wallet 0x...     # Single wallet
  python src/workers/polymarket_trade_backfiller.py --limit-wallets 50 # Batch of 50
"""

import asyncio
import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime, timezone
import aiohttp
import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [trade_backfiller] %(message)s"
)
logger = logging.getLogger("trade_backfiller")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
PM_DATA_API = "https://data-api.polymarket.com"

TRADES_PER_PAGE = 500
MAX_OFFSET = 1000            # Two 500-row pages: offsets 0 and 500
MAX_TRADES_PER_WALLET = 600  # Retain the newest 600 CLOB trades per wallet
CONCURRENCY = 8            # Parallel wallet worker tasks
GLOBAL_RATE_LIMIT_RPS = 15 # Max HTTP requests per second


def _parse_float(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


class RateLimiter:
    """Sliding window rate limiter."""
    def __init__(self, max_per_second: int = GLOBAL_RATE_LIMIT_RPS):
        self.interval = 1.0 / max_per_second
        self.last_time = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_time
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self.last_time = asyncio.get_event_loop().time()


rate_limiter = RateLimiter()


async def fetch_wallet_trades(session: aiohttp.ClientSession, address: str) -> tuple[list[dict], bool]:
    """Fetch newest trades for a wallet from Polymarket Data API.

    Retention rule: max 500 trades per wallet (newest first).

    Returns (trades, fetch_ok). fetch_ok is False when a page request failed
    after retries — callers must NOT treat the result as complete history.
    """
    all_trades = []
    seen_txs = set()
    offset = 0
    fetch_ok = True

    while offset < MAX_OFFSET:
        url = f"{PM_DATA_API}/trades?user={address}&limit={TRADES_PER_PAGE}&offset={offset}"
        data = None
        page_failed = False

        for attempt in range(3):
            await rate_limiter.acquire()
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 429:
                        wait = 3 * (attempt + 1)
                        logger.warning(f"Rate limited on {address[:10]}... offset={offset}, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    elif resp.status == 400:
                        # Reached API offset limit — legitimate end of data
                        data = []
                        break
                    elif resp.status != 200:
                        logger.warning(f"HTTP {resp.status} on {address[:10]}... offset={offset} (attempt {attempt + 1}/3)")
                        if attempt < 2:
                            await asyncio.sleep(1)
                            continue
                        page_failed = True
                        break
                    data = await resp.json()
                    break
            except Exception as e:
                logger.warning(f"Fetch error on {address[:10]}... offset={offset} (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(1)

        if page_failed:
            fetch_ok = False
            break

        for t in data:
            tx = t.get("transactionHash") or t.get("txHash") or ""
            unique_key = (tx, t.get("asset"), t.get("timestamp"))
            if unique_key not in seen_txs:
                seen_txs.add(unique_key)
                all_trades.append(t)

        if len(data) < TRADES_PER_PAGE:
            break

        offset += TRADES_PER_PAGE
        if len(all_trades) >= MAX_TRADES_PER_WALLET:
            break

    return all_trades[:MAX_TRADES_PER_WALLET], fetch_ok


async def insert_wallet_trades(conn: asyncpg.Connection, address: str, trades: list[dict]) -> int:
    """Batch insert trades into wallet_trades_v2."""
    if not trades:
        return 0

    records = []
    max_ts = 0

    for idx, t in enumerate(trades):
        tx_hash = t.get("transactionHash") or t.get("txHash") or f"pm_{address}_{idx}"
        log_idx = int(t.get("logIndex") or idx)
        condition_id = t.get("conditionId") or t.get("asset_id")
        outcome = str(t.get("outcome") or "YES")
        side = str(t.get("side") or "TRADE").upper()
        price = _parse_float(t.get("price"))
        size = _parse_float(t.get("size"))
        amount_usdc = _parse_float(t.get("amount") or (price * size))
        market_name = str(t.get("title") or t.get("question") or f"Polymarket Trade")
        category = t.get("category") or "Trading"
        subcategory = t.get("subcategory")
        
        ts = int(t.get("timestamp") or 0)
        if ts > max_ts:
            max_ts = ts

        dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts > 0 else datetime.now(timezone.utc)

        records.append((
            tx_hash,
            log_idx,
            address.lower(),
            condition_id,
            outcome,
            side,
            price,
            size,
            amount_usdc,
            dt,
            market_name,
            category,
            subcategory,
            0 # block_number
        ))

    # Check if wallet is lineage — route to separate table
    is_lineage = await conn.fetchval("""
        SELECT TRUE FROM wallets_v2
        WHERE address = $1 AND (
            funding_source IN ('internal_funded', 'inherited_positions')
            OR COALESCE(transferred_positions_count, 0) > 0
            OR funded_by IS NOT NULL
        )
    """, address.lower())

    if is_lineage:
        # This table also stores transfers/funding, so preserve its required
        # lineage fields while retaining the full CLOB trade payload.
        await conn.executemany("""
            INSERT INTO wallet_lineage_trades_v2 (
                wallet_address, event_type, amount, amount_usd,
                condition_id, outcome, tx_hash, block_number, event_at,
                log_index, side, price, size, amount_usdc, traded_at,
                market_name, category, subcategory
            ) VALUES (
                $3, 'TRADE', $8, $9, $4, $5, $1, $14, $10,
                $2, $6, $7, $8, $9, $10, $11, $12, $13
            ) ON CONFLICT DO NOTHING
        """, records)
    else:
        await conn.executemany("""
            INSERT INTO wallet_trades_v2 (
            tx_hash, log_index, wallet_address, condition_id,
            outcome, side, price, size, amount_usdc,
            traded_at, market_name, category, subcategory, block_number
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (tx_hash, log_index) DO NOTHING
        """, records)

    # Retain only the newest 600 normal-wallet CLOB trades.  Lineage history
    # is accounting evidence and is intentionally retained without a cap.
    if not is_lineage:
        await conn.execute("""
            WITH ranked AS (
                SELECT ctid, ROW_NUMBER() OVER (PARTITION BY wallet_address ORDER BY traded_at DESC) AS rn
                FROM wallet_trades_v2 WHERE wallet_address = $1
            )
            DELETE FROM wallet_trades_v2 WHERE ctid IN (
                SELECT ctid FROM ranked WHERE rn > $2
            )
        """, address.lower(), MAX_TRADES_PER_WALLET)

    # Update last trade timestamp and classify in wallets_v2
    if max_ts > 0:
        last_trade_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc)
        tot_vol = sum(float(t.get("usd_volume") or (float(t.get("size", 0)) * float(t.get("price", 0)))) for t in trades)
        await conn.execute("""
            UPDATE wallets_v2 
            SET last_trade_at = GREATEST(COALESCE(last_trade_at, $2), $2),
                tier = CASE 
                    WHEN tier = 'UNCLASSIFIED' AND $3 >= 1000 THEN 'STANDARD'
                    WHEN tier = 'UNCLASSIFIED' THEN 'LOW_BALANCE'
                    ELSE tier
                END,
                tier_reason = CASE
                    WHEN tier = 'UNCLASSIFIED' AND $3 >= 1000 THEN 'backfill: vol >= $1k'
                    WHEN tier = 'UNCLASSIFIED' THEN 'backfill: low balance'
                    ELSE tier_reason
                END,
                is_dormant = CASE 
                    WHEN GREATEST(COALESCE(last_trade_at, $2), $2) < NOW() - INTERVAL '30 days' THEN TRUE 
                    ELSE FALSE 
                END,
                updated_at = NOW()
            WHERE address = $1
        """, address.lower(), last_trade_dt, tot_vol)
    else:
        # If no trades returned from API
        await conn.execute("""
            UPDATE wallets_v2 
            SET tier = CASE WHEN tier = 'UNCLASSIFIED' THEN 'NEW' ELSE tier END,
                tier_reason = CASE WHEN tier = 'UNCLASSIFIED' THEN 'backfill: 0 trades' ELSE tier_reason END,
                updated_at = NOW()
            WHERE address = $1
        """, address.lower())

    return len(records)


async def process_wallet(conn_pool: asyncpg.Pool, session: aiohttp.ClientSession, address: str, stats: dict):
    """Worker task to process a single wallet."""
    addr = address.lower().strip()
    try:
        trades, fetch_ok = await fetch_wallet_trades(session, addr)
        async with conn_pool.acquire() as conn:
            inserted = await insert_wallet_trades(conn, addr, trades)

            if not fetch_ok:
                # Fetch failed after retries — do NOT mark as synced so the
                # wallet is retried on the next run. Partial data is kept
                # (insert is idempotent), but completion is not recorded.
                stats["wallets_failed"] = stats.get("wallets_failed", 0) + 1
                logger.error(f"Fetch FAILED for {addr[:10]}... — kept {inserted} partial trades, NOT marking synced (will retry)")
                return

            # Record completion in curated_trade_sync
            await conn.execute("""
                INSERT INTO curated_trade_sync (wallet_address, last_synced_block, updated_at)
                VALUES ($1, 1, NOW())
                ON CONFLICT (wallet_address) DO UPDATE SET updated_at = NOW()
            """, addr)

        stats["wallets_done"] += 1
        stats["trades_inserted"] += inserted

        if inserted > 0 or stats["wallets_done"] % 20 == 0:
            rate = stats["trades_inserted"] / max(1.0, time.time() - stats["start_time"])
            w_rate = stats["wallets_done"] / max(1.0, time.time() - stats["start_time"])
            logger.info(f"[{stats['wallets_done']:,}/{stats['total_wallets']:,}] {addr[:10]}... | +{inserted:,} trades | Avg: {rate:.1f} trades/s ({w_rate:.1f} wallets/s)")

    except Exception as e:
        logger.error(f"Error processing {addr[:10]}...: {e}")


async def run_backfill(single_wallet: str = None, limit_wallets: int = None):
    start_time = time.time()
    logger.info("=======================================================")
    logger.info("POLYMARKET DATA API TRADE BACKFILLER")
    logger.info(f"Concurrency       : {CONCURRENCY} workers")
    logger.info(f"Max Trades/Wallet : {MAX_TRADES_PER_WALLET:,}")
    logger.info("=======================================================")

    pool = await asyncpg.create_pool(DB_URL, min_size=4, max_size=CONCURRENCY + 4)

    try:
        # Select target wallets
        async with pool.acquire() as conn:
            if single_wallet:
                wallets = [single_wallet.lower().strip()]
            else:
                query = """
                    SELECT w.address 
                    FROM wallets_v2 w
                    LEFT JOIN curated_trade_sync s ON w.address = s.wallet_address
                    WHERE s.wallet_address IS NULL
                      AND w.is_dormant = FALSE
                      AND w.tier != 'DEAD'
                    ORDER BY 
                        CASE 
                            WHEN w.tier = 'CURATED' THEN 1
                            WHEN w.tier = 'STANDARD' THEN 2
                            WHEN w.tier = 'NEW' THEN 3
                            WHEN w.tier = 'LOW_BALANCE' THEN 4
                            ELSE 5
                        END ASC,
                        w.added_at DESC
                """
                if limit_wallets:
                    query += f" LIMIT {limit_wallets}"
                rows = await conn.fetch(query)
                wallets = [r["address"] for r in rows]

        logger.info(f"Found {len(wallets):,} wallets queued for trade backfill.")
        if not wallets:
            logger.info("All wallets already synced! Nothing to do.")
            return

        stats = {
            "wallets_done": 0,
            "wallets_failed": 0,
            "trades_inserted": 0,
            "total_wallets": len(wallets),
            "start_time": time.time()
        }

        # Queue tasks with concurrency semaphore
        sem = asyncio.Semaphore(CONCURRENCY)

        async def sem_worker(session, addr):
            async with sem:
                await process_wallet(pool, session, addr, stats)

        headers = {"User-Agent": "PolymarketBackfiller/2.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [asyncio.create_task(sem_worker(session, addr)) for addr in wallets]
            await asyncio.gather(*tasks)

        elapsed = time.time() - start_time
        logger.info("=======================================================")
        logger.info("BACKFILL RUN COMPLETE")
        logger.info(f"Total Wallets Processed: {stats['wallets_done']:,}")
        logger.info(f"Wallets FAILED (retry) : {stats['wallets_failed']:,}")
        logger.info(f"Total Trades Inserted  : {stats['trades_inserted']:,}")
        logger.info(f"Elapsed Time           : {elapsed:.2f}s ({stats['trades_inserted']/max(1.0, elapsed):.1f} trades/s)")

        logger.info("=======================================================")

    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket Trade Backfiller")
    parser.add_argument("--wallet", type=str, help="Single wallet address")
    parser.add_argument("--limit-wallets", type=int, help="Max number of wallets to process")
    args = parser.parse_args()

    asyncio.run(run_backfill(single_wallet=args.wallet, limit_wallets=args.limit_wallets))
