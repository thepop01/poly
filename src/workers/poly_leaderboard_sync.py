"""
Polymarket Leaderboard Sync Worker

Weekly sync that:
1. Fetches top 5000 wallets from Polymarket ALL leaderboard
2. Fetches top 2000 from SPORTS leaderboard
3. Fetches top 500 from each category leaderboard
4. Adds new wallets to wallets_v2 (source='leaderboard')
5. Checks curated conditions for category top-5000
6. Promotes qualified wallets to curated list

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
                INSERT INTO wallet_metrics_v2 (address, pm_pnl, pm_volume, pm_rank, computed_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    pm_pnl = GREATEST(COALESCE(wallet_metrics_v2.pm_pnl, 0), $2),
                    pm_volume = GREATEST(COALESCE(wallet_metrics_v2.pm_volume, 0), $3),
                    pm_rank = $4,
                    computed_at = NOW()
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
                INSERT INTO wallet_metrics_v2 (address, pm_pnl, pm_volume, pm_rank, computed_at)
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
    """Store per-category PnL/volume and remove wallets that dropped off.
    Returns (upserted, removed) counts."""
    current_addresses = set()
    upserted = 0
    for entry in entries:
        address = (entry.get("proxyWallet") or "").lower()
        if not address or len(address) != 42:
            continue
        pnl = float(entry.get("pnl") or 0)
        volume = float(entry.get("vol") or 0)
        if pnl == 0 and volume == 0:
            continue

        current_addresses.add(address)
        await conn.execute("""
            INSERT INTO category_stats_v2 (address, category, subcategory, window_size, pnl, volume, computed_at)
            VALUES ($1, $2, '', 0, $3, $4, NOW())
            ON CONFLICT (address, category, subcategory, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                computed_at = NOW()
        """, address, category, pnl, volume)
        upserted += 1

    # Remove wallets no longer in this category's leaderboard
    removed = await conn.execute("""
        DELETE FROM category_stats_v2
        WHERE category = $1 AND subcategory = '' AND window_size = 0
        AND address NOT IN (SELECT unnest($2::text[]))
    """, category, list(current_addresses)) if current_addresses else 0
    # Parse "DELETE N" from result
    removed_count = int(removed.split()[-1]) if removed and removed.startswith("DELETE") else 0

    return upserted, removed_count


async def check_and_promote_curated(
    conn: asyncpg.Connection,
    entries: list[dict],
    category: str,
) -> int:
    """Check if leaderboard top-100 wallets qualify for curated. Returns count promoted."""
    promoted = 0
    for entry in entries[:100]:
        address = (entry.get("proxyWallet") or "").lower()
        if not address or len(address) != 42:
            continue

        # Check if wallet is tracked and has stats
        row = await conn.fetchrow("""
            SELECT w.address, w.tier, w.is_dormant, wm.balance,
                   wm.resolved_count, wm.win_rate, wm.roi_pct, wm.total_pnl
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 wm ON w.address = wm.address
            WHERE w.address = $1
        """, address)

        if not row:
            continue
        if row["tier"] == 'CURATED':
            continue
        if row["is_dormant"]:
            continue

        # Curated conditions: global OR per-category
        resolved = row["resolved_count"] or 0
        win_rate = float(row["win_rate"] or 0)
        roi = float(row["roi_pct"] or 0)
        pnl = float(row["total_pnl"] or 0)

        qualifies = (
            roi > 30
            or float(row["balance"] or 0) > 5_000
            or pnl > 10_000
        )

        # Also check per-category stats
        if not qualifies:
            cat_row = await conn.fetchrow("""
                SELECT pnl, win_rate, roi_pct, volume
                FROM category_stats_v2
                WHERE address = $1 AND category ILIKE $2 AND subcategory = '' AND window_size = 0
            """, address, category)
            if cat_row:
                cat_vol = float(cat_row["volume"] or 0)
                cat_pnl = float(cat_row["pnl"] or 0)
                cat_roi = float(cat_row["roi_pct"] or 0)
                cat_wr = float(cat_row["win_rate"] or 0)
                if cat_vol >= 5_000 and (cat_roi > 30 or cat_wr > 0.60 or cat_pnl > 5_000):
                    qualifies = True

        if qualifies:
            await conn.execute("""
                UPDATE wallets_v2 SET
                    tier = 'CURATED',
                    curated_at = NOW(),
                    last_checked_for_curated = NOW()
                WHERE address = $1 AND tier != 'CURATED'
            """, address)
            promoted += 1
            logger.info(f"Promoted to curated from leaderboard ({category}): {address[:10]}...")

        # Always update last_checked_for_curated
        await conn.execute(
            "UPDATE wallets_v2 SET last_checked_for_curated = NOW() WHERE address = $1",
            address,
        )

    return promoted


async def run_weekly_sync(db_url: str = DB_URL):
    """Main weekly sync entry point."""
    logger.info("Starting Polymarket leaderboard weekly sync...")
    conn = await asyncpg.connect(db_url)

    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            # 1. Fetch top 5000 from ALL
            logger.info("Fetching top 5000 from ALL leaderboard...")
            all_entries = await fetch_poly_leaderboard(session, "OVERALL", limit=5000)
            logger.info(f"Got {len(all_entries)} entries from ALL")

            # 2. Fetch top 2000 from SPORTS
            logger.info("Fetching top 2000 from SPORTS leaderboard...")
            sports_entries = await fetch_poly_leaderboard(session, "SPORTS", limit=2000)
            logger.info(f"Got {len(sports_entries)} entries from SPORTS")

            # 3. Fetch top 500 from each category
            category_entries = {}
            for cat in CATEGORIES:
                logger.info(f"Fetching top 500 from {cat} leaderboard...")
                entries = await fetch_poly_leaderboard(session, cat, limit=500)
                category_entries[cat] = entries
                logger.info(f"Got {len(entries)} entries from {cat}")
                await asyncio.sleep(0.2)

            # 4. Add all to wallets_v2
            total_new = 0
            total_new += await add_wallets_to_tracked(conn, all_entries, "ALL top 5000")
            total_new += await add_wallets_to_tracked(conn, sports_entries, "SPORTS top 2000")
            for cat, entries in category_entries.items():
                total_new += await add_wallets_to_tracked(conn, entries, f"{cat} top 500")
            logger.info(f"Added {total_new} new wallets to wallets_v2")

            # 4b. Store per-category PnL/volume in wallet_category_stats
            #     SPORTS uses the full 2000 entries; other categories use their top 500
            upserted, removed = await store_category_stats(conn, sports_entries, "SPORTS")
            logger.info(f"SPORTS: {upserted} upserted, {removed} dropped off")
            for cat, entries in category_entries.items():
                if cat == "SPORTS":
                    continue
                upserted, removed = await store_category_stats(conn, entries, cat)
                logger.info(f"{cat}: {upserted} upserted, {removed} dropped off")
                await asyncio.sleep(0.1)

            # 5. Check curated conditions for category top-100
            total_promoted = 0
            for cat, entries in category_entries.items():
                promoted = await check_and_promote_curated(conn, entries, cat)
                total_promoted += promoted
            logger.info(f"Promoted {total_promoted} wallets to curated")

            # 6. Set next_check_at = NOW() for new wallets so stats worker picks them up
            await conn.execute("""
                UPDATE wallets_v2 SET next_check_at = NOW()
                WHERE address IN (SELECT address FROM wallet_sources_v2 WHERE source = 'leaderboard')
                AND next_check_at IS NULL
                AND added_at > NOW() - INTERVAL '7 days'
            """)

    finally:
        await conn.close()

    logger.info("Polymarket leaderboard weekly sync complete.")


def next_monday_2pm_utc() -> datetime:
    """Calculate the next Monday 2 PM UTC from now."""
    now = datetime.now(timezone.utc)
    days_until_monday = (SYNC_DAY - now.weekday()) % 7
    if days_until_monday == 0 and now.hour >= SYNC_HOUR:
        days_until_monday = 7
    target = now.replace(hour=SYNC_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
    return target


# ── Standalone runner with shutdown support ──

async def main():
    """Run sync every Monday 2 PM UTC with graceful shutdown."""
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

    logger.info("Leaderboard sync worker started (Monday 2 PM UTC)")
    while not shutdown.is_set():
        target = next_monday_2pm_utc()
        wait_seconds = (target - datetime.now(timezone.utc)).total_seconds()
        logger.info(f"Next sync: {target.isoformat()} ({wait_seconds/3600:.1f}h from now)")
        
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

    logger.info("Leaderboard sync worker shut down cleanly.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
