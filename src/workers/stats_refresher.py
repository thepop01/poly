import asyncio
import asyncpg
import aiohttp
import os
import signal
import logging
from datetime import datetime, timezone, timedelta

from src.workers.wallet_trade_history import fetch_positions, _parse
from src.utils.alchemy_client import (
    fetch_usdc_deposits,
    fetch_usdc_withdrawals,
    alchemy_get_token_balances,
    PUSD_CONTRACT,
)

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

REFRESH_STALE_AFTER_HOURS = 12
BATCH_SIZE = 100
POLL_INTERVAL = 600  # run every 10 minutes

CURATED_MIN_ROI = 30.0
CURATED_MIN_PNL = 10_000.0
CURATED_MIN_RESOLVED = 10

async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
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
    wallets (except source='custom') that no longer qualify. Dormancy does NOT
    demote — the curated list query already filters is_dormant=FALSE."""
    # PROMOTE: active STANDARD wallets meeting the threshold rule.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = 'CURATED',
            tier_reason = 'auto: roi/pnl threshold',
            curated_at = NOW(),
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'STANDARD'
          AND w.is_dormant = FALSE
          AND COALESCE(m.resolved_count, 0) >= $3
          AND (COALESCE(m.roi_pct, 0) > $1 OR COALESCE(m.total_pnl, 0) > $2)
        """,
        CURATED_MIN_ROI, CURATED_MIN_PNL, CURATED_MIN_RESOLVED,
    )

    # DEMOTE: curated, non-custom wallets that fail the rule → canonical tier.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = CASE
                WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) <= 0 THEN
                    CASE WHEN w.last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
                WHEN w.last_trade_at IS NULL THEN 'NEW'
                ELSE 'STANDARD'
            END,
            tier_reason = 'auto: demoted below curated threshold',
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'CURATED'
          AND NOT EXISTS (
              SELECT 1 FROM wallet_sources_v2 s
              WHERE s.address = w.address AND s.source = 'custom'
          )
          AND (
              COALESCE(m.resolved_count, 0) < $3
              OR (COALESCE(m.roi_pct, 0) <= $1 AND COALESCE(m.total_pnl, 0) <= $2)
          )
        """,
        CURATED_MIN_ROI, CURATED_MIN_PNL, CURATED_MIN_RESOLVED,
    )

async def refresh_tracked_wallets(conn: asyncpg.Connection, session: aiohttp.ClientSession):
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=REFRESH_STALE_AFTER_HOURS)
    
    # Auto-hibernate wallets that haven't traded in 30 days
    hibernate_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    await conn.execute("""
        UPDATE wallets_v2
        SET is_dormant = TRUE
        WHERE is_dormant = FALSE AND last_trade_at < $1
    """, hibernate_cutoff)

    # Reverse: wake wallets that traded again (or whose fake last_trade_at
    # was nulled — never-traded is NEW, not dormant)
    await conn.execute("""
        UPDATE wallets_v2
        SET is_dormant = FALSE
        WHERE is_dormant = TRUE
          AND (last_trade_at IS NULL OR last_trade_at >= $1)
    """, hibernate_cutoff)

    # Sweep tiers to the canonical model for every wallet with metrics.
    # CURATED is never auto-demoted; UNCLASSIFIED rows are the vetting
    # queue owned by wallet_trade_history — don't dequeue them here.
    # Model: balance decides the bucket first; NEW = funded ($1k+) but
    # zero trades ever. Discovery date (added_at) is NOT a signal.
    await conn.execute("""
        UPDATE wallets_v2 w
        SET tier = sub.new_tier, tier_reason = 'stats_refresher reclassify', updated_at = NOW()
        FROM (
            SELECT w2.address,
                CASE
                    WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) <= 0 THEN
                        CASE WHEN w2.last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                    WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
                    WHEN w2.last_trade_at IS NULL THEN 'NEW'
                    ELSE 'STANDARD'
                END AS new_tier
            FROM wallets_v2 w2
            JOIN wallet_metrics_v2 m ON m.address = w2.address
            WHERE w2.tier NOT IN ('CURATED', 'UNCLASSIFIED')
        ) sub
        WHERE sub.address = w.address AND sub.new_tier != w.tier
    """)

    # Promote/demote the curated tier on fresh metrics (spec 2026-07-20).
    await sweep_curated_tiers(conn)

    # Fetch active wallets to refresh
    # We prioritize wallets that have never been computed, then stale ones.
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
    logger.info(f"Refreshing {len(wallets)} stale active wallets...")
    refreshed = 0

    for address in wallets:
        try:
            deposits = await fetch_usdc_deposits(session, address)
            withdrawals = await fetch_usdc_withdrawals(session, address)

            positions = await fetch_positions(session, address)
            balance = await fetch_balance(session, address)

            # Compute position_value from open positions
            position_value = 0.0
            for pos in (positions or []):
                curr_val = _parse(pos.get("currentValue"))
                if curr_val > 0:
                    position_value += curr_val

            # Upsert into wallet_metrics_v2
            await conn.execute("""
                INSERT INTO wallet_metrics_v2 (address, balance, deposits, withdrawals, position_value, computed_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    deposits = COALESCE(EXCLUDED.deposits, wallet_metrics_v2.deposits),
                    withdrawals = COALESCE(EXCLUDED.withdrawals, wallet_metrics_v2.withdrawals),
                    position_value = EXCLUDED.position_value,
                    computed_at = NOW()
            """, address, balance, deposits, withdrawals, position_value)

            # Reclassify on fresh numbers (canonical model: DEAD /
            # LOW_BALANCE / NEW / STANDARD; CURATED never auto-demoted,
            # UNCLASSIFIED stays queued for vetting). NEW = funded ($1k+)
            # with zero trades ever; discovery date is not a signal.
            await conn.execute("""
                UPDATE wallets_v2
                SET tier = CASE
                        WHEN $2 <= 0 THEN
                            CASE WHEN last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                        WHEN $2 < 1000 THEN 'LOW_BALANCE'
                        WHEN last_trade_at IS NULL THEN 'NEW'
                        ELSE 'STANDARD'
                    END,
                    tier_reason = 'stats_refresher reclassify',
                    updated_at = NOW()
                WHERE address = $1
                  AND tier NOT IN ('CURATED', 'UNCLASSIFIED')
                  AND tier != CASE
                        WHEN $2 <= 0 THEN
                            CASE WHEN last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                        WHEN $2 < 1000 THEN 'LOW_BALANCE'
                        WHEN last_trade_at IS NULL THEN 'NEW'
                        ELSE 'STANDARD'
                    END
            """, address, balance + position_value)

            refreshed += 1
            logger.info(f"Refreshed {address[:10]}... | pos_val={position_value:.0f} bal={balance:.0f}")
        except Exception as e:
            logger.warning(f"Error refreshing {address[:10]}...: {e}")

        await asyncio.sleep(0.5)

    logger.info(f"Refreshed {refreshed}/{len(wallets)} wallets.")

async def run_stats_refresher(db_url: str = DB_URL):
    logger.info("Starting Stats Refresher worker...")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return

    while True:
        try:
            async with pool.acquire() as conn:
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    await refresh_tracked_wallets(conn, session)
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
