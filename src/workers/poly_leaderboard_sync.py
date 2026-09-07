"""
Polymarket Leaderboard Sync Worker

Discovery only. Weekly sync that:
1. Fetches top 5000 wallets from Polymarket ALL leaderboard
2. Fetches top 2000 from SPORTS leaderboard
3. Fetches top 500 from each category leaderboard
4. Adds new wallets to wallets_v2 (source='leaderboard')
5. Stores per-category PnL/volume stats

Curated promotion/demotion is handled by stats_refresher.py
(see docs/CORE_LOGIC.md section 1). This worker no longer promotes.

Runs once per week on Monday at 2 PM UTC.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
import signal
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

POLY_LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"

# Categories to fetch top 100 from
CATEGORIES = [
    "SPORTS", "POLITICS", "CRYPTO", "ESPORTS", "CULTURE",
    "TECH", "FINANCE", "ECONOMICS", "WEATHER", "MENTIONS",
]

# Polymarket leaderboard max 50 per request
PM_PAGE_SIZE = 50
SYNC_DAY = 0  # Monday (0=Mon, 6=Sun)
SYNC_HOUR = 14  # 2 PM UTC


async def fetch_poly_leaderboard(
    session: aiohttp.ClientSession,
    category: str,
    limit: int = 100,
) -> list[dict]:
    """Fetch leaderboard entries from Polymarket Data API."""
    all_entries = []
    offset = 0
    while offset < min(limit, 5000):
        page_limit = min(PM_PAGE_SIZE, limit - offset)
        url = (
            f"{POLY_LEADERBOARD_URL}"
            f"?category={category}&timePeriod=ALL&orderBy=PNL"
            f"&limit={page_limit}&offset={offset}"
        )
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Polymarket API {resp.status} for {category} offset={offset}")
                    break
                data = await resp.json()
                if not isinstance(data, list) or not data:
                    break
                all_entries.extend(data)
                if len(data) < page_limit:
                    break
                offset += page_limit
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Error fetching leaderboard {category}: {e}")
            break
    return all_entries[:limit]


async def add_wallets_to_tracked(
    conn: asyncpg.Connection,
    entries: list[dict],
    source: str,
) -> int:
    """Add leaderboard wallets to wallets_v2. Returns count of new wallets added."""
    added = 0
    for entry in entries:
        address = (entry.get("proxyWallet") or "").lower()
        if not address or len(address) != 42:
            continue
        username = (entry.get("userName") or "").strip()[:255]
        pnl = float(entry.get("pnl") or 0)
        volume = float(entry.get("vol") or 0)
        rank = int(entry.get("rank") or 0)

        exists = await conn.fetchval(
            "SELECT 1 FROM wallets_v2 WHERE address = $1", address
        )
        if exists:
            # Already tracked — update username/rank if better
            await conn.execute("""
                UPDATE wallets_v2 SET
                    username = COALESCE(NULLIF($2, ''), username),
                    updated_at = NOW()
                WHERE address = $1
            """, address, username)
            await conn.execute("""
                INSERT INTO wallet_metrics_v2 (address, pm_pnl, pm_volume, pm_rank, pm_synced_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    pm_pnl = GREATEST(COALESCE(wallet_metrics_v2.pm_pnl, 0), $2),
                    pm_volume = GREATEST(COALESCE(wallet_metrics_v2.pm_volume, 0), $3),
                    pm_rank = $4,
                    pm_synced_at = NOW()
            """, address, pnl, volume, rank)
        else:
            # New wallet from leaderboard.
            await conn.execute("""
                INSERT INTO wallets_v2 (
                    address, username, tier, tier_reason, is_dormant,
                    added_at, next_check_at
                ) VALUES ($1, $2, 'STANDARD', 'leaderboard', FALSE, NOW(), NOW())
                ON CONFLICT (address) DO NOTHING
            """, address, username)
            
            await conn.execute("""
                INSERT INTO wallet_metrics_v2 (address, pm_pnl, pm_volume, pm_rank, pm_synced_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (address) DO NOTHING
            """, address, pnl, volume, rank)

            added += 1
            logger.info(f"New wallet from leaderboard ({source}): {address[:10]}... pnl=${pnl:,.0f} rank={rank}")

        # Always add the leaderboard source
        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, 'leaderboard', $2, NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address, f"Polymarket leaderboard ({source})")

    return added


async def store_category_stats(
    conn: asyncpg.Connection,
    entries: list[dict],
    category: str,
) -> tuple[int, int]:
    """Skip official category snapshots until the separate Task 2 table exists.

    This worker may publish only ``pm_*`` wallet fields; returning zero keeps
    the weekly discovery job safe without destroying existing canonical rows.
    """
    logger.info(
        "Skipping official %s category rows; category_stats_v2 is canonical "
        "and the official snapshot table is deferred to Task 2",
        category,
    )
    return 0, 0


async def run_weekly_sync(pool: asyncpg.Pool | None = None, db_url: str = DB_URL):
    """Main weekly sync entry point."""
    logger.info("Starting Polymarket leaderboard weekly sync...")

    own_pool = False
    if pool is None:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        own_pool = True

    try:
        async with pool.acquire() as conn:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                logger.info("Fetching top 5000 from ALL leaderboard...")
                all_entries = await fetch_poly_leaderboard(session, "OVERALL", limit=5000)
                logger.info(f"Got {len(all_entries)} entries from ALL")

                logger.info("Fetching top 2000 from SPORTS leaderboard...")
                sports_entries = await fetch_poly_leaderboard(session, "SPORTS", limit=2000)
                logger.info(f"Got {len(sports_entries)} entries from SPORTS")

                category_entries = {}
                for cat in CATEGORIES:
                    logger.info(f"Fetching top 500 from {cat} leaderboard...")
                    entries = await fetch_poly_leaderboard(session, cat, limit=500)
                    category_entries[cat] = entries
                    logger.info(f"Got {len(entries)} entries from {cat}")
                    await asyncio.sleep(0.2)

                total_new = 0
                total_new += await add_wallets_to_tracked(conn, all_entries, "ALL top 5000")
                total_new += await add_wallets_to_tracked(conn, sports_entries, "SPORTS top 2000")
                for cat, entries in category_entries.items():
                    total_new += await add_wallets_to_tracked(conn, entries, f"{cat} top 500")
                logger.info(f"Added {total_new} new wallets to wallets_v2")

                upserted, removed = await store_category_stats(conn, sports_entries, "SPORTS")
                logger.info(f"SPORTS: {upserted} upserted, {removed} dropped off")
                for cat, entries in category_entries.items():
                    if cat == "SPORTS":
                        continue
                    upserted, removed = await store_category_stats(conn, entries, cat)
                    logger.info(f"{cat}: {upserted} upserted, {removed} dropped off")
                    await asyncio.sleep(0.1)

                await conn.execute("""
                    UPDATE wallets_v2 SET next_check_at = NOW()
                    WHERE address IN (SELECT address FROM wallet_sources_v2 WHERE source = 'leaderboard')
                    AND next_check_at IS NULL
                    AND added_at > NOW() - INTERVAL '7 days'
                """)
    finally:
        if own_pool and pool:
            await pool.close()

    logger.info("Polymarket leaderboard weekly sync complete.")


def next_weekly_sync_utc(sync_day: int = SYNC_DAY, sync_hour: int = SYNC_HOUR) -> datetime:
    """Calculate the next target day & hour UTC (e.g. Monday 2 PM UTC) from now."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=sync_hour, minute=0, second=0, microsecond=0)
    days_ahead = (sync_day - now.weekday()) % 7
    if days_ahead == 0 and target <= now:
        days_ahead = 7
    target += timedelta(days=days_ahead)
    return target


# ── Standalone runner with shutdown support ──

async def main():
    """Run weekly sync on Monday at 2 PM UTC with graceful shutdown."""
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

    logger.info("Leaderboard sync worker started (weekly Monday 2 PM UTC) - running immediate initial sync...")
    try:
        await run_weekly_sync()
    except Exception as e:
        logger.error(f"Initial leaderboard sync error: {e}", exc_info=True)

    while not shutdown.is_set():
        target = next_weekly_sync_utc()
        wait_seconds = (target - datetime.now(timezone.utc)).total_seconds()
        logger.info(f"Next scheduled sync: {target.isoformat()} ({wait_seconds/3600:.1f}h from now)")
        
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=wait_seconds)
            break
        except asyncio.TimeoutError:
            pass

        try:
            await run_weekly_sync()
        except Exception as e:
            logger.error(f"Leaderboard sync error: {e}", exc_info=True)

    logger.info("Leaderboard sync worker shut down cleanly.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
