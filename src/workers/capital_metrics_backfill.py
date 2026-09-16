# src/workers/capital_metrics_backfill.py
"""Capital/deposit synchronization worker.

This worker owns capital/deposit/withdrawal fields only.  Internal accounting
outputs are owned by the canonical metrics coordinator;
Polymarket ``pm_*`` snapshots and Activity API PnL are never used as a
fallback for those fields.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging

from src.utils.alchemy_client import fetch_capital_metrics

logger = logging.getLogger("capital_metrics_backfill")

DB_URL       = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
CONCURRENCY  = int(os.environ.get("CAPITAL_CONCURRENCY", "1"))    # 1 wallet at a time
WALLET_TIMEOUT = int(os.environ.get("CAPITAL_WALLET_TIMEOUT", "120"))

ACTIVITY_API = "https://activity.polymarket-tools.com/api/activity"


async def fetch_activity_deposits_withdrawals(
    session: aiohttp.ClientSession, address: str
) -> tuple[float | None, float | None, float | None]:
    """
    Fetch total deposits and withdrawals from Polymarket's activity tool API.
    Returns (deposits, withdrawals, activity_pnl) or (None, None, None) on failure.

    Activity PnL is retained as a raw observation for diagnostics only.  It is
    deliberately not consumed by ``process_capital_metrics`` for internal ROI.
    """
    payload = {
        "wallets": [address],
        "filters": {
            "types": ["DEPOSIT", "WITHDRAWAL"],
            "side": "ALL",
            "timeRange": "ALL_TIME",
            "sortDirection": "DESC",
        },
    }
    try:
        async with session.post(
            ACTIVITY_API,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15, connect=5, sock_read=10),
        ) as resp:
            if resp.status != 200:
                logger.debug(f"Activity API {resp.status} for {address[:12]}...")
                return None, None, None
            data = await resp.json()
            activities = data.get("activity", [])
            total_pnl = data.get("totalPnl")

            deposits = sum(
                a.get("usdcSize", 0)
                for a in activities
                if a.get("type") == "DEPOSIT"
            )
            withdrawals = sum(
                a.get("usdcSize", 0)
                for a in activities
                if a.get("type") == "WITHDRAWAL"
            )
            return deposits, withdrawals, total_pnl
    except Exception as e:
        logger.debug(f"Activity API error for {address[:12]}: {e}")
        return None, None, None


async def process_capital_metrics(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Synchronize capital fields without touching canonical accounting fields."""
    row = await conn.fetchrow(
        """
        SELECT deposits, withdrawals
        FROM wallet_metrics_v2 WHERE address = $1
        """,
        address,
    )

    # Activity PnL is intentionally ignored: it is an official/activity
    # snapshot, not the eligible position-ledger source for internal ROI.
    act_dep, act_wdw, _activity_pnl = await fetch_activity_deposits_withdrawals(session, address)
    if act_dep is not None:
        deposits = act_dep
        withdrawals = act_wdw or 0.0
    else:
        deposits = float(row["deposits"]) if row and row["deposits"] is not None else 0.0
        withdrawals = float(row["withdrawals"]) if row and row["withdrawals"] is not None else 0.0

    await asyncio.sleep(0.5)

    await conn.execute("""
        INSERT INTO wallet_metrics_v2
            (address, deposits, withdrawals, capital_synced_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (address) DO UPDATE SET
            deposits          = EXCLUDED.deposits,
            withdrawals       = EXCLUDED.withdrawals,
            capital_synced_at = NOW()
    """, address, deposits, withdrawals)

    logger.info(
        f"Done {address[:12]}... dep=${deposits:.0f} wdw=${withdrawals:.0f} "
        "(canonical internal ROI left untouched)"
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
              AND (w.last_trade_at IS NULL OR w.last_trade_at >= NOW() - INTERVAL '7 days')
              AND (m.capital_synced_at IS NULL OR m.capital_synced_at < NOW() - INTERVAL '5 days')
            ORDER BY m.capital_synced_at ASC NULLS FIRST
        """)
        wallets = [r["address"] for r in rows]
        total = len(wallets)
        logger.info(f"Queue: {total} wallets for capital metrics (concurrency={CONCURRENCY}, timeout={WALLET_TIMEOUT}s)")
        if total == 0:
            logger.info("No wallets in queue for capital metrics backfill. Sleeping for 60s...")
            await pool.close()
            await asyncio.sleep(60)
            return

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
