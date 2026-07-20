import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timedelta, timezone

from src.utils.alchemy_client import fetch_capital_metrics
from src.utils.category_classifier import classify_tags
from src.workers.leaderboard_stats import (
    fetch_balance, fetch_website_pnl, fetch_supabase_wallet_profile, fetch_positions,
    _fetch_wallet_data, _fetch_category_pnl_batch, compute_stats, compute_wallet_tags,
    compute_category_stats, select_headline_pnl, _computed_volume, _parse, _parse_end
)
from src.workers.window_stats import compute_category_window_stats

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = 300
CONCURRENCY = int(os.environ.get("STATS_WORKER_CONCURRENCY", "10"))
WALLET_TIMEOUT = int(os.environ.get("STATS_WALLET_TIMEOUT", "600"))

async def get_latest_end_date_v2(conn: asyncpg.Connection, address: str) -> datetime | None:
    row = await conn.fetchrow("SELECT MAX(closed_at) as latest FROM wallet_closed_positions_v2 WHERE address = $1", address)
    return row["latest"] if row and row["latest"] else None

async def upsert_closed_positions_v2(conn: asyncpg.Connection, address: str, closed_list: list[dict]):
    if not closed_list:
        return
    rows = []
    for cp in closed_list:
        cid = cp.get("conditionId") or ""
        if not cid: continue
        outcome = cp.get("outcome") or ""
        realized_pnl = _parse(cp.get("realizedPnl"))
        total_bought = _parse(cp.get("totalBought"))
        total_sold = _parse(cp.get("totalSold"))
        avg_price = _parse(cp.get("avgPrice"))
        avg_sell_price = _parse(cp.get("avgSellPrice"))
        end_date = _parse_end(cp.get("endDate"))
        
        rows.append((address, cid, outcome, avg_price, avg_sell_price, total_bought, total_sold, realized_pnl, end_date))
        
    if rows:
        await conn.executemany("""
            INSERT INTO wallet_closed_positions_v2
                (address, condition_id, outcome, avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, closed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT DO NOTHING
        """, rows)

async def aggregate_and_upsert_positions_v2(conn, address, open_positions):
    if not open_positions:
        return
    rows = []
    for p in open_positions:
        cid = p.get('conditionId')
        if not cid: continue
        outcome = p.get('outcome', '')
        size = _parse(p.get('size'))
        avg_price = _parse(p.get('avgPrice'))
        cur_val = _parse(p.get('currentValue'))
        upnl = _parse(p.get('cashPnl'))
        rows.append((address, cid, outcome, size, avg_price, cur_val, upnl))

    if rows:
        await conn.executemany('''
            INSERT INTO wallet_positions_v2
            (address, condition_id, outcome, size, avg_price, current_value, unrealized_pnl, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT DO NOTHING
        ''', rows)

async def compute_window_stats_from_db_v2(conn, address):
    # For now we'll just return empty to skip heavy re-computation of win rates from DB
    # We rely on Supabase for global win rates anyway
    return {}

async def process_wallet_v2(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    row = await conn.fetchrow(
        "SELECT tier, is_dormant, last_trade_at FROM wallets_v2 WHERE address = $1",
        address
    )
    if not row:
        return

    is_curated = row["tier"] == "CURATED"
    start_stats_at = datetime.now(timezone.utc) - timedelta(days=365) # Approximation for v2

    supabase = None
    if is_curated:
        data = await _fetch_wallet_data(session, address, start_stats_at)
        trades, positions, balance, website = data["trades"], data["positions"], data["balance"], data["website"]
        deposits, withdrawals, peak_capital = data["deposits"], data["withdrawals"], data["peak_capital"]
    else:
        balance_f, website_f, supabase_f, positions_f = await asyncio.gather(
            fetch_balance(session, address),
            fetch_website_pnl(session, address),
            fetch_supabase_wallet_profile(session, address),
            fetch_positions(session, address),
            return_exceptions=True,
        )
        balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
        website = website_f if isinstance(website_f, dict) else None
        supabase = supabase_f if isinstance(supabase_f, dict) else None
        trades, positions = [], positions_f if isinstance(positions_f, list) else []
        capital_f = await fetch_capital_metrics(session, address)
        if isinstance(capital_f, tuple) and len(capital_f) == 3:
            deposits, withdrawals, peak_capital = capital_f
        else:
            deposits, withdrawals, peak_capital = 0.0, 0.0, 0.0

    # NON-CURATED short-circuit
    if not is_curated:
        sb_wr = supabase["win_rate"] if supabase and supabase.get("win_rate") is not None else None
        sb_roi = supabase["roi_pct"] if supabase and supabase.get("roi_pct") is not None else None
        sb_resolved = supabase["resolved_count"] if supabase and supabase.get("resolved_count") is not None else None
        sb_winning = supabase["winning_count"] if supabase and supabase.get("winning_count") is not None else None

        total_pnl = website["pnl"] if website else None
        total_volume = website["volume"] if website else None
        pos_val = sum(_parse(p.get("currentValue", 0)) for p in positions)

        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count, total_volume, total_pnl, balance, deposits, withdrawals, position_value, peak_capital, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct,
                resolved_count=EXCLUDED.resolved_count, winning_count=EXCLUDED.winning_count,
                total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                balance=EXCLUDED.balance, deposits=EXCLUDED.deposits,
                withdrawals=EXCLUDED.withdrawals, position_value=EXCLUDED.position_value,
                peak_capital=EXCLUDED.peak_capital, computed_at=NOW()
        """, address, sb_wr, sb_roi, sb_resolved, sb_winning, total_volume, total_pnl, balance, deposits, withdrawals, pos_val, peak_capital)
        return

    # CURATED WALLETS
    if not supabase:
        supabase_f = await fetch_supabase_wallet_profile(session, address)
        supabase = supabase_f if isinstance(supabase_f, dict) else None

    from src.utils.etherscan_client import fetch_historical_redemptions_polygonscan, build_synthetic_closed_positions
    proxies = set(t.get("proxyWallet") for t in trades if t.get("proxyWallet") and isinstance(t.get("proxyWallet"), str))
    addresses_to_query = [address] + list(proxies)
    
    redemptions = await fetch_historical_redemptions_polygonscan(session, addresses_to_query)
    synthetic_closed = build_synthetic_closed_positions(trades, redemptions)
    
    await upsert_closed_positions_v2(conn, address, synthetic_closed)
    closed = synthetic_closed
    
    headline = select_headline_pnl(website, 0.0, _computed_volume(trades))
    stats = compute_stats(positions, closed, headline["pnl"], headline["volume"], start_stats_at, peak_capital)

    if supabase:
        if supabase.get("win_rate") is not None: stats["win_rate"] = supabase["win_rate"]
        if supabase.get("roi_pct") is not None: stats["roi_pct"] = supabase["roi_pct"]
        if supabase.get("resolved_count") is not None: stats["resolved_count"] = supabase["resolved_count"]
        if supabase.get("winning_count") is not None: stats["winning_count"] = supabase["winning_count"]

    from src.workers.curated_positions_builder import build_wallet_positions
    await build_wallet_positions(conn, session, address)
    wr_row = await conn.fetchrow(
        """
        SELECT COUNT(*) FILTER (WHERE is_resolved) AS resolved,
               COUNT(*) FILTER (WHERE is_win) AS wins
        FROM curated_positions WHERE address = $1
        """,
        address,
    )
    if wr_row and wr_row["resolved"]:
        stats["resolved_count"] = wr_row["resolved"]
        stats["winning_count"] = wr_row["wins"]
        stats["win_rate"] = wr_row["wins"] / wr_row["resolved"]

    pos_val = sum(_parse(p.get("currentValue", 0)) for p in positions)

    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, total_volume, total_pnl, win_rate, roi_pct, resolved_count, winning_count,
            balance, deposits, withdrawals, position_value, peak_capital, biggest_win, biggest_loss,
            active_days, avg_buy_price, computed_at
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW()
        ) ON CONFLICT (address) DO UPDATE SET
            total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
            win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct,
            resolved_count=EXCLUDED.resolved_count, winning_count=EXCLUDED.winning_count,
            balance=EXCLUDED.balance, deposits=EXCLUDED.deposits, withdrawals=EXCLUDED.withdrawals,
            position_value=EXCLUDED.position_value, peak_capital=EXCLUDED.peak_capital,
            biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
            active_days=EXCLUDED.active_days, avg_buy_price=EXCLUDED.avg_buy_price,
            computed_at=NOW()
    """, address, stats["total_volume"], stats["total_pnl"], stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
         balance, deposits, withdrawals, pos_val, peak_capital, stats["biggest_win"], stats["biggest_loss"], stats["active_days"], stats["avg_buy_price"])

    trade_categories = set(classify_tags([t.get("title") or ""])[0] for t in trades if t.get("title"))
    pm_category_pnl = await _fetch_category_pnl_batch(session, address, trade_categories)
    cat_stats, sub_stats = compute_category_stats(trades, closed, pm_category_pnl)
    
    for cs in cat_stats:
        await conn.execute("""
            INSERT INTO category_stats_v2 (address, category, subcategory, window_size, pnl, volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,'',0,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT DO NOTHING
        """, address, cs["category"], cs["total_pnl"], cs["total_volume"], cs["win_rate"], cs["resolved_count"], cs["winning_count"], cs["roi_pct"], cs["last_active"])
    
    for ss in sub_stats:
        await conn.execute("""
            INSERT INTO category_stats_v2 (address, category, subcategory, window_size, pnl, volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,$3,0,$4,$5,$6,$7,$8,$9,$10,NOW())
            ON CONFLICT DO NOTHING
        """, address, ss["category"], ss["subcategory"], ss["total_pnl"], ss["total_volume"], ss["win_rate"], ss["resolved_count"], ss["winning_count"], ss["roi_pct"], ss["last_active"])

    TRADE_WINDOWS = [100, 300, 800, 1500, 2500]
    window_stats = compute_category_window_stats(closed or [], TRADE_WINDOWS, lambda title: classify_tags([title])[0] if title else "OTHER")
    for (cat, window), s in window_stats.items():
        await conn.execute("""
            INSERT INTO category_stats_v2 (address, category, subcategory, window_size, pnl, volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,'',$3,$4,$5,$6,$7,$8,$9,$10,NOW())
            ON CONFLICT DO NOTHING
        """, address, cat.upper(), window, s["pnl"], s["volume"], s["win_rate"], s["resolved_count"], s["winning_count"], s["roi_pct"], s["last_active"])

    await aggregate_and_upsert_positions_v2(conn, address, positions)
    logger.info(f"Done curated wallet {address[:10]}... | vol=${stats['total_volume']:.0f} pnl=${stats['total_pnl']:.0f}")

async def run_leaderboard_stats_v2(db_url: str = DB_URL):
    logger.info("Starting V2 Leaderboard Stats worker (concurrency=%d, interval=%ds)...", CONCURRENCY, POLL_INTERVAL)
    try:
        pool = await asyncpg.create_pool(db_url, min_size=2, max_size=15)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return

    while True:
        try:
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
                logger.info(f"Processing {total} wallets with concurrency={CONCURRENCY}...")

            sem = asyncio.Semaphore(CONCURRENCY)
            done, errors = 0, 0

            async def _process_one(addr):
                nonlocal done, errors
                async with sem:
                    try:
                        async with pool.acquire() as conn:
                            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                                await asyncio.wait_for(process_wallet_v2(conn, session, addr), timeout=WALLET_TIMEOUT)
                        done += 1
                    except asyncio.TimeoutError:
                        errors += 1
                        logger.warning(f"Timeout {addr[:10]}... ({WALLET_TIMEOUT}s)")
                    except Exception as e:
                        errors += 1
                        logger.warning(f"Error {addr[:10]}...: {e}")
                    if (done + errors) % 50 == 0:
                        logger.info(f"Progress: {done + errors}/{total} (ok={done} err={errors})")

            await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)
            logger.info(f"Full pass complete: {done} ok, {errors} errors out of {total}")
            await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(run_leaderboard_stats_v2())
