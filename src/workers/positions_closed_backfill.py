# src/workers/positions_closed_backfill.py
"""
Worker 2: Closed Positions Backfill
===================================
Fetches closed positions from API and stores in wallet_closed_positions_v2.
Retries failed API batches up to 3 times to prevent silent truncation.
Only marks closed_synced_at when the full fetch completes successfully.
Does NOT compute metrics — that's Worker 3 (positions_metrics_compute).
"""

import asyncio
import json
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

from src.workers.wallet_trade_history import fetch_closed_positions, fetch_combo_activity
from src.utils.polymarket_rate_limit import PostgresRateLimiter
from src.workers.market_metadata import upsert_position_markets
from src.pnl.invariants import check_row_invariants

logger = logging.getLogger("positions_closed_backfill")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
# Keep spare pooled connections because each in-flight wallet can acquire a
# second connection for the shared PostgreSQL API-rate limiter.
CONCURRENCY = int(os.getenv("POSITIONS_CLOSED_CONCURRENCY", "100"))
STALE_AFTER_HOURS = int(os.getenv("POSITIONS_CLOSED_STALE_AFTER_HOURS", "48"))
BATCH_SIZE = int(os.getenv("POSITIONS_CLOSED_BATCH_SIZE", "1000"))
WALLET_TIMEOUT = 1800


def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_realized_pnl(cp: dict) -> float:
    return _parse(cp.get("realized_pnl") if "realized_pnl" in cp else cp.get("realizedPnl"))


def _parse_ts(val) -> Optional[datetime]:
    if not val:
        return None
    try:
        if isinstance(val, (int, float)):
            if val > 86400:
                return datetime.fromtimestamp(val, tz=timezone.utc)
        elif isinstance(val, str):
            cleaned = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        pass
    return None


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


def _parse_token_id(value) -> str | None:
    """Raw ERC-1155 token id string or None (never float: precision loss)."""
    text = str(value or "").strip()
    if not text:
        return None
    return text if text.isdigit() else None


async def upsert_position_with_quarantine(conn: asyncpg.Connection, row: dict) -> str:
    """Upsert a position row after checking invariants. Quarantine if invariants fail.

    Args:
        conn: asyncpg connection
        row: position row dict with required fields

    Returns:
        "quarantined" if invariants failed, "ok" if upserted successfully
    """
    failures, warnings = check_row_invariants(row)
    if warnings:
        logging.getLogger("data_quality").warning(
            "Soft invariant: wallet=%s condition=%s warnings=%s",
            row.get("address"), row.get("condition_id"),
            [f"{w.rule}:{w.actual}" for w in warnings],
        )
    if failures:
        reasons = "; ".join(f"{f.rule}: expected {f.expected}, got {f.actual}" for f in failures)
        await conn.execute(
            """INSERT INTO position_quarantine
               (address, condition_id, outcome, status, failure_reason, raw_row)
               VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING""",
            row.get("address"), row.get("condition_id"), row.get("outcome"),
            row.get("status"), reasons, json.dumps(row),
        )
        return "quarantined"
    # For now, return "ok" — actual upsert logic would go here if integrated into workflow
    return "ok"


async def upsert_closed_positions_v2(conn: asyncpg.Connection, address: str, closed_positions: list[dict]):
    if not closed_positions:
        return 0
    rows = []
    for cp in closed_positions:
        cid = cp.get("conditionId") or ""
        outcome = cp.get("outcome") or cp.get("asset", "")
        if not cid:
            continue
        closed_at = _parse_end(cp.get("endDate")) or _parse_ts(cp.get("timestamp")) or datetime.now(tz=timezone.utc)
        rows.append((
            address, cid, outcome,
            _parse(cp.get("avgPrice")), _parse(cp.get("avgSellPrice")),
            _parse(cp.get("totalBought")), _parse(cp.get("totalSold")),
            _parse_realized_pnl(cp), closed_at,
            _is_parlay(cp), str(cp.get("asset") or "") or None,
            _parse_token_id(cp.get("asset")),
        ))
    if not rows:
        return 0

    await conn.executemany("""
        INSERT INTO wallet_closed_positions_v2 (
            address, condition_id, outcome, avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, closed_at, is_parlay, source_asset, asset_token_id
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            avg_buy_price=EXCLUDED.avg_buy_price,
            avg_sell_price=EXCLUDED.avg_sell_price,
            total_bought=EXCLUDED.total_bought,
            total_sold=EXCLUDED.total_sold,
            realized_pnl=EXCLUDED.realized_pnl,
            closed_at=COALESCE(wallet_closed_positions_v2.closed_at, EXCLUDED.closed_at),
            is_parlay=EXCLUDED.is_parlay,
            source_asset=COALESCE(EXCLUDED.source_asset, wallet_closed_positions_v2.source_asset),
            asset_token_id=COALESCE(EXCLUDED.asset_token_id, wallet_closed_positions_v2.asset_token_id),
            is_redeemable=FALSE,
            resolved_at=COALESCE(wallet_closed_positions_v2.resolved_at, EXCLUDED.closed_at)
    """, rows)
    return len(rows)


async def process_wallet_closed(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
):
    existing_keys = {
        (r["condition_id"], r["outcome"])
        for r in await conn.fetch(
            "SELECT condition_id, outcome FROM wallet_closed_positions_v2 WHERE address = $1", address
        )
    }

    result = await fetch_closed_positions(
        session, address, existing_keys=existing_keys, rate_limiter=rate_limiter
    )
    if not isinstance(result, tuple):
        logger.warning(f"fetch_closed_positions failed for {address[:12]}... — skipping")
        return
    closed_positions, is_complete = result

    upserted = await upsert_closed_positions_v2(conn, address, closed_positions)

    # Same market-metadata persistence as the open worker: closed payloads
    # carry title/eventSlug, and unlinked condition_ids otherwise land in OTHER.
    try:
        await upsert_position_markets(conn, closed_positions)
    except Exception as e:
        logger.warning(f"Market metadata upsert failed for {address[:12]}...: {e}")

    if is_complete:
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, closed_synced_at)
            VALUES ($1, NOW())
            ON CONFLICT (address) DO UPDATE SET closed_synced_at = NOW()
        """, address)
    else:
        logger.warning(f"Incomplete fetch for {address[:12]}... — NOT marking closed_synced_at")

    logger.info(
        f"Done {address[:12]}... | new_stored={upserted} (existing={len(existing_keys)}) complete={is_complete}"
    )
    sys.stdout.flush()


async def main_loop(db_url: str = DB_URL):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logger.info(f"=== CLOSED POSITIONS BACKFILLER STARTED (CONCURRENCY={CONCURRENCY}) ===")

    pool = await asyncpg.create_pool(DB_URL, min_size=16, max_size=max(140, CONCURRENCY + 40))
    rate_limiter = PostgresRateLimiter(pool)
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 6,
        limit_per_host=CONCURRENCY * 4,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=15, connect=4, sock_read=8),
    ) as session:
        while True:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT w.address
                        FROM wallets_v2 w
                        LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
                        WHERE (
                              m.closed_synced_at IS NULL
                              OR m.closed_synced_at < NOW() - make_interval(hours => $1)
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
                        LIMIT $2
                    """, STALE_AFTER_HOURS, BATCH_SIZE)
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

                        if (done + errors) % 10 == 0 or (done + errors) == total:
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
