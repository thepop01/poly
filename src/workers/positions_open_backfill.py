# src/workers/positions_open_backfill.py
"""
Worker 1: Open Positions Backfill
===================================
Fetches open positions, detects concluded-but-not-redeemed positions,
syncs redeemable positions as closed, upserts open positions, and
updates open-related metrics in wallet_metrics_v2.
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

from src.workers.wallet_trade_history import fetch_positions, fetch_portfolio_value
from src.utils.category_classifier import classify_tags, flatten_subcategory
from src.utils.polymarket_rate_limit import PostgresRateLimiter
from src.workers.market_metadata import upsert_position_markets
from src.pnl.invariants import check_row_invariants

logger = logging.getLogger("positions_open_backfill")

V2_EPOCH = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _should_apply_legacy_repair(fetched_at: datetime | None) -> bool:
    return fetched_at is not None and fetched_at < V2_EPOCH


def _log_repair_fired(rule_name: str, row: dict) -> None:
    import logging
    logging.getLogger("data_quality").warning(
        "Legacy repair rule fired: rule=%s wallet=%s condition=%s",
        rule_name, row.get("address"), row.get("condition_id"),
    )

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
# Keep spare pooled connections because each in-flight wallet can acquire a
# second connection for the shared PostgreSQL API-rate limiter.
CONCURRENCY = int(os.getenv("POSITIONS_OPEN_CONCURRENCY", "100"))
STALE_AFTER_HOURS = int(os.getenv("POSITIONS_OPEN_STALE_AFTER_HOURS", "48"))
BATCH_SIZE = int(os.getenv("POSITIONS_OPEN_BATCH_SIZE", "1000"))
WALLET_TIMEOUT = 1800

GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")


def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


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
    """Return the raw ERC-1155 token id string, or None.

    Kept as a string: 77-digit ids lose precision as float64, and the
    NUMERIC column adapts exact decimal strings without loss.
    """
    text = str(value or "").strip()
    if not text:
        return None
    return text if text.isdigit() else None


async def sync_redeemable_positions(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    positions: list[dict],
    closed_keys: set[tuple[str, str]],
) -> int:
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
        # initialValue is the cost basis still held after partial sells. Cap it
        # by recorded CLOB spend because minted/converted shares can make the
        # API-reported size and initialValue much larger than totalBought.
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


async def aggregate_and_upsert_positions_v2(conn: asyncpg.Connection, address: str, open_positions: list[dict]):
    if not open_positions:
        return
    rows = []
    for p in open_positions:
        cid = p.get("conditionId") or ""
        outcome = p.get("outcome") or p.get("asset", "")
        if not cid:
            continue
        cur_val = _parse(p.get("currentValue"))
        size_val = _parse(p.get("size"))
        avg_price = _parse(p.get("avgPrice"))
        cost_basis = size_val * avg_price if (size_val > 0 and avg_price > 0) else _parse(p.get("initialValue"))
        pos_pnl = cur_val - cost_basis
        rows.append((
            address, cid, outcome,
            size_val, avg_price,
            cur_val, pos_pnl,
            _is_parlay(p),
            bool(p.get("redeemable", False)),
            _parse_token_id(p.get("asset")),
        ))
    if not rows:
        return

    await conn.executemany("""
        INSERT INTO wallet_positions_v2 (
            address, condition_id, outcome, size, avg_price, current_value, unrealized_pnl, is_parlay, is_resolved, asset_token_id, entry_at, computed_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, NOW(), NOW())
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            size=EXCLUDED.size,
            avg_price=EXCLUDED.avg_price,
            current_value=EXCLUDED.current_value,
            unrealized_pnl=EXCLUDED.unrealized_pnl,
            is_parlay=EXCLUDED.is_parlay,
            is_resolved=EXCLUDED.is_resolved,
            asset_token_id=COALESCE(EXCLUDED.asset_token_id, wallet_positions_v2.asset_token_id),
            entry_at=COALESCE(wallet_positions_v2.entry_at, EXCLUDED.entry_at),
            computed_at=NOW()
    """, rows)


async def prune_stale_open_positions_v2(conn: asyncpg.Connection, address: str, open_positions: list[dict]):
    if not open_positions:
        return 0
    keys = []
    for p in open_positions:
        cid = p.get("conditionId") or ""
        outcome = p.get("outcome") or p.get("asset", "")
        if cid:
            keys.append((cid, outcome))
    if not keys:
        return 0

    tag = await conn.execute("""
        DELETE FROM wallet_positions_v2
        WHERE address = $1
          AND (condition_id, outcome) NOT IN (
              SELECT * FROM unnest($2::text[], $3::text[])
          )
    """, address, [k[0] for k in keys], [k[1] for k in keys])
    deleted = int(tag.split()[-1]) if tag and tag.split()[-1].isdigit() else 0
    if deleted:
        logger.info(f"Pruned {deleted} stale open positions for {address[:12]}...")
    return deleted


async def process_wallet_open(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
):
    positions_f, port_val_f = await asyncio.gather(
        fetch_positions(session, address, rate_limiter=rate_limiter),
        fetch_portfolio_value(session, address),
        return_exceptions=True,
    )

    if isinstance(positions_f, tuple):
        positions, positions_complete = positions_f
    elif isinstance(positions_f, list):
        positions, positions_complete = positions_f, True
    else:
        positions, positions_complete = [], False
    portfolio_val = port_val_f if isinstance(port_val_f, (int, float)) else 0.0

    if isinstance(positions_f, Exception):
        logger.warning(f"fetch_positions failed for {address[:12]}... — skipping, will retry")
        return

    # /value returns marked-to-market PORTFOLIO value, not cash. Writing it to
    # `balance` made balance a duplicate of position_value for 90k wallets and
    # double-counted open value in every equity formula. Preserve whatever a
    # genuine cash source wrote; never synthesise it from portfolio value.
    # This source worker owns open-position evidence only.  Capital sync owns
    # balance; preserve it instead of overwriting it with a position snapshot.
    existing_balance = await conn.fetchval(
        "SELECT balance FROM wallet_metrics_v2 WHERE address = $1", address
    )

    pos_val = sum(_parse(p.get("currentValue", 0)) for p in positions)
    unrealised = sum(
        _parse(p.get("currentValue", 0)) - _parse(p.get("initialValue", 0))
        for p in positions
    )

    existing_closed_keys = {
        (row["condition_id"], row["outcome"])
        for row in await conn.fetch(
            "SELECT condition_id, outcome FROM wallet_closed_positions_v2 WHERE address = $1", address
        )
    }

    redeemable_count = 0
    redeemable_winning_count = 0
    for p in positions:
        if p.get("redeemable", False):
            cid = p.get("conditionId")
            asset = p.get("asset", "")
            if cid and (cid, asset) not in existing_closed_keys:
                redeemable_count += 1
                if _parse(p.get("currentValue")) > 0:
                    redeemable_winning_count += 1

    synced_count = await sync_redeemable_positions(conn, session, address, positions, existing_closed_keys)
    if synced_count > 0:
        existing_closed_keys = {
            (row["condition_id"], row["outcome"])
            for row in await conn.fetch(
                "SELECT condition_id, outcome FROM wallet_closed_positions_v2 WHERE address = $1", address
            )
        }

    parlay_open = [p for p in positions if _is_parlay(p)]
    parlay_open_count = len(parlay_open) if parlay_open else 0
    parlay_open_value = sum(_parse(p.get("currentValue", 0)) for p in parlay_open) if parlay_open else 0.0

    await aggregate_and_upsert_positions_v2(conn, address, positions)
    # Persist market metadata seen in this sync (title/eventSlug are already
    # in the payload: zero extra API calls). Without this, positions whose
    # condition_id has no markets_v2 row collapse into OTHER downstream.
    try:
        await upsert_position_markets(conn, positions)
    except Exception as e:
        logger.warning(f"Market metadata upsert failed for {address[:12]}...: {e}")
    if positions_complete and len(positions) < 200000:
        if not positions:
            # Complete fetch with zero open positions: the wallet fully exited.
            # Without this, stale rows would linger forever and inflate
            # position_value / parlay_open metrics.
            tag = await conn.execute(
                "DELETE FROM wallet_positions_v2 WHERE address = $1", address
            )
            deleted = int(tag.split()[-1]) if tag and tag.split()[-1].isdigit() else 0
            if deleted:
                logger.info(f"Wallet {address[:12]}... fully exited — pruned {deleted} stale open position rows")
        else:
            await prune_stale_open_positions_v2(conn, address, positions)

    existing = await conn.fetchrow(
        "SELECT win_rate, resolved_count, winning_count, total_volume, total_pnl, roi_pct, avg_buy_price FROM wallet_metrics_v2 WHERE address = $1", address
    )

    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, position_value,
            parlay_open_count, parlay_open_value,
            redeemable_count, redeemable_winning_count,
            open_synced_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $7 THEN NOW() ELSE NULL END)
        ON CONFLICT (address) DO UPDATE SET
            position_value=EXCLUDED.position_value,
            parlay_open_count=EXCLUDED.parlay_open_count,
            parlay_open_value=EXCLUDED.parlay_open_value,
            redeemable_count=EXCLUDED.redeemable_count,
            redeemable_winning_count=EXCLUDED.redeemable_winning_count,
            open_synced_at=CASE WHEN $7 THEN NOW() ELSE wallet_metrics_v2.open_synced_at END
    """, address, pos_val, parlay_open_count, parlay_open_value,
         redeemable_count, redeemable_winning_count, positions_complete)

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
    else:
        await conn.execute("""
            UPDATE wallets_v2
            SET is_dormant = CASE
                WHEN last_trade_at IS NOT NULL AND last_trade_at < NOW() - INTERVAL '30 days' THEN TRUE
                ELSE FALSE
            END
            WHERE address = $1
        """, address)

    logger.info(
        f"Done {address[:12]}... | open={len(positions)} pos_val=${pos_val:.0f} "
        f"redeemable={redeemable_count} parlay_open={parlay_open_count}"
    )
    sys.stdout.flush()


async def main_loop(db_url: str = DB_URL):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logger.info(f"=== OPEN POSITIONS BACKFILLER STARTED (CONCURRENCY={CONCURRENCY}) ===")

    # Each wallet task holds a connection while the shared limiter may briefly
    # acquire another.  Leave headroom so high fan-out cannot starve it.
    pool = await asyncpg.create_pool(DB_URL, min_size=16, max_size=max(140, CONCURRENCY + 40))
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
                        WHERE (
                              m.open_synced_at IS NULL
                              OR m.open_synced_at < NOW() - make_interval(hours => $1)
                          )
                        ORDER BY
                          CASE WHEN m.open_synced_at IS NULL THEN 0 ELSE 1 END ASC,
                          CASE
                            WHEN w.tier IN ('CURATED', 'CUSTOM') THEN 0
                            WHEN w.tier = 'STANDARD' THEN 1
                            WHEN w.tier = 'NEW' THEN 2
                            WHEN w.tier = 'LOW_BALANCE' THEN 3
                            ELSE 4
                          END ASC,
                          COALESCE(m.open_synced_at, '1970-01-01'::TIMESTAMPTZ) ASC
                        LIMIT $2
                    """, STALE_AFTER_HOURS, BATCH_SIZE)
                    wallets = [r["address"] for r in rows]
                    total = len(wallets)

                if total == 0:
                    logger.info("All active wallets fully backfilled (open)! Sleeping for 60s...")
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
                                    process_wallet_open(conn, session, addr, rate_limiter),
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
