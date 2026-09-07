"""
Worker A: Core Account Metrics Computer
=======================================
Computes wallet-level core performance metrics from wallet_closed_positions_v2:
- Per-position win rate at (condition_id, outcome) contract-row grain
- Resolved count, winning count, losing count
- 6 price-bucket matrices (<15c, 15-30c, 30-45c, 45-60c, 60-75c, >75c)
- Parlay metrics (pnl, volume, win rate, resolved/winning counts)
- Total USD volume, unscaled position-ledger PnL, and ROI
- Updates wallet_metrics_v2
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

import aiohttp
import asyncpg
from src.pnl.rules import is_winning_pnl

logger = logging.getLogger("compute_core_metrics")
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

def _is_parlay(row: asyncpg.Record) -> bool:
    return bool(row.get("is_parlay", False))

async def compute_core_metrics_for_wallet(
    conn: asyncpg.Connection,
    address: str,
) -> dict:
    """Computes core win rate, price buckets, parlay, and volume metrics for a single wallet."""
    closed_rows = await conn.fetch("""
        SELECT c.condition_id, c.outcome, c.avg_buy_price, c.avg_sell_price,
               c.total_bought, c.total_sold, c.realized_pnl, c.closed_at, c.is_parlay,
               c.is_redeemable, c.data_quality_flag,
               m.winning_outcome as winning_outcome,
               p.current_value as current_value
        FROM wallet_closed_positions_v2 c
        LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
        LEFT JOIN wallet_positions_v2 p
            ON p.address = c.address AND p.condition_id = c.condition_id AND p.outcome = c.outcome
        WHERE c.address = $1
          AND COALESCE(c.metrics_eligible, TRUE)
    """, address)

    # Official pm_* and capital fields are read-only inputs to this pass.  Do
    # not use them as fallbacks for internal totals.
    if not closed_rows:
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, total_pnl, total_volume, win_rate, resolved_count, winning_count, computed_at)
            VALUES ($1, NULL, NULL, NULL, 0, 0, NOW())
            ON CONFLICT (address) DO UPDATE SET
                total_pnl = NULL,
                total_volume = NULL,
                win_rate = NULL,
                resolved_count = 0,
                winning_count = 0,
                computed_at = NOW();
        """, address)
        return {"address": address, "resolved": 0, "win_rate": None}

    # Sum of raw closed positions strictly from database ledger
    total_raw_pnl = sum(_parse_realized_pnl(cp) for cp in closed_rows)
    total_pnl = total_raw_pnl

    calc_volume = sum(
        (_parse(cp.get("total_bought")) * _parse(cp.get("avg_buy_price")))
        for cp in closed_rows
        if _parse(cp.get("avg_buy_price")) > 0
    )
    # A complete eligible history with no measurable buy basis has an explicit
    # zero canonical volume.  Never preserve an older/official volume value.
    total_volume = calc_volume

    resolved = len(closed_rows)
    wins = sum(1 for cp in closed_rows if is_winning_pnl(_parse_realized_pnl(cp)))
    all_buy_prices = []

    bucket_stats = {
        k: {"buys": 0, "wins": 0, "losses": 0, "sum_sell": 0.0, "count_sell": 0}
        for k in ["below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c"]
    }

    for cp in closed_rows:
        buy_price = _parse(cp.get("avg_buy_price"))
        sell_p = _parse(cp.get("avg_sell_price"))
        is_leg_win = is_winning_pnl(_parse_realized_pnl(cp))
        if buy_price > 0:
            if buy_price > 1.0:
                buy_price = buy_price / 100.0
            all_buy_prices.append(buy_price)
            b_key = _get_price_bucket(buy_price)
            if b_key:
                bucket_stats[b_key]["buys"] += 1
                if is_leg_win:
                    bucket_stats[b_key]["wins"] += 1
                else:
                    bucket_stats[b_key]["losses"] += 1
                if sell_p > 0:
                    bucket_stats[b_key]["sum_sell"] += sell_p
                    bucket_stats[b_key]["count_sell"] += 1

    win_rate = (wins / resolved * 100.0) if resolved > 0 else None
    avg_buy_price = (sum(all_buy_prices) / len(all_buy_prices)) if all_buy_prices else None

    # Parlay statistics
    parlay_closed = [cp for cp in closed_rows if _is_parlay(cp)]
    parlay_resolved_count = len(parlay_closed)
    parlay_winning_count = sum(
        1 for cp in parlay_closed
        if is_winning_pnl(_parse_realized_pnl(cp))
    )
    parlay_pnl = sum(_parse_realized_pnl(cp) for cp in parlay_closed) if parlay_resolved_count > 0 else None
    parlay_volume = sum(
        _parse(cp.get("total_bought")) * _parse(cp.get("avg_buy_price"))
        for cp in parlay_closed
    ) if parlay_resolved_count > 0 else None
    parlay_win_rate = (parlay_winning_count / parlay_resolved_count * 100.0) if parlay_resolved_count > 0 else None

    # Calculate price bucket average sell prices
    avg_sells = {}
    for k, v in bucket_stats.items():
        avg_sells[k] = (v["sum_sell"] / v["count_sell"]) if v["count_sell"] > 0 else None

    # ROI Calculation
    roi_pct = None
    if total_volume and total_volume >= 10.0 and total_pnl is not None:
        roi_pct = max(-100.0, min((total_pnl / total_volume * 100.0), 10000.0))

    flagged_count = sum(1 for cp in closed_rows if cp.get("data_quality_flag"))
    data_completeness = round((1.0 - (flagged_count / len(closed_rows))) * 100.0, 2) if closed_rows else 100.0

    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, total_volume, total_pnl, roi_pct, win_rate, resolved_count, winning_count, avg_buy_price,
            buys_below_15c, wins_below_15c, losses_below_15c, avg_sell_below_15c,
            buys_15_30c, wins_15_30c, losses_15_30c, avg_sell_15_30c,
            buys_30_45c, wins_30_45c, losses_30_45c, avg_sell_30_45c,
            buys_45_60c, wins_45_60c, losses_45_60c, avg_sell_45_60c,
            buys_60_75c, wins_60_75c, losses_60_75c, avg_sell_60_75c,
            buys_above_75c, wins_above_75c, losses_above_75c, avg_sell_above_75c,
            parlay_pnl, parlay_volume, parlay_win_rate, parlay_resolved_count, parlay_winning_count,
            data_completeness_pct, computed_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11, $12,
            $13, $14, $15, $16,
            $17, $18, $19, $20,
            $21, $22, $23, $24,
            $25, $26, $27, $28,
            $29, $30, $31, $32,
            $33, $34, $35, $36, $37,
            $38, NOW()
        )
        ON CONFLICT (address) DO UPDATE SET
            total_volume = EXCLUDED.total_volume,
            total_pnl = EXCLUDED.total_pnl,
            roi_pct = EXCLUDED.roi_pct,
            win_rate = EXCLUDED.win_rate,
            resolved_count = EXCLUDED.resolved_count,
            winning_count = EXCLUDED.winning_count,
            avg_buy_price = EXCLUDED.avg_buy_price,
            buys_below_15c = EXCLUDED.buys_below_15c,
            wins_below_15c = EXCLUDED.wins_below_15c,
            losses_below_15c = EXCLUDED.losses_below_15c,
            avg_sell_below_15c = EXCLUDED.avg_sell_below_15c,
            buys_15_30c = EXCLUDED.buys_15_30c,
            wins_15_30c = EXCLUDED.wins_15_30c,
            losses_15_30c = EXCLUDED.losses_15_30c,
            avg_sell_15_30c = EXCLUDED.avg_sell_15_30c,
            buys_30_45c = EXCLUDED.buys_30_45c,
            wins_30_45c = EXCLUDED.wins_30_45c,
            losses_30_45c = EXCLUDED.losses_30_45c,
            avg_sell_30_45c = EXCLUDED.avg_sell_30_45c,
            buys_45_60c = EXCLUDED.buys_45_60c,
            wins_45_60c = EXCLUDED.wins_45_60c,
            losses_45_60c = EXCLUDED.losses_45_60c,
            avg_sell_45_60c = EXCLUDED.avg_sell_45_60c,
            buys_60_75c = EXCLUDED.buys_60_75c,
            wins_60_75c = EXCLUDED.wins_60_75c,
            losses_60_75c = EXCLUDED.losses_60_75c,
            avg_sell_60_75c = EXCLUDED.avg_sell_60_75c,
            buys_above_75c = EXCLUDED.buys_above_75c,
            wins_above_75c = EXCLUDED.wins_above_75c,
            losses_above_75c = EXCLUDED.losses_above_75c,
            avg_sell_above_75c = EXCLUDED.avg_sell_above_75c,
            parlay_pnl = EXCLUDED.parlay_pnl,
            parlay_volume = EXCLUDED.parlay_volume,
            parlay_win_rate = EXCLUDED.parlay_win_rate,
            parlay_resolved_count = EXCLUDED.parlay_resolved_count,
            parlay_winning_count = EXCLUDED.parlay_winning_count,
            data_completeness_pct = EXCLUDED.data_completeness_pct,
            computed_at = NOW();
    """, address, total_volume, total_pnl, roi_pct, win_rate, resolved, wins, avg_buy_price,
         bucket_stats["below_15c"]["buys"], bucket_stats["below_15c"]["wins"], bucket_stats["below_15c"]["losses"], avg_sells["below_15c"],
         bucket_stats["15_30c"]["buys"], bucket_stats["15_30c"]["wins"], bucket_stats["15_30c"]["losses"], avg_sells["15_30c"],
         bucket_stats["30_45c"]["buys"], bucket_stats["30_45c"]["wins"], bucket_stats["30_45c"]["losses"], avg_sells["30_45c"],
         bucket_stats["45_60c"]["buys"], bucket_stats["45_60c"]["wins"], bucket_stats["45_60c"]["losses"], avg_sells["45_60c"],
         bucket_stats["60_75c"]["buys"], bucket_stats["60_75c"]["wins"], bucket_stats["60_75c"]["losses"], avg_sells["60_75c"],
         bucket_stats["above_75c"]["buys"], bucket_stats["above_75c"]["wins"], bucket_stats["above_75c"]["losses"], avg_sells["above_75c"],
         parlay_pnl, parlay_volume, parlay_win_rate, parlay_resolved_count, parlay_winning_count,
         data_completeness)

    return {
        "address": address,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "resolved_count": resolved,
        "winning_count": wins,
    }

async def main():
    parser = argparse.ArgumentParser(description="Worker A: Core Account Metrics Computer")
    parser.add_argument("--concurrency", type=int, default=250, help="Number of concurrent workers")
    parser.add_argument("--wallet", type=str, default=None, help="Specific wallet address to compute")
    parser.add_argument("--limit", type=int, default=None, help="Max wallets to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pool = await asyncpg.create_pool(DB_URL, min_size=10, max_size=args.concurrency)

    if args.wallet:
        async with pool.acquire() as conn:
            res = await compute_core_metrics_for_wallet(conn, args.wallet.lower())
            logger.info(f"Single wallet result: {res}")
        await pool.close()
        return

    logger.info(f"Fetching active wallets for Core Metrics Compute (Concurrency: {args.concurrency})...")
    async with pool.acquire() as conn:
        limit_clause = f"LIMIT {args.limit}" if args.limit else ""
        rows = await conn.fetch(f"""
            SELECT address FROM wallet_metrics_v2 
            WHERE (resolved_count > 0 OR position_value > 0)
              AND (computed_at IS NULL OR computed_at < NOW() - INTERVAL '2 hours')
            ORDER BY computed_at NULLS FIRST, COALESCE(pm_volume, total_volume, 0) DESC
            {limit_clause};
        """)
        wallets = [r["address"] for r in rows]

    total = len(wallets)
    logger.info(f"Found {total:,} wallets to process for Core Metrics.")

    sem = asyncio.Semaphore(args.concurrency)
    processed = 0
    start_t = time.time()

    async def _worker(addr: str):
        nonlocal processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_core_metrics_for_wallet(conn, addr)
                except Exception as e:
                    logger.error(f"Error computing core metrics for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 1000 == 0 or processed == total:
                        elapsed = time.time() - start_t
                        speed = processed / elapsed if elapsed > 0 else 0
                        logger.info(f"Core Metrics Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/s")

    await asyncio.gather(*[_worker(addr) for addr in wallets])
    logger.info(f"Core Metrics Computation finished in {(time.time() - start_t)/60:.2f} minutes!")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
