# src/workers/positions_winrate_backfill.py
"""
Worker 1: High-Speed Positions & Win-Rate Sync with Price Buckets & 10 PnL Windows
==================================================================================
Syncs position data, computes 10 PnL windows (100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000),
calculates price-bucket Win Rates and Avg Sell Prices (<0.15, 0.15-0.30, 0.30-0.45, 0.45-0.60, 0.60-0.75, >0.75),
and upserts results into wallet_metrics_v2.
"""

import asyncio
import logging
import os
import aiohttp
import asyncpg
from typing import Optional

from src.workers.wallet_trade_history import fetch_positions, fetch_closed_positions, fetch_website_pnl
from src.utils.category_classifier import classify_tags, flatten_subcategory

logger = logging.getLogger("positions_winrate_backfill")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
CONCURRENCY = 15
WALLET_TIMEOUT = 90

WINDOWS = [100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000]


def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_end(dt_str) -> Optional[object]:
    """Parse a market endDate string, capping at today to avoid future 2027+ phantom dates.
    Polymarket sets endDate as a market deadline (e.g. 2027-12-31) before the market resolves.
    We must never use a future endDate as the wallet's last active timestamp."""
    if not dt_str:
        return None
    try:
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        if isinstance(dt_str, (int, float)):
            if dt_str <= 86400:
                return None
            dt = datetime.fromtimestamp(dt_str, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        if dt.year <= 1970:
            return None
        # Reject future dates — endDate is a deadline, not a settlement date
        if dt > now:
            return None
        return dt
    except Exception:
        return None


def _get_price_bucket(buy_price: float) -> str:
    if buy_price < 0.15:
        return "below_15c"
    elif buy_price < 0.30:
        return "15_30c"
    elif buy_price < 0.45:
        return "30_45c"
    elif buy_price < 0.60:
        return "45_60c"
    elif buy_price < 0.75:
        return "60_75c"
    else:
        return "above_75c"


async def upsert_closed_positions_v2(conn: asyncpg.Connection, address: str, closed_positions: list[dict]):
    """Batch-upsert closed positions into wallet_closed_positions_v2."""
    if not closed_positions:
        return
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
        ))
    if not rows:
        return

    await conn.executemany("""
        INSERT INTO wallet_closed_positions_v2 (
            address, condition_id, outcome, avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, closed_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            avg_buy_price=EXCLUDED.avg_buy_price,
            avg_sell_price=EXCLUDED.avg_sell_price,
            total_bought=EXCLUDED.total_bought,
            total_sold=EXCLUDED.total_sold,
            realized_pnl=EXCLUDED.realized_pnl,
            closed_at=EXCLUDED.closed_at
    """, rows)


async def aggregate_and_upsert_positions_v2(conn: asyncpg.Connection, address: str, open_positions: list[dict]):
    """Batch-upsert active open positions into wallet_positions_v2."""
    if not open_positions:
        return
    rows = []
    for p in open_positions:
        cid = p.get("conditionId") or ""
        outcome = p.get("outcome") or p.get("asset", "")
        if not cid:
            continue
        cur_val = _parse(p.get("currentValue"))
        pos_pnl = _parse(p.get("realizedPnl")) + _parse(p.get("cashPnl"))
        rows.append((
            address, cid, outcome,
            _parse(p.get("size")), _parse(p.get("avgPrice")),
            cur_val, pos_pnl,
        ))
    if not rows:
        return

    await conn.executemany("""
        INSERT INTO wallet_positions_v2 (
            address, condition_id, outcome, size, avg_price, current_value, unrealized_pnl, computed_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7, NOW())
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            size=EXCLUDED.size,
            avg_price=EXCLUDED.avg_price,
            current_value=EXCLUDED.current_value,
            unrealized_pnl=EXCLUDED.unrealized_pnl,
            computed_at=NOW()
    """, rows)


async def process_wallet_backfill(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
):
    website_f, positions_f, closed_positions_f = await asyncio.gather(
        fetch_website_pnl(session, address),
        fetch_positions(session, address),
        fetch_closed_positions(session, address),
        return_exceptions=True,
    )

    website          = website_f if isinstance(website_f, dict) else None
    positions        = positions_f if isinstance(positions_f, list) else []
    closed_positions = closed_positions_f if isinstance(closed_positions_f, list) else []

    api_failed = (
        isinstance(website_f, Exception) and
        isinstance(positions_f, Exception) and
        isinstance(closed_positions_f, Exception)
    )
    if api_failed:
        logger.warning(f"API request failed for {address[:12]}... — skipping, will retry")
        return

    existing_balance = await conn.fetchval(
        "SELECT balance FROM wallet_metrics_v2 WHERE address = $1", address
    )
    balance = float(existing_balance) if existing_balance is not None else 0.0

    total_pnl    = website["pnl"]    if website else None
    total_volume = website["volume"] if website else None
    pos_val      = sum(_parse(p.get("currentValue", 0)) for p in positions)

    # Fallback: if the wallet isn't on the public leaderboard (API returns []),
    # compute PnL and volume directly from closed positions so it's never None.
    if (total_pnl is None or total_pnl == 0) and closed_positions:
        total_pnl = sum(_parse(cp.get("realizedPnl")) for cp in closed_positions) or None
    if (total_volume is None or total_volume == 0) and closed_positions:
        total_volume = sum(_parse(cp.get("totalBought")) for cp in closed_positions) or None

    resolved, wins = 0, 0
    cat_volume: dict[str, float] = {}
    from collections import defaultdict
    cat_metrics = defaultdict(lambda: {"pnl": 0.0, "volume": 0.0, "wins": 0, "resolved": 0})

    bucket_stats = {
        k: {"buys": 0, "wins": 0, "losses": 0, "sum_sell": 0.0, "count_sell": 0}
        for k in ["below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c"]
    }

    all_buy_prices = []

    closed_keys = {
        (cp.get("conditionId"), cp.get("asset", ""))
        for cp in closed_positions
        if cp.get("conditionId")
    }

    # Calculate wins/losses & price bucket stats from closed positions
    for cp in closed_positions:
        resolved += 1
        realized_pnl = _parse(cp.get("realizedPnl"))
        sell_p = _parse(cp.get("avgSellPrice"))
        cur_p = _parse(cp.get("curPrice"))
        is_win = realized_pnl > 0 or sell_p >= 0.95 or cur_p >= 0.95
        if is_win:
            wins += 1

        title = cp.get("title") or ""
        if title:
            raw_c, raw_s = classify_tags([title])
            cat = raw_c.upper()
            subcat = flatten_subcategory(raw_c, raw_s)
        else:
            cat, subcat = "OTHER", "General"

        m_cat = cat_metrics[(cat, "")]
        m_cat["pnl"] += realized_pnl
        m_cat["volume"] += _parse(cp.get("totalBought"))
        m_cat["resolved"] += 1
        if is_win:
            m_cat["wins"] += 1

        if subcat:
            m_sub = cat_metrics[(cat, subcat)]
            m_sub["pnl"] += realized_pnl
            m_sub["volume"] += _parse(cp.get("totalBought"))
            m_sub["resolved"] += 1
            if is_win:
                m_sub["wins"] += 1

        buy_price = _parse(cp.get("avgPrice"))
        if buy_price > 0:
            if buy_price > 1.0:
                buy_price = buy_price / 100.0
            all_buy_prices.append(buy_price)
            b_key = _get_price_bucket(buy_price)
            b = bucket_stats[b_key]
            b["buys"] += 1
            if is_win:
                b["wins"] += 1
            else:
                b["losses"] += 1

            if sell_p <= 0:
                sell_p = 1.0 if is_win else 0.0
            b["sum_sell"] += sell_p
            b["count_sell"] += 1

    # Check open positions for resolved/redeemable status, price buckets & category volume
    for p in positions:
        cid = p.get("conditionId")
        asset = p.get("asset", "")
        if (cid, asset) in closed_keys:
            continue

        cur_price    = _parse(p.get("curPrice"))
        redeemable   = p.get("redeemable", False)
        total_bought = _parse(p.get("totalBought"))
        title        = p.get("title") or ""
        end_date     = p.get("endDate")
        cash_pnl     = _parse(p.get("cashPnl"))
        realized_pnl = _parse(p.get("realizedPnl"))
        pos_pnl      = realized_pnl + cash_pnl

        if title:
            raw_c, raw_s = classify_tags([title])
            cat = raw_c.upper()
            subcat = flatten_subcategory(raw_c, raw_s)
        else:
            cat, subcat = "OTHER", "General"

        cat_volume[cat] = cat_volume.get(cat, 0.0) + total_bought
        cat_metrics[(cat, "")]["volume"] += total_bought
        if subcat:
            cat_metrics[(cat, subcat)]["volume"] += total_bought

        buy_price = _parse(p.get("avgPrice"))
        if buy_price > 0:
            if buy_price > 1.0:
                buy_price = buy_price / 100.0
            all_buy_prices.append(buy_price)

        is_resolved_pos = redeemable or cur_price < 0.03 or (end_date and cur_price < 0.10)
        if is_resolved_pos:
            resolved += 1
            is_win = pos_pnl > 0 or cur_price > 0.97
            if is_win:
                wins += 1

            m_cat = cat_metrics[(cat, "")]
            m_cat["resolved"] += 1
            if is_win:
                m_cat["wins"] += 1
            m_cat["pnl"] += pos_pnl

            if subcat:
                m_sub = cat_metrics[(cat, subcat)]
                m_sub["resolved"] += 1
                if is_win:
                    m_sub["wins"] += 1
                m_sub["pnl"] += pos_pnl

            if buy_price > 0:
                b_key = _get_price_bucket(buy_price)
                b = bucket_stats[b_key]
                b["buys"] += 1
                if is_win:
                    b["wins"] += 1
                else:
                    b["losses"] += 1

                sell_p = 1.0 if is_win else 0.0
                b["sum_sell"] += sell_p
                b["count_sell"] += 1

    win_rate = (wins / resolved) if resolved > 0 else None
    avg_buy_price = (sum(all_buy_prices) / len(all_buy_prices)) if all_buy_prices else None

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

    # Prepare computed avg_sell values per bucket
    avg_sells = {
        k: (bucket_stats[k]["sum_sell"] / bucket_stats[k]["count_sell"]) if bucket_stats[k]["count_sell"] > 0 else 0.0
        for k in bucket_stats
    }

    # Write metrics, price bucket stats & 10 windowed PnLs to wallet_metrics_v2
    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, total_volume, total_pnl, balance, position_value,
            win_rate, resolved_count, winning_count, avg_buy_price,
            buys_below_15c, wins_below_15c, losses_below_15c, avg_sell_below_15c,
            buys_15_30c, wins_15_30c, losses_15_30c, avg_sell_15_30c,
            buys_30_45c, wins_30_45c, losses_30_45c, avg_sell_30_45c,
            buys_45_60c, wins_45_60c, losses_45_60c, avg_sell_45_60c,
            buys_60_75c, wins_60_75c, losses_60_75c, avg_sell_60_75c,
            buys_above_75c, wins_above_75c, losses_above_75c, avg_sell_above_75c,
            pnl_100, pnl_200, pnl_300, pnl_500, pnl_750, pnl_1000, pnl_1500, pnl_2000, pnl_3500, pnl_5000,
            onchain_verify_pending, computed_at
        )
        VALUES (
            $1,$2,$3,$4,$5,
            $6,$7,$8,$9,
            $10,$11,$12,$13,
            $14,$15,$16,$17,
            $18,$19,$20,$21,
            $22,$23,$24,$25,
            $26,$27,$28,$29,
            $30,$31,$32,$33,
            $34,$35,$36,$37,$38,$39,$40,$41,$42,$43,
            $44, NOW()
        )
        ON CONFLICT (address) DO UPDATE SET
            total_volume=EXCLUDED.total_volume,
            total_pnl=EXCLUDED.total_pnl,
            balance=EXCLUDED.balance,
            position_value=EXCLUDED.position_value,
            win_rate=EXCLUDED.win_rate,
            resolved_count=EXCLUDED.resolved_count,
            winning_count=EXCLUDED.winning_count,
            avg_buy_price=EXCLUDED.avg_buy_price,
            buys_below_15c=EXCLUDED.buys_below_15c,
            wins_below_15c=EXCLUDED.wins_below_15c,
            losses_below_15c=EXCLUDED.losses_below_15c,
            avg_sell_below_15c=EXCLUDED.avg_sell_below_15c,
            buys_15_30c=EXCLUDED.buys_15_30c,
            wins_15_30c=EXCLUDED.wins_15_30c,
            losses_15_30c=EXCLUDED.losses_15_30c,
            avg_sell_15_30c=EXCLUDED.avg_sell_15_30c,
            buys_30_45c=EXCLUDED.buys_30_45c,
            wins_30_45c=EXCLUDED.wins_30_45c,
            losses_30_45c=EXCLUDED.losses_30_45c,
            avg_sell_30_45c=EXCLUDED.avg_sell_30_45c,
            buys_45_60c=EXCLUDED.buys_45_60c,
            wins_45_60c=EXCLUDED.wins_45_60c,
            losses_45_60c=EXCLUDED.losses_45_60c,
            avg_sell_45_60c=EXCLUDED.avg_sell_45_60c,
            buys_60_75c=EXCLUDED.buys_60_75c,
            wins_60_75c=EXCLUDED.wins_60_75c,
            losses_60_75c=EXCLUDED.losses_60_75c,
            avg_sell_60_75c=EXCLUDED.avg_sell_60_75c,
            buys_above_75c=EXCLUDED.buys_above_75c,
            wins_above_75c=EXCLUDED.wins_above_75c,
            losses_above_75c=EXCLUDED.losses_above_75c,
            avg_sell_above_75c=EXCLUDED.avg_sell_above_75c,
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
            open_synced_at=NOW(),
            closed_synced_at=NOW(),
            computed_at=NOW()
    """, address, total_volume, total_pnl, balance, pos_val,
         win_rate, resolved, wins, avg_buy_price,
         bucket_stats["below_15c"]["buys"], bucket_stats["below_15c"]["wins"], bucket_stats["below_15c"]["losses"], avg_sells["below_15c"],
         bucket_stats["15_30c"]["buys"], bucket_stats["15_30c"]["wins"], bucket_stats["15_30c"]["losses"], avg_sells["15_30c"],
         bucket_stats["30_45c"]["buys"], bucket_stats["30_45c"]["wins"], bucket_stats["30_45c"]["losses"], avg_sells["30_45c"],
         bucket_stats["45_60c"]["buys"], bucket_stats["45_60c"]["wins"], bucket_stats["45_60c"]["losses"], avg_sells["45_60c"],
         bucket_stats["60_75c"]["buys"], bucket_stats["60_75c"]["wins"], bucket_stats["60_75c"]["losses"], avg_sells["60_75c"],
         bucket_stats["above_75c"]["buys"], bucket_stats["above_75c"]["wins"], bucket_stats["above_75c"]["losses"], avg_sells["above_75c"],
         window_pnls["pnl_100"], window_pnls["pnl_200"], window_pnls["pnl_300"],
         window_pnls["pnl_500"], window_pnls["pnl_750"], window_pnls["pnl_1000"],
         window_pnls["pnl_1500"], window_pnls["pnl_2000"], window_pnls["pnl_3500"],
         window_pnls["pnl_5000"], is_zero_activity)

    # Calculate latest active date from closed positions
    # Use endDate only when it's in the past (real resolution) — never future deadlines
    from datetime import datetime, timezone as _tz
    _now = datetime.now(tz=_tz.utc)
    last_active_dt = None
    for cp in closed_positions:
        end = _parse_end(cp.get("endDate"))
        # Extra guard: _parse_end already filters futures, but be defensive
        if end and end <= _now and (last_active_dt is None or end > last_active_dt):
            last_active_dt = end

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
                ELSE FALSE 
            END
            WHERE address = $1
        """, address)

    for (cat, subcat), m in cat_metrics.items():
        cat_wr = (m["wins"] / m["resolved"]) if m["resolved"] > 0 else 0.0
        cat_roi = 0.0
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            ) VALUES ($1, $2, $3, 0, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (address, category, subcategory, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW()
        """, address, cat, subcat, m["pnl"], m["volume"], cat_wr, cat_roi, m["resolved"], m["wins"])

    await upsert_closed_positions_v2(conn, address, closed_positions)
    await aggregate_and_upsert_positions_v2(conn, address, positions)

    logger.info(
        f"Done {address[:12]}... | vol=${total_volume or 0:.0f} "
        f"pnl=${total_pnl or 0:.0f} wr={(win_rate or 0)*100:.1f}% resolved={resolved}"
    )


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
              AND (
                  -- 1. Fast schedule for open positions + open parlay positions: active in last 6 hours & open sync > 2 hours ago
                  (w.last_trade_at >= NOW() - INTERVAL '6 hours' AND (m.open_synced_at IS NULL OR m.open_synced_at < NOW() - INTERVAL '2 hours'))
                  OR
                  -- 2. Standard schedule for closed positions + closed parlay positions: active in last 7 days & closed sync > 5 days ago
                  ((w.last_trade_at IS NULL OR w.last_trade_at >= NOW() - INTERVAL '7 days') AND (m.closed_synced_at IS NULL OR m.closed_synced_at < NOW() - INTERVAL '5 days' OR m.computed_at IS NULL OR m.computed_at < NOW() - INTERVAL '5 days'))
              )
            ORDER BY 
              CASE WHEN w.tier IN ('CURATED', 'CUSTOM') THEN 0 ELSE 1 END ASC,
              LEAST(COALESCE(m.open_synced_at, '1970-01-01'::TIMESTAMPTZ), COALESCE(m.closed_synced_at, '1970-01-01'::TIMESTAMPTZ)) ASC
        """)
        wallets = [r["address"] for r in rows]
        total = len(wallets)
        logger.info(f"Queue: {total} wallets (concurrency={CONCURRENCY}, timeout={WALLET_TIMEOUT}s)")
        if total == 0:
            logger.info("No wallets in queue for positions/winrate backfill. Sleeping for 60s...")
            await pool.close()
            await asyncio.sleep(60)
            return

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
