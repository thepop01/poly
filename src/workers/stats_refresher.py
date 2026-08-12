import asyncio
import asyncpg
import aiohttp
import os
import signal
import logging
from datetime import datetime, timezone, timedelta

from src.workers.wallet_trade_history import fetch_positions, _parse
from src.utils.alchemy_client import (
    fetch_capital_metrics,
    alchemy_get_token_balances,
    PUSD_CONTRACT,
)

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

REFRESH_STALE_AFTER_HOURS = 12
# Sized so a full lap over all active wallets (~9-12k) completes well inside
# the 12h staleness window: 1000/batch at concurrency 8 ≈ 2k+ wallets/hour.
# Hibernated wallets are NOT refreshed proactively: trade_tracker catches any
# new trade in real-time → dormancy sweep auto-wakes the wallet → it then
# falls back into the normal 12h active refresh queue.
BATCH_SIZE = 1000
WALLET_CONCURRENCY = 8
POLL_INTERVAL = 300  # run every 5 minutes

CURATED_MIN_ROI = 30.0
CURATED_MIN_PNL = 10_000.0
CURATED_MIN_WIN_RATE = 70.0

async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float | None:
    try:
        b = await alchemy_get_token_balances(session, address, [PUSD_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance for {address}: {e}")
    return 0.0

async def sweep_curated_tiers(conn: asyncpg.Connection):
    """Promote qualifying active STANDARD wallets to CURATED; demote curated
    wallets (except source='custom') that no longer qualify.

    Qualification Rule (spec 2026-08-10):
    PnL > $10,000 AND (ROI > 30% OR Win Rate > 70%)
    """
    # PROMOTE: active STANDARD wallets meeting the threshold rule.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = 'CURATED',
            tier_reason = 'auto: pnl>10k AND (roi>30% OR win_rate>70%)',
            curated_at = NOW(),
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'STANDARD'
          AND w.is_dormant = FALSE
          AND COALESCE(m.total_pnl, 0) > 10000
          AND (COALESCE(m.roi_pct, 0) > 30 OR COALESCE(m.win_rate, 0) > 70)
        """
    )

    # DEMOTE: curated wallets that no longer meet either condition -> demote tag.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = CASE
                WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
                WHEN w.last_trade_at IS NULL THEN 'NEW'
                ELSE 'STANDARD'
            END,
            is_dormant = CASE
                WHEN w.last_trade_at IS NULL OR w.last_trade_at < NOW() - INTERVAL '30 days' THEN TRUE
                ELSE FALSE
            END,
            tier_reason = 'auto: fails pnl>10k AND (roi>30% OR win_rate>70%)',
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'CURATED'
          AND (
              COALESCE(m.total_pnl, 0) <= 10000
              OR (COALESCE(m.roi_pct, 0) <= 30 AND COALESCE(m.win_rate, 0) <= 70)
          )
        """
    )

async def refresh_tracked_wallets(pool: asyncpg.Pool, session: aiohttp.ClientSession):
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=REFRESH_STALE_AFTER_HOURS)

    async with pool.acquire() as conn:
        # Auto-hibernate wallets that haven't traded in 30 days
        hibernate_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        
        # 1. Demote dormant CURATED wallets to PREVIOUSLY_CURATED and set is_dormant = TRUE
        await conn.execute("""
            UPDATE wallets_v2
            SET tier = 'PREVIOUSLY_CURATED', is_dormant = TRUE, updated_at = NOW()
            WHERE tier = 'CURATED' AND is_dormant = FALSE AND last_trade_at < $1
        """, hibernate_cutoff)

        # 2. Hibernate dormant STANDARD / LOW_BALANCE / NEW wallets
        await conn.execute("""
            UPDATE wallets_v2
            SET is_dormant = TRUE, updated_at = NOW()
            WHERE tier IN ('STANDARD', 'LOW_BALANCE', 'NEW') AND is_dormant = FALSE AND (last_trade_at IS NULL OR last_trade_at < $1)
        """, hibernate_cutoff)

        # 3. Wake up PREVIOUSLY_CURATED wallets when they trade again -> promote directly to CURATED
        await conn.execute("""
            UPDATE wallets_v2
            SET tier = 'CURATED', is_dormant = FALSE, updated_at = NOW()
            WHERE tier = 'PREVIOUSLY_CURATED'
              AND last_trade_at >= $1
        """, hibernate_cutoff)

        # 4. Wake up STANDARD / LOW_BALANCE / NEW wallets when they trade again
        await conn.execute("""
            UPDATE wallets_v2
            SET is_dormant = FALSE, updated_at = NOW()
            WHERE is_dormant = TRUE AND tier != 'PREVIOUSLY_CURATED'
              AND last_trade_at >= $1
        """, hibernate_cutoff)

        # Sweep tiers to the canonical model for every wallet with metrics.
        # CURATED and PREVIOUSLY_CURATED are never auto-demoted to STANDARD/LOW_BALANCE.
        await conn.execute("""
            UPDATE wallets_v2 w
            SET tier = sub.new_tier,
                is_dormant = sub.new_is_dormant,
                tier_reason = 'stats_refresher reclassify',
                updated_at = NOW()
            FROM (
                SELECT w2.address,
                    CASE
                        WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
                        WHEN w2.last_trade_at IS NULL THEN 'NEW'
                        ELSE 'STANDARD'
                    END AS new_tier,
                    CASE
                        WHEN w2.last_trade_at IS NULL OR w2.last_trade_at < NOW() - INTERVAL '30 days' THEN TRUE
                        ELSE FALSE
                    END AS new_is_dormant
                FROM wallets_v2 w2
                LEFT JOIN wallet_metrics_v2 m ON w2.address = m.address
                WHERE w2.tier NOT IN ('CURATED', 'PREVIOUSLY_CURATED')
            ) sub
            WHERE w.address = sub.address AND (w.tier IS DISTINCT FROM sub.new_tier OR w.is_dormant IS DISTINCT FROM sub.new_is_dormant)
        """)

        # Promote/demote the curated tier on fresh metrics (spec 2026-07-20).
        await sweep_curated_tiers(conn)

        # Fetch only active wallets stale past the 12-hour window.
        # Hibernated wallets are NOT refreshed proactively — when they trade,
        # trade_tracker updates last_trade_at, the dormancy sweep wakes them up
        # (is_dormant = FALSE), and they re-enter this queue automatically.
        rows = await conn.fetch(
            """
            SELECT w.address
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.is_dormant = FALSE
              AND (m.computed_at IS NULL OR m.computed_at < $1)
            ORDER BY m.computed_at ASC NULLS FIRST
            LIMIT $2
            """,
            stale_cutoff, BATCH_SIZE,
        )

    if not rows:
        logger.info("No stale active wallets to refresh.")
        return

    wallets = [r["address"] for r in rows]
    logger.info(f"Refreshing {len(wallets)} stale active wallets (concurrency={WALLET_CONCURRENCY})...")
    refreshed = 0
    errors = 0
    sem = asyncio.Semaphore(WALLET_CONCURRENCY)

    async def _refresh_one(address: str):
        nonlocal refreshed, errors
        async with sem:
            try:
                async with pool.acquire() as rconn:
                    crow = await rconn.fetchrow(
                        "SELECT deposits, withdrawals, net_capital, peak_capital, last_capital_block FROM wallet_metrics_v2 WHERE address = $1", address
                    )

                cur_dep = float(crow["deposits"]) if crow and crow["deposits"] is not None else 0.0
                cur_wdw = float(crow["withdrawals"]) if crow and crow["withdrawals"] is not None else 0.0
                cur_net = float(crow["net_capital"]) if crow and crow["net_capital"] is not None else 0.0
                cur_peak = float(crow["peak_capital"]) if crow and crow["peak_capital"] is not None else 0.0
                last_block = int(crow["last_capital_block"]) if crow and crow["last_capital_block"] is not None else 0
                from_block = last_block + 1 if last_block > 0 else 0

                deposits, withdrawals, peak_capital, net_capital, max_block = await fetch_capital_metrics(
                    session, address, from_block=from_block, current_deposits=cur_dep, current_withdrawals=cur_wdw, current_net_capital=cur_net, current_peak_capital=cur_peak
                )

                positions = await fetch_positions(session, address)
                balance = await fetch_balance(session, address)
                next_last_block = max(last_block, max_block or 0)

                # Compute position_value from open positions
                position_value = 0.0
                for pos in (positions or []):
                    curr_val = _parse(pos.get("currentValue"))
                    if curr_val > 0:
                        position_value += curr_val

                async with pool.acquire() as wconn:
                    # Upsert into wallet_metrics_v2
                    await wconn.execute("""
                        INSERT INTO wallet_metrics_v2 (address, balance, deposits, withdrawals, net_capital, peak_capital, position_value, last_capital_block, computed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                        ON CONFLICT (address) DO UPDATE SET
                            balance = EXCLUDED.balance,
                            deposits = COALESCE(EXCLUDED.deposits, wallet_metrics_v2.deposits),
                            withdrawals = COALESCE(EXCLUDED.withdrawals, wallet_metrics_v2.withdrawals),
                            net_capital = COALESCE(EXCLUDED.net_capital, wallet_metrics_v2.net_capital),
                            peak_capital = COALESCE(EXCLUDED.peak_capital, wallet_metrics_v2.peak_capital),
                            position_value = EXCLUDED.position_value,
                            last_capital_block = EXCLUDED.last_capital_block,
                            computed_at = NOW()
                    """, address, balance, deposits, withdrawals, net_capital, peak_capital, position_value, next_last_block)

                    # Reclassify on fresh numbers (canonical model:
                    # LOW_BALANCE / NEW / STANDARD; CURATED never auto-demoted,
                    # UNCLASSIFIED stays queued for vetting).
                    tot_cap = (balance or 0.0) + position_value
                    await wconn.execute("""
                        UPDATE wallets_v2
                        SET tier = CASE
                                WHEN $2 < 1000 THEN 'LOW_BALANCE'
                                WHEN last_trade_at IS NULL THEN 'NEW'
                                ELSE 'STANDARD'
                            END,
                            is_dormant = CASE
                                WHEN last_trade_at IS NULL OR last_trade_at < NOW() - INTERVAL '30 days' THEN TRUE
                                ELSE FALSE
                            END,
                            tier_reason = 'stats_refresher reclassify',
                            updated_at = NOW()
                        WHERE address = $1
                          AND tier NOT IN ('CURATED', 'UNCLASSIFIED')
                    """, address, tot_cap)

                refreshed += 1
            except Exception as e:
                errors += 1
                logger.warning(f"Error refreshing {address[:10]}...: {e}")
            if (refreshed + errors) % 100 == 0:
                logger.info(f"Refresh progress: {refreshed + errors}/{len(wallets)} (ok={refreshed} err={errors})")

    await asyncio.gather(*[_refresh_one(a) for a in wallets])

    logger.info(f"Refreshed {refreshed}/{len(wallets)} wallets ({errors} errors).")

async def run_stats_refresher(db_url: str = DB_URL):
    logger.info("Starting Stats Refresher worker...")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=WALLET_CONCURRENCY + 2)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return

    while True:
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                await refresh_tracked_wallets(pool, session)
        except Exception as e:
            logger.error(f"Stats refresher error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

async def main():
    shutdown = asyncio.Event()

    def _handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except NotImplementedError:
            pass

    logger.info(f"Starting Stats Refresher (interval={POLL_INTERVAL}s)")
    while not shutdown.is_set():
        try:
            await run_stats_refresher()
        except Exception:
            logger.exception("Error in stats refresher loop")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass

    logger.info("Stats Refresher shut down cleanly")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
