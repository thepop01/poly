# src/workers/positions_winrate_backfill.py
"""
Hibernated Wallet Closed Positions Backfill
=============================================
Fetches closed positions from Polymarket API and upserts them into
wallet_closed_positions_v2. Also syncs redeemable open positions as closed.
Retries failed API batches to prevent silent truncation.
Only marks closed_synced_at when the full fetch completes successfully.

Does NOT compute win rate or write metrics — that's Worker 3 (positions_metrics_compute).
Does NOT touch open positions — that's Worker 2 (positions_open_backfill.py).
"""

import asyncio
import logging
import os
import sys
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

from datetime import datetime, timezone
import aiohttp
import asyncpg
from typing import Optional

from src.workers.wallet_trade_history import fetch_closed_positions, fetch_positions
from src.utils.category_classifier import classify_market
from src.utils.polymarket_rate_limit import PostgresRateLimiter

GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")

logger = logging.getLogger("positions_winrate_backfill")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
# Keep spare pooled connections because each in-flight wallet can acquire a
# second connection for the shared PostgreSQL API-rate limiter.
CONCURRENCY = 50
WALLET_TIMEOUT = 1800


def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


async def upsert_market_metadata_v2(conn: asyncpg.Connection, positions: list[dict]) -> None:
    """Persist exact Data API event slugs and fill only missing/OTHER taxonomy."""
    markets: dict[str, tuple] = {}
    for position in positions:
        condition_id = str(position.get("conditionId") or "")
        if not condition_id:
            continue
        title = str(position.get("title") or "")
        event_slug = str(position.get("eventSlug") or "")
        category, subcategory, league = classify_market(title, event_slug)
        markets[condition_id] = (
            condition_id, title, category, subcategory, league, event_slug
        )
    if not markets:
        return

    await conn.executemany("""
        INSERT INTO markets_v2 (
            condition_id, title, category, subcategory, league, event_slug, status, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', NOW())
        ON CONFLICT (condition_id) DO UPDATE SET
            title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
            event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug),
            category = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.category ELSE markets_v2.category END,
            subcategory = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.subcategory ELSE markets_v2.subcategory END,
            league = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.league ELSE markets_v2.league END,
            updated_at = NOW()
    """, list(markets.values()))


def _parse_realized_pnl(cp: dict) -> float:
    return _parse(cp.get("realized_pnl") if "realized_pnl" in cp else cp.get("realizedPnl"))


def _parse_end(dt_str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        now = datetime.now(tz=timezone.utc)
        if isinstance(dt_str, (int, float)):
            if dt_str <= 86400:
                return None
            dt = datetime.fromtimestamp(dt_str, tz=timezone.utc)
        else:
            cleaned = str(dt_str).replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        if dt.year <= 1970:
            return None
        if dt > now:
            return None
        return dt
    except Exception:
        return None


def _is_parlay(pos: dict) -> bool:
    if pos.get("isCombo") is True or pos.get("is_parlay") is True or pos.get("is_combo") is True:
        return True
    title = str(pos.get("title") or "")
    upper = title.upper()
    if "COMBO" in upper or "PARLAY" in upper:
        return True
    return False


async def sync_redeemable_positions(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    positions: list[dict],
    closed_keys: set[tuple[str, str]],
) -> int:
    """Find open positions with redeemable=True and write them into wallet_closed_positions_v2."""
    redeemable_positions = []
    for p in positions:
        cid = p.get("conditionId")
        outcome = p.get("outcome") or p.get("asset", "")
        asset = p.get("asset", "")
        if not cid:
            continue
        if (cid, outcome) in closed_keys or (cid, asset) in closed_keys:
            continue
        if not p.get("redeemable", False):
            continue
        redeemable_positions.append(p)

    if not redeemable_positions:
        return 0

    rows = []
    for p in redeemable_positions:
        cid = p.get("conditionId") or ""
        outcome = p.get("outcome") or p.get("asset", "")
        if not cid:
            continue
        realized_pnl = _parse(p.get("realizedPnl"))
        cur_val = _parse(p.get("currentValue"))
        avg_price = _parse(p.get("avgPrice"))
        size_val = _parse(p.get("size"))
        bought_val = _parse(p.get("totalBought"))

        # Determine actual cash outlay on CLOB
        actual_bought = bought_val if bought_val > 0 else 0.0
        recorded_cash_cost = actual_bought * avg_price if (avg_price > 0 and actual_bought > 0) else 0.0
        initial_value = _parse(p.get("initialValue"))
        if initial_value > 0 and recorded_cash_cost > 0:
            remaining_cost = min(initial_value, recorded_cash_cost)
        else:
            remaining_cost = recorded_cash_cost

        quality_flag = None
        if bought_val == 0 and size_val > 0:
            quality_flag = "minted_shares"
        elif size_val > bought_val * 1.5 and bought_val > 0:
            quality_flag = "mixed_minted_shares"
        elif avg_price <= 0:
            quality_flag = "missing_avg_price"

        total_pnl = realized_pnl + cur_val - remaining_cost
        is_win = total_pnl > 0

        closed_at = _parse_end(p.get("endDate")) or datetime.now(tz=timezone.utc)

        rows.append((
            address, cid, outcome,
            avg_price,
            1.0 if is_win else 0.0,
            actual_bought,
            0.0,
            total_pnl,
            closed_at,
            _is_parlay(p),
            True,
            closed_at,
            quality_flag,
            str(p.get("asset") or "") or None,
        ))

    if not rows:
        return 0

    await upsert_market_metadata_v2(conn, redeemable_positions)

    await conn.executemany("""
        INSERT INTO wallet_closed_positions_v2 (
            address, condition_id, outcome, avg_buy_price, avg_sell_price,
            total_bought, total_sold, realized_pnl, closed_at, is_parlay,
            is_redeemable, resolved_at, data_quality_flag, source_asset
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            avg_buy_price=EXCLUDED.avg_buy_price,
            avg_sell_price=EXCLUDED.avg_sell_price,
            total_bought=EXCLUDED.total_bought,
            total_sold=EXCLUDED.total_sold,
            realized_pnl=EXCLUDED.realized_pnl,
            closed_at=COALESCE(wallet_closed_positions_v2.closed_at, EXCLUDED.closed_at),
            is_parlay=EXCLUDED.is_parlay,
            is_redeemable=EXCLUDED.is_redeemable,
            resolved_at=COALESCE(wallet_closed_positions_v2.resolved_at, EXCLUDED.resolved_at),
            data_quality_flag=EXCLUDED.data_quality_flag,
            source_asset=COALESCE(EXCLUDED.source_asset, wallet_closed_positions_v2.source_asset)
    """, rows)

    logger.info(f"Synced {len(rows)} redeemable open positions as closed for {address[:12]}...")
    return len(rows)


async def upsert_closed_positions_v2(conn: asyncpg.Connection, address: str, closed_positions: list[dict]):
    """Batch-upsert closed positions into wallet_closed_positions_v2."""
    if not closed_positions:
        return
    await upsert_market_metadata_v2(conn, closed_positions)
    rows = []
    for cp in closed_positions:
        cid = cp.get("conditionId") or ""
        outcome = cp.get("outcome") or cp.get("asset", "")
        if not cid:
            continue
        rows.append((
            address, cid, outcome,
            _parse(cp.get("avgPrice")), _parse(cp.get("avgSellPrice")),
            _parse(cp.get("totalBought")), _parse(cp.get("totalSold")),
            _parse(cp.get("realizedPnl")), _parse_end(cp.get("endDate")),
            _is_parlay(cp), str(cp.get("asset") or "") or None,
        ))
    if not rows:
        return

    await conn.executemany("""
        INSERT INTO wallet_closed_positions_v2 (
            address, condition_id, outcome, avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, closed_at, is_parlay, source_asset
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            avg_buy_price=EXCLUDED.avg_buy_price,
            avg_sell_price=EXCLUDED.avg_sell_price,
            total_bought=EXCLUDED.total_bought,
            total_sold=EXCLUDED.total_sold,
            realized_pnl=EXCLUDED.realized_pnl,
            closed_at=EXCLUDED.closed_at,
            is_parlay=EXCLUDED.is_parlay,
            source_asset=COALESCE(EXCLUDED.source_asset, wallet_closed_positions_v2.source_asset),
            is_redeemable=FALSE,
            resolved_at=COALESCE(wallet_closed_positions_v2.resolved_at, EXCLUDED.closed_at)
    """, rows)


async def process_wallet_closed(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
):
    """Fetch closed positions from API and upsert to DB. That's it."""
    positions_f, closed_f = await asyncio.gather(
        fetch_positions(session, address, rate_limiter=rate_limiter),
        fetch_closed_positions(session, address, rate_limiter=rate_limiter),
        return_exceptions=True,
    )

    if isinstance(positions_f, tuple):
        positions, positions_complete = positions_f
    elif isinstance(positions_f, list):
        positions, positions_complete = positions_f, True
    else:
        positions, positions_complete = [], False

    if isinstance(closed_f, tuple):
        closed_positions, closed_complete = closed_f
    elif isinstance(closed_f, list):
        closed_positions, closed_complete = closed_f, True
    else:
        closed_positions, closed_complete = [], False

    if isinstance(positions_f, Exception) and isinstance(closed_f, Exception):
        logger.warning(f"API failed for {address[:12]}... — skipping")
        return

    closed_keys = {
        (cp.get("conditionId"), cp.get("asset", ""))
        for cp in closed_positions
        if cp.get("conditionId")
    }

    synced_count = await sync_redeemable_positions(conn, session, address, positions, closed_keys)
    if synced_count > 0:
        closed_keys = {
            (cp.get("conditionId"), cp.get("asset", ""))
            for cp in closed_positions
            if cp.get("conditionId")
        }

    if positions_complete:
        redeem_keys = [
            (p.get("conditionId"), p.get("outcome") or p.get("asset", ""))
            for p in positions
            if p.get("redeemable", False) and p.get("conditionId")
        ]
        await conn.execute("""
            UPDATE wallet_closed_positions_v2 c
            SET is_redeemable = FALSE
            WHERE c.address = $1 AND c.is_redeemable
              AND (c.condition_id, c.outcome) NOT IN (
                  SELECT * FROM unnest($2::text[], $3::text[])
              )
        """, address, [k[0] for k in redeem_keys], [k[1] for k in redeem_keys])

    real_closed = [cp for cp in closed_positions if not cp.get("is_redeemable")]
    await upsert_closed_positions_v2(conn, address, real_closed)

    if closed_complete:
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, closed_synced_at)
            VALUES ($1, NOW())
            ON CONFLICT (address) DO UPDATE SET closed_synced_at = NOW()
        """, address)
    else:
        logger.warning(f"Incomplete closed fetch for {address[:12]}... — NOT marking closed_synced_at")

    max_db_trade = await conn.fetchval("""
        SELECT max(traded_at) FROM wallet_trades_v2
        WHERE wallet_address = $1 AND traded_at <= NOW()
    """, address)
    if max_db_trade:
        await conn.execute("""
            UPDATE wallets_v2
            SET last_trade_at = GREATEST(COALESCE(last_trade_at, $2), $2),
                is_dormant = CASE WHEN GREATEST(COALESCE(last_trade_at, $2), $2) < NOW() - INTERVAL '30 days' THEN TRUE ELSE FALSE END
            WHERE address = $1
        """, address, max_db_trade)

    logger.info(
        f"Done {address[:12]}... | closed={len(real_closed)} "
        f"redeemable_synced={synced_count}"
    )
    sys.stdout.flush()


async def main_loop(db_url: str = DB_URL):
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logger.info(f"=== CLOSED POSITIONS BACKFILLER STARTED (CONCURRENCY={CONCURRENCY}) ===")

    pool = await asyncpg.create_pool(DB_URL, min_size=12, max_size=80)
    rate_limiter = PostgresRateLimiter(pool)
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 6,
        limit_per_host=CONCURRENCY * 4,
        keepalive_timeout=20,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=12, connect=4, sock_read=8),
    ) as session:
        while True:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT w.address
                        FROM wallets_v2 w
                        LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
                        WHERE w.is_dormant = FALSE
                          AND (
                              m.closed_synced_at IS NULL
                              OR m.closed_synced_at < NOW() - INTERVAL '84 hours'
                          )
                        ORDER BY
                          CASE WHEN m.closed_synced_at IS NULL THEN 0 ELSE 1 END ASC,
                          CASE
                            WHEN w.tier IN ('CURATED', 'CUSTOM') THEN 0
                            WHEN w.tier = 'STANDARD' THEN 1
                            WHEN w.tier = 'NEW' THEN 2
                            WHEN w.tier = 'LOW_BALANCE' THEN 3
                            ELSE 4
                          END ASC,
                          COALESCE(m.closed_synced_at, '1970-01-01'::TIMESTAMPTZ) ASC
                        LIMIT 500
                    """)
                    wallets = [r["address"] for r in rows]
                    total = len(wallets)

                if total == 0:
                    logger.info("All active wallets fully backfilled (closed)! Sleeping for 60s...")
                    await asyncio.sleep(60)
                    continue

                done, errors = 0, 0
                t0 = time.time()

                async def _process_one(addr):
                    nonlocal done, errors
                    async with sem:
                        try:
                            async with pool.acquire() as conn:
                                await asyncio.wait_for(
                                    process_wallet_closed(conn, session, addr, rate_limiter),
                                    timeout=WALLET_TIMEOUT,
                                )
                            done += 1
                        except asyncio.TimeoutError:
                            errors += 1
                        except Exception as e:
                            errors += 1
                            logger.warning(f"Error {addr[:12]}...: {e}")

                        if (done + errors) % 5 == 0 or (done + errors) == total:
                            rate = (done + errors) / max(0.1, time.time() - t0)
                            logger.info(f"Progress: {done+errors}/{total} (ok={done} err={errors}) | Speed: {rate:.1f} wallets/s")

                await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)
                logger.info(f"=== BATCH COMPLETE: {done} ok, {errors} errors / {total} ===")
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error in backfill loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main_loop())
