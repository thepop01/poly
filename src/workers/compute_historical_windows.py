"""
Worker C: Historical 10-Window Trade PnL Progression Computer
=============================================================
Computes the 10 rolling trade progression windows from wallet_closed_positions_v2:
- Slices resolved position rows, including concluded-but-unclaimed positions
- Orders contract rows chronologically by closed_at DESC
- Computes pnl_100, pnl_200, pnl_300, pnl_500, pnl_750, pnl_1000, pnl_1500, pnl_2000, pnl_3500
- Keeps pnl_5000 / pnl_all as unscaled position-ledger PnL
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

import asyncpg

logger = logging.getLogger("compute_historical_windows")
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

WINDOWS = [100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000]

def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def _parse_realized_pnl(cp: dict) -> float:
    return _parse(cp.get("realized_pnl") if "realized_pnl" in cp else cp.get("realizedPnl"))

def _pos_close_ts(row: asyncpg.Record) -> float:
    ca = row.get("closed_at")
    if ca:
        try:
            return ca.timestamp()
        except Exception:
            pass
    return 0.0

async def compute_historical_windows_for_wallet(
    conn: asyncpg.Connection,
    address: str,
) -> dict:
    """Calculates the 10 rolling trade progression windows and updates wallet_metrics_v2."""
    # Fetch all resolved position rows. is_redeemable describes settlement
    # state, not whether the row is synthetic; excluding it drops genuine
    # expired losses and unclaimed winners from the historical ledger.
    closed_rows = await conn.fetch("""
        SELECT condition_id, outcome, realized_pnl, closed_at
        FROM wallet_closed_positions_v2
        WHERE address = $1
          AND COALESCE(metrics_eligible, TRUE)
        ORDER BY closed_at DESC NULLS LAST;
    """, address)

    # 2. Fetch total_pnl fallback from wallet_metrics_v2
    m_row = await conn.fetchrow("SELECT total_pnl, pm_pnl FROM wallet_metrics_v2 WHERE address = $1", address)
    tot_pnl = float(m_row["total_pnl"]) if m_row and m_row["total_pnl"] is not None else 0.0

    if not closed_rows:
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, pnl_100, pnl_200, pnl_300, pnl_500, pnl_750, pnl_1000, pnl_1500, pnl_2000, pnl_3500, pnl_5000, computed_at)
            VALUES ($1, $2, $2, $2, $2, $2, $2, $2, $2, $2, $2, NOW())
            ON CONFLICT (address) DO UPDATE SET
                pnl_100 = EXCLUDED.pnl_100,
                pnl_200 = EXCLUDED.pnl_200,
                pnl_300 = EXCLUDED.pnl_300,
                pnl_500 = EXCLUDED.pnl_500,
                pnl_750 = EXCLUDED.pnl_750,
                pnl_1000 = EXCLUDED.pnl_1000,
                pnl_1500 = EXCLUDED.pnl_1500,
                pnl_2000 = EXCLUDED.pnl_2000,
                pnl_3500 = EXCLUDED.pnl_3500,
                pnl_5000 = EXCLUDED.pnl_5000;
        """, address, tot_pnl)
        return {f"pnl_{w}": tot_pnl for w in WINDOWS}

    total_positions = len(closed_rows)
    total_raw_closed_pnl = sum(_parse_realized_pnl(cp) for cp in closed_rows)

    window_pnls = {}
    for w in WINDOWS:
        if w >= total_positions or w == 5000:
            window_pnls[f"pnl_{w}"] = total_raw_closed_pnl
        else:
            slice_positions = closed_rows[:w]
            window_pnls[f"pnl_{w}"] = sum(_parse_realized_pnl(cp) for cp in slice_positions) if slice_positions else 0.0

    window_pnls["pnl_all"] = total_raw_closed_pnl

    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, pnl_100, pnl_200, pnl_300, pnl_500, pnl_750, pnl_1000, pnl_1500, pnl_2000, pnl_3500, pnl_5000, pnl_all, computed_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW()
        )
        ON CONFLICT (address) DO UPDATE SET
            pnl_100 = EXCLUDED.pnl_100,
            pnl_200 = EXCLUDED.pnl_200,
            pnl_300 = EXCLUDED.pnl_300,
            pnl_500 = EXCLUDED.pnl_500,
            pnl_750 = EXCLUDED.pnl_750,
            pnl_1000 = EXCLUDED.pnl_1000,
            pnl_1500 = EXCLUDED.pnl_1500,
            pnl_2000 = EXCLUDED.pnl_2000,
            pnl_3500 = EXCLUDED.pnl_3500,
            pnl_5000 = EXCLUDED.pnl_5000,
            pnl_all = EXCLUDED.pnl_all;
    """, address,
         window_pnls["pnl_100"], window_pnls["pnl_200"], window_pnls["pnl_300"],
         window_pnls["pnl_500"], window_pnls["pnl_750"], window_pnls["pnl_1000"],
         window_pnls["pnl_1500"], window_pnls["pnl_2000"], window_pnls["pnl_3500"],
         window_pnls["pnl_5000"], window_pnls["pnl_all"])

    return window_pnls

async def main():
    parser = argparse.ArgumentParser(description="Worker C: Historical 10-Window Progression Computer")
    parser.add_argument("--concurrency", type=int, default=150, help="Number of concurrent workers")
    parser.add_argument("--wallet", type=str, default=None, help="Specific wallet address to compute")
    parser.add_argument("--limit", type=int, default=None, help="Max wallets to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pool = await asyncpg.create_pool(DB_URL, min_size=10, max_size=args.concurrency)

    if args.wallet:
        async with pool.acquire() as conn:
            res = await compute_historical_windows_for_wallet(conn, args.wallet.lower())
            logger.info(f"Historical windows for {args.wallet}: {res}")
        await pool.close()
        return

    logger.info(f"Fetching active wallets for Historical Windows Compute (Concurrency: {args.concurrency})...")
    async with pool.acquire() as conn:
        limit_clause = f"LIMIT {args.limit}" if args.limit else ""
        rows = await conn.fetch(f"""
            SELECT address FROM wallet_metrics_v2 
            WHERE resolved_count > 0
            ORDER BY COALESCE(pm_volume, total_volume, 0) DESC
            {limit_clause};
        """)
        wallets = [r["address"] for r in rows]

    total = len(wallets)
    logger.info(f"Found {total:,} wallets to process for Historical Windows.")

    sem = asyncio.Semaphore(args.concurrency)
    processed = 0
    start_t = time.time()

    async def _worker(addr: str):
        nonlocal processed
        async with sem:
            async with pool.acquire() as conn:
                try:
                    await compute_historical_windows_for_wallet(conn, addr)
                except Exception as e:
                    logger.error(f"Error computing historical windows for {addr}: {e}")
                finally:
                    processed += 1
                    if processed % 1000 == 0 or processed == total:
                        elapsed = time.time() - start_t
                        speed = processed / elapsed if elapsed > 0 else 0
                        logger.info(f"Historical Windows Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | Speed: {speed:.1f} wallets/s")

    await asyncio.gather(*[_worker(addr) for addr in wallets])
    logger.info(f"Historical Windows Computation finished in {(time.time() - start_t)/60:.2f} minutes!")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
