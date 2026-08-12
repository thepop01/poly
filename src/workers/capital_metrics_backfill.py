# src/workers/capital_metrics_backfill.py
"""
Worker 2: Capital Metrics & ROI Backfill
==========================================
Fetches on-chain deposit/withdrawal history and computes ROI
using ONLY the Alchemy API (Polygon RPC).

Runs independently from Worker 1 at low concurrency (default=4)
to respect Alchemy rate limits without affecting Polymarket fetches.

What it writes to wallet_metrics_v2:
  - deposits        (total USDC ever deposited into Polymarket)
  - withdrawals     (total USDC ever withdrawn)
  - peak_capital    (max capital deployed at any point)
  - roi_pct         (total_pnl / peak_capital * 100)
  - capital_synced_at (its own cursor — independent from computed_at)

Worker 1 must have already written total_pnl for roi_pct to be meaningful.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging

from src.utils.alchemy_client import fetch_capital_metrics

logger = logging.getLogger("capital_metrics_backfill")

DB_URL       = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
CONCURRENCY  = int(os.environ.get("CAPITAL_CONCURRENCY", "1"))    # 1 wallet at a time = max 2 Alchemy calls simultaneously
WALLET_TIMEOUT = int(os.environ.get("CAPITAL_WALLET_TIMEOUT", "120"))  # longer — backoff can take up to 30s per retry


async def process_capital_metrics(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Fetch on-chain capital metrics incrementally and update roi_pct in wallet_metrics_v2."""
    # Fetch existing state from DB
    row = await conn.fetchrow(
        """
        SELECT total_pnl, deposits, withdrawals, net_capital, peak_capital, last_capital_block
        FROM wallet_metrics_v2 WHERE address = $1
        """,
        address,
    )
    
    total_pnl = float(row["total_pnl"]) if row and row["total_pnl"] is not None else None
    cur_dep = float(row["deposits"]) if row and row["deposits"] is not None else 0.0
    cur_wdw = float(row["withdrawals"]) if row and row["withdrawals"] is not None else 0.0
    cur_net = float(row["net_capital"]) if row and row["net_capital"] is not None else 0.0
    cur_peak = float(row["peak_capital"]) if row and row["peak_capital"] is not None else 0.0
    last_block = int(row["last_capital_block"]) if row and row["last_capital_block"] is not None else 0

    from_block = last_block + 1 if last_block > 0 else 0

    deposits, withdrawals, peak_capital, net_capital, max_block = await fetch_capital_metrics(
        session,
        address,
        from_block=from_block,
        current_deposits=cur_dep,
        current_withdrawals=cur_wdw,
        current_net_capital=cur_net,
        current_peak_capital=cur_peak,
    )

    if deposits is None and withdrawals is None and peak_capital is None:
        # Alchemy failed — don't write, will be retried next pass
        logger.warning(f"Alchemy returned no data for {address[:12]}... — skipping")
        return

    next_last_block = max(last_block, max_block or 0)

    # ROI = pnl / peak_capital (use deposits as fallback if peak_capital is 0)
    cap = peak_capital if (peak_capital and peak_capital > 0) else (deposits if (deposits and deposits > 0) else None)
    roi_pct = (total_pnl / cap * 100.0) if (total_pnl is not None and cap and cap > 0) else None

    # Small throttle to keep Alchemy requests under rate limit
    await asyncio.sleep(0.5)

    await conn.execute("""
        INSERT INTO wallet_metrics_v2
            (address, deposits, withdrawals, net_capital, peak_capital, roi_pct, last_capital_block, capital_synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT (address) DO UPDATE SET
            deposits          = EXCLUDED.deposits,
            withdrawals       = EXCLUDED.withdrawals,
            net_capital       = EXCLUDED.net_capital,
            peak_capital      = EXCLUDED.peak_capital,
            roi_pct           = EXCLUDED.roi_pct,
            last_capital_block = EXCLUDED.last_capital_block,
            capital_synced_at = NOW()
    """, address, deposits, withdrawals, net_capital, peak_capital, roi_pct, next_last_block)

    logger.info(
        f"Done {address[:12]}... | dep=${deposits or 0:.0f} "
        f"wdw=${withdrawals or 0:.0f} peak=${peak_capital or 0:.0f} roi={roi_pct or 0:.1f}% block={next_last_block}"
    )


async def run_capital_metrics_backfill(db_url: str = DB_URL):
    logger.info(f"=== WORKER 2: CAPITAL METRICS BACKFILL STARTED (CONCURRENCY={CONCURRENCY}) ===")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=CONCURRENCY + 2)
    except Exception as e:
        logger.error(f"DB pool failed: {e}")
        return

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.address
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.is_dormant = FALSE
            ORDER BY m.capital_synced_at ASC NULLS FIRST
        """)
        wallets = [r["address"] for r in rows]
        total = len(wallets)
        logger.info(f"Queue: {total} wallets for capital metrics (concurrency={CONCURRENCY}, timeout={WALLET_TIMEOUT}s)")

    sem = asyncio.Semaphore(CONCURRENCY)
    done, errors = 0, 0

    # Alchemy tolerates persistent connections well — use keepalive
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 3,
        limit_per_host=10,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:

        async def _process_one(addr):
            nonlocal done, errors
            async with sem:
                try:
                    async with pool.acquire() as conn:
                        await asyncio.wait_for(
                            process_capital_metrics(conn, session, addr),
                            timeout=WALLET_TIMEOUT,
                        )
                    done += 1
                except asyncio.TimeoutError:
                    errors += 1
                    logger.warning(f"Timeout {addr[:12]}... ({WALLET_TIMEOUT}s)")
                except Exception as e:
                    errors += 1
                    logger.warning(f"Error {addr[:12]}...: {e}")

                if (done + errors) % 25 == 0 or (done + errors) == total:
                    logger.info(f"Progress: {done+errors}/{total} (ok={done} err={errors})")

        await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)

    logger.info(f"=== WORKER 2 COMPLETE: {done} ok, {errors} errors / {total} ===")
    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(run_capital_metrics_backfill())
