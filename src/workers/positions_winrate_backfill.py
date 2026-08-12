# src/workers/positions_winrate_backfill.py
"""
High-Speed Positions & Win-Rate Backfill Worker
================================================
Fetches positions, closed positions (up to 5,000 newest), win rate, volume, PnL,
and 10 Window PnLs (100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000)
for ALL active wallets (Curated, Standard, Low Balance) using ONLY the fast, reliable
Polymarket REST API (data-api.polymarket.com).

NO Polygonscan on-chain scanning.
NO Alchemy RPC rate-limit blocking.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timezone

from src.utils.category_classifier import classify_tags
from src.workers.leaderboard_stats import (
    fetch_website_pnl, fetch_positions, fetch_closed_positions,
    _parse, _parse_end
)

logger = logging.getLogger("positions_winrate_backfill")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
CONCURRENCY = int(os.environ.get("BACKFILL_CONCURRENCY", "15"))
WALLET_TIMEOUT = int(os.environ.get("BACKFILL_WALLET_TIMEOUT", "90"))
WINDOWS = [100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000]


# ── DB Helpers ──────────────────────────────────────────────────────────────

async def upsert_closed_positions_v2(conn: asyncpg.Connection, address: str, closed_list: list[dict]):
    if not closed_list:
        return
    rows = []
    for cp in closed_list:
        cid = cp.get("conditionId") or ""
        if not cid:
            continue
        rows.append((
            address,
            cid,
            cp.get("outcome") or "",
            _parse(cp.get("avgPrice")),
            _parse(cp.get("avgSellPrice")),
            _parse(cp.get("totalBought")),
            _parse(cp.get("totalSold")),
            _parse(cp.get("realizedPnl")),
            _parse_end(cp.get("endDate")),
        ))
    if rows:
        await conn.executemany("""
            INSERT INTO wallet_closed_positions_v2
                (address, condition_id, outcome, avg_buy_price, avg_sell_price,
                 total_bought, total_sold, realized_pnl, closed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT DO NOTHING
        """, rows)


async def aggregate_and_upsert_positions_v2(conn: asyncpg.Connection, address: str, open_positions: list[dict]):
    if not open_positions:
        return
    rows = []
    for p in open_positions:
        cid = p.get("conditionId")
        if not cid:
            continue
        rows.append((
            address,
            cid,
            p.get("outcome", ""),
            _parse(p.get("size")),
            _parse(p.get("avgPrice")),
            _parse(p.get("currentValue")),
            _parse(p.get("cashPnl")),
        ))
    if rows:
        await conn.executemany("""
            INSERT INTO wallet_positions_v2
                (address, condition_id, outcome, size, avg_price,
                 current_value, unrealized_pnl, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7, NOW())
            ON CONFLICT DO NOTHING
        """, rows)


# ── Per-Wallet Processor ─────────────────────────────────────────────────────

async def process_wallet_backfill(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    # Fetch official PnL/volume, open positions, and closed positions concurrently from Polymarket REST API
    website_f, positions_f, closed_positions_f = await asyncio.gather(
        fetch_website_pnl(session, address),
        fetch_positions(session, address),
        fetch_closed_positions(session, address),
        return_exceptions=True,
    )

    website          = website_f if isinstance(website_f, dict) else None
    positions        = positions_f if isinstance(positions_f, list) else []
    closed_tup       = closed_positions_f if isinstance(closed_positions_f, tuple) else ([], False)
    closed_positions = closed_tup[0]
    closed_success   = closed_tup[1] if isinstance(closed_tup, tuple) else False

    # Actual API failure occurs only if network exceptions were raised across calls
    api_failed = (
        isinstance(website_f, Exception) and
        isinstance(positions_f, Exception) and
        isinstance(closed_positions_f, Exception)
    )
    if api_failed or not closed_success:
        logger.warning(f"API request failed for {address[:12]}... — skipping, will retry")
        return

    # Preserve balance from existing DB row (Worker 2 / Alchemy updates balance separately)
    existing_balance = await conn.fetchval(
        "SELECT balance FROM wallet_metrics_v2 WHERE address = $1", address
    )
    balance = float(existing_balance) if existing_balance is not None else 0.0

    total_pnl    = website["pnl"]    if website else None
    total_volume = website["volume"] if website else None
    pos_val      = sum(_parse(p.get("currentValue", 0)) for p in positions)

    resolved, wins = 0, 0
    cat_volume: dict[str, float] = {}

    # Set of closed condition keys to prevent double-counting if an open position moved to closed
    closed_keys = {
        (cp.get("conditionId"), cp.get("asset", ""))
        for cp in closed_positions
        if cp.get("conditionId")
    }

    # Calculate wins/losses from closed positions
    for cp in closed_positions:
        resolved += 1
        if _parse(cp.get("realizedPnl")) > 0:
            wins += 1

    # Check open positions for resolved/redeemable status & category volume
    for p in positions:
        cid = p.get("conditionId")
        asset = p.get("asset", "")
        if (cid, asset) in closed_keys:
            # Already processed in closed_positions — skip to prevent double-counting
            continue

        cur_price    = _parse(p.get("curPrice"))
        redeemable   = p.get("redeemable", False)
        total_bought = _parse(p.get("totalBought"))
        title        = p.get("title") or ""
        end_date     = p.get("endDate")
        cash_pnl     = _parse(p.get("cashPnl"))
        realized_pnl = _parse(p.get("realizedPnl"))
        pos_pnl      = realized_pnl + cash_pnl

        if redeemable or cur_price < 0.03 or (end_date and cur_price < 0.10):
            resolved += 1
            if pos_pnl > 0 or cur_price > 0.97:
                wins += 1

        category = classify_tags([title])[0] if title else "OTHER"
        cat_volume[category] = cat_volume.get(category, 0.0) + total_bought

    win_rate = (wins / resolved) if resolved > 0 else None

    # Calculate Windowed PnLs for all 10 window steps
    window_pnls = {}
    for w in WINDOWS:
        slice_cp = closed_positions[:w]
        window_pnls[f"pnl_{w}"] = sum(_parse(cp.get("realizedPnl")) for cp in slice_cp) if slice_cp else (total_pnl if w == 5000 else 0.0)

    # Volume fallback logic if total_volume is missing
    if not total_volume or total_volume <= 0:
        cat_vol = sum(cat_volume.values())
        pos_vol = (
            sum(_parse(p.get("totalBought", 0)) for p in positions) +
            sum(_parse(p.get("totalBought", 0)) for p in closed_positions)
        )
        total_volume = max(cat_vol, pos_vol) or None

    if not total_volume or total_volume <= 0:
        try:
            from src.workers.wallet_trade_history import fetch_all_trades
            trades_fb = await fetch_all_trades(session, address)
            if trades_fb:
                total_volume = sum(
                    _parse(t.get("usd_volume")) or (_parse(t.get("size")) * _parse(t.get("price")))
                    for t in trades_fb
                ) or None
        except Exception as e:
            logger.debug(f"Trade volume fallback error {address[:12]}: {e}")

    is_zero_activity = (
        (not total_volume or total_volume == 0) and
        (not total_pnl or total_pnl == 0) and
        not positions and not closed_positions
    )

    # Write metrics and 10 windowed PnLs to wallet_metrics_v2
    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, total_volume, total_pnl, balance, position_value,
            win_rate, resolved_count, winning_count,
            pnl_100, pnl_200, pnl_300, pnl_500, pnl_750, pnl_1000, pnl_1500, pnl_2000, pnl_3500, pnl_5000,
            onchain_verify_pending, computed_at
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19, NOW())
        ON CONFLICT (address) DO UPDATE SET
            total_volume=EXCLUDED.total_volume,
            total_pnl=EXCLUDED.total_pnl,
            balance=EXCLUDED.balance,
            position_value=EXCLUDED.position_value,
            win_rate=EXCLUDED.win_rate,
            resolved_count=EXCLUDED.resolved_count,
            winning_count=EXCLUDED.winning_count,
            pnl_100=EXCLUDED.pnl_100,
            pnl_200=EXCLUDED.pnl_200,
            pnl_300=EXCLUDED.pnl_300,
            pnl_500=EXCLUDED.pnl_500,
            pnl_750=EXCLUDED.pnl_750,
            pnl_1000=EXCLUDED.pnl_1000,
            pnl_1500=EXCLUDED.pnl_1500,
            pnl_2000=EXCLUDED.pnl_2000,
            pnl_3500=EXCLUDED.pnl_3500,
            pnl_5000=EXCLUDED.pnl_5000,
            onchain_verify_pending=EXCLUDED.onchain_verify_pending,
            computed_at=NOW()
    """, address, total_volume, total_pnl, balance, pos_val, win_rate, resolved, wins,
         window_pnls["pnl_100"], window_pnls["pnl_200"], window_pnls["pnl_300"],
         window_pnls["pnl_500"], window_pnls["pnl_750"], window_pnls["pnl_1000"],
         window_pnls["pnl_1500"], window_pnls["pnl_2000"], window_pnls["pnl_3500"],
         window_pnls["pnl_5000"], is_zero_activity)

    # Calculate latest active date from closed positions
    last_active_dt = None
    for cp in closed_positions:
        end = _parse_end(cp.get("endDate"))
        if end and (last_active_dt is None or end > last_active_dt):
            last_active_dt = end

    # Update wallets_v2 last_trade_at and enforce dormancy (inactive > 30 days -> is_dormant = TRUE)
    if last_active_dt:
        await conn.execute("""
            UPDATE wallets_v2
            SET last_trade_at = $2,
                is_dormant = CASE WHEN $2 < NOW() - INTERVAL '30 days' THEN TRUE ELSE FALSE END
            WHERE address = $1
        """, address, last_active_dt)
    else:
        await conn.execute("""
            UPDATE wallets_v2
            SET is_dormant = CASE 
                WHEN last_trade_at IS NOT NULL AND last_trade_at < NOW() - INTERVAL '30 days' THEN TRUE 
                ELSE is_dormant 
            END
            WHERE address = $1
        """, address)

    if is_zero_activity:
        await conn.execute(
            "UPDATE wallets_v2 SET onchain_verify_pending = TRUE WHERE address = $1", address
        )

    # Upsert closed and open positions
    await upsert_closed_positions_v2(conn, address, closed_positions)
    await aggregate_and_upsert_positions_v2(conn, address, positions)

    logger.info(
        f"Done {address[:12]}... | vol=${total_volume or 0:.0f} "
        f"pnl=${total_pnl or 0:.0f} wr={(win_rate or 0)*100:.1f}% resolved={resolved}"
    )


# ── Main Orchestrator ────────────────────────────────────────────────────────

async def run_positions_winrate_backfill(db_url: str = DB_URL):
    logger.info(f"=== HIGH-SPEED POSITIONS & WIN-RATE BACKFILL WORKER STARTED (CONCURRENCY={CONCURRENCY}) ===")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=4, max_size=12)
    except Exception as e:
        logger.error(f"DB pool failed: {e}")
        return

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.address
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.is_dormant = FALSE
            ORDER BY m.computed_at ASC NULLS FIRST
        """)
        wallets = [r["address"] for r in rows]
        total = len(wallets)
        logger.info(f"Queue: {total} wallets (concurrency={CONCURRENCY}, timeout={WALLET_TIMEOUT}s)")

    sem = asyncio.Semaphore(CONCURRENCY)
    done, errors = 0, 0

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 5,
        limit_per_host=40,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as session:

        async def _process_one(addr):
            nonlocal done, errors
            async with sem:
                try:
                    async with pool.acquire() as conn:
                        await asyncio.wait_for(
                            process_wallet_backfill(conn, session, addr),
                            timeout=WALLET_TIMEOUT,
                        )
                    done += 1
                except asyncio.TimeoutError:
                    errors += 1
                    logger.warning(f"Timeout {addr[:12]}... ({WALLET_TIMEOUT}s)")
                except Exception as e:
                    errors += 1
                    logger.warning(f"Error {addr[:12]}...: {e}")

                if (done + errors) % 50 == 0 or (done + errors) == total:
                    logger.info(f"Progress: {done+errors}/{total} (ok={done} err={errors})")

        await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)

    logger.info(f"=== BACKFILL COMPLETE: {done} ok, {errors} errors / {total} ===")
    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(run_positions_winrate_backfill())
