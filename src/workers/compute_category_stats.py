"""
Worker B: Category & League Returns Computer
=============================================
Computes multi-tier hierarchical category statistics from wallet_closed_positions_v2:
- Root Category rollups (SPORTS, POLITICS, CRYPTO, CULTURE, TECH, FINANCE, MENTIONS, OTHER)
- Subcategory & Competition League breakdowns
- Category-level win rates, volume, resolved/winning counts
- Keeps category PnL as the unscaled sum of its position rows
- Writes to category_stats_v2
"""

import asyncio
import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from typing import Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

import asyncpg
from src.pnl.rules import is_winning_pnl
from src.utils.category_classifier import classify_market

logger = logging.getLogger("compute_category_stats")
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def _parse_realized_pnl(cp: dict) -> float:
    return _parse(cp.get("realized_pnl") if "realized_pnl" in cp else cp.get("realizedPnl"))

async def compute_category_stats_for_wallet(
    conn: asyncpg.Connection,
    address: str,
) -> int:
    """Compute unscaled position-row category metrics for one wallet."""
    # 1. Fetch closed positions with market metadata
    closed_rows = await conn.fetch("""
        SELECT c.condition_id, c.outcome, c.avg_buy_price, c.avg_sell_price,
               c.total_bought, c.total_sold, c.realized_pnl, c.is_redeemable,
               m.title as title,
               COALESCE(m.event_slug, '') as event_slug,
               m.winning_outcome as winning_outcome,
               COALESCE(m.category, 'OTHER') as category,
               COALESCE(m.subcategory, '') as subcategory,
               COALESCE(m.league, '') as league,
               p.current_value as current_value
        FROM wallet_closed_positions_v2 c
        LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
        LEFT JOIN wallet_positions_v2 p
            ON p.address = c.address AND p.condition_id = c.condition_id AND p.outcome = c.outcome
        WHERE c.address = $1
          AND COALESCE(c.metrics_eligible, TRUE)
    """, address)

    if not closed_rows:
        await conn.execute("DELETE FROM category_stats_v2 WHERE address = $1", address)
        return 0

    cat_metrics = defaultdict(lambda: {"pnl": 0.0, "volume": 0.0, "wins": 0, "resolved": 0})

    for cp in closed_rows:
        leg_pnl = _parse_realized_pnl(cp)
        buy_p = _parse(cp.get("avg_buy_price"))
        leg_vol = (_parse(cp.get("total_bought")) * buy_p) if buy_p > 0 else 0.0
        is_leg_win = is_winning_pnl(leg_pnl)

        cat = cp.get("category") or "OTHER"
        subcat = cp.get("subcategory") or ""
        league = cp.get("league") or ""
        title = cp.get("title") or ""
        event_slug = cp.get("event_slug") or ""

        if (cat == "OTHER" or (cat == "SPORTS" and not subcat)) and title:
            t_cat, t_sub, t_lg = classify_market(title, event_slug)
            if t_cat != "OTHER":
                cat = t_cat
                if t_sub:
                    subcat = t_sub
                if t_lg:
                    league = t_lg

        if cat == "SPORTS" and not subcat:
            subcat = "Unclassified Sports"
            league = ""

        # Root Category aggregate
        m_cat = cat_metrics[(cat, "", "")]
        m_cat["pnl"] += leg_pnl
        m_cat["volume"] += leg_vol
        m_cat["resolved"] += 1
        if is_leg_win:
            m_cat["wins"] += 1

        # Subcategory & League breakdown aggregate
        if subcat or league:
            m_sub = cat_metrics[(cat, subcat or "", league or "")]
            m_sub["pnl"] += leg_pnl
            m_sub["volume"] += leg_vol
            m_sub["resolved"] += 1
            if is_leg_win:
                m_sub["wins"] += 1

    await conn.execute("DELETE FROM category_stats_v2 WHERE address = $1", address)
    cat_rows = []
    for (cat, subcat, league), m in cat_metrics.items():
        cat_wr = (m["wins"] / m["resolved"] * 100.0) if m["resolved"] > 0 else None
        cat_pnl = m["pnl"]
        cat_roi = max(-100.0, min((cat_pnl / m["volume"] * 100.0), 10000.0)) if m["volume"] and m["volume"] >= 10.0 else None
        cat_rows.append((address, cat, subcat, league, cat_pnl, m["volume"], cat_wr, cat_roi, m["resolved"], m["wins"]))

    if cat_rows:
        await conn.executemany("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            ) VALUES ($1, $2, $3, $4, 0, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW()
        """, cat_rows)

    await conn.execute("""
        UPDATE wallet_metrics_v2 
        SET categories_computed_at = NOW() 
        WHERE address = $1
    """, address)

    return len(cat_rows)

async def main():
    parser = argparse.ArgumentParser(description="Worker B: Category & League Returns Computer")
    parser.add_argument("--concurrency", type=int, default=100, help="Number of concurrent workers")
    parser.add_argument("--wallet", type=str, default=None, help="Specific wallet address to compute")
    parser.add_argument("--limit", type=int, default=None, help="Max wallets to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pool = await asyncpg.create_pool(DB_URL, min_size=10, max_size=args.concurrency)

    if args.wallet:
        async with pool.acquire() as conn:
            cnt = await compute_category_stats_for_wallet(conn, args.wallet.lower())
            logger.info(f"Computed {cnt} category breakdown rows for {args.wallet}.")
        await pool.close()
        return

    logger.info(f"Fetching active wallets for Category Stats Compute (Concurrency: {args.concurrency})...")
    async with pool.acquire() as conn:
        limit_clause = f"LIMIT {args.limit}" if args.limit else ""
        rows = await conn.fetch(f"""
            SELECT address FROM wallet_metrics_v2 
            WHERE resolved_count > 0
              AND (categories_computed_at IS NULL OR categories_computed_at < NOW() - INTERVAL '2 hours')
            ORDER BY categories_computed_at NULLS FIRST, COALESCE(pm_volume, total_volume, 0) DESC
            {limit_clause};
        """)
        wallets = [r["address"] for r in rows]

    total = len(wallets)
    logger.info(f"Found {total:,} wallets to process for Category Stats.")

    sem = asyncio.Semaphore(args.concurrency)
    processed = 0
    start_t = time.time()

    async def _worker(addr: str):
        nonlocal processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_category_stats_for_wallet(conn, addr)
                except Exception as e:
                    logger.error(f"Error computing category stats for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 1000 == 0 or processed == total:
                        elapsed = time.time() - start_t
                        speed = processed / elapsed if elapsed > 0 else 0
                        logger.info(f"Category Stats Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/s")

    await asyncio.gather(*[_worker(addr) for addr in wallets])
    logger.info(f"Category Stats Computation finished in {(time.time() - start_t)/60:.2f} minutes!")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
