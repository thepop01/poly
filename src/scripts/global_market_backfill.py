"""Global Market Backfill Script.

Resolves all missing condition_ids from wallet_closed_positions_v2 via Polymarket CLOB & Gamma APIs,
upserts them into markets_v2 with the 3-tier taxonomy, and recomputes category_stats_v2 for all wallets.
"""

import asyncio
import logging
import os
import sys
import time
from typing import Any
import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.gamma_tag_resolver import resolve_gamma_tags
from src.utils.category_classifier import classify_tags, flatten_subcategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("global_market_backfill")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"


class AdaptiveRateLimiter:
    def __init__(self, initial_concurrency: int = 30, initial_delay: float = 0.01):
        self.concurrency = initial_concurrency
        self.delay = initial_delay
        self.success_streak = 0
        self.rate_limit_hits = 0

    def on_success(self):
        self.success_streak += 1
        if self.success_streak > 500 and self.delay > 0.005:
            self.delay = max(0.005, self.delay * 0.9)
            self.success_streak = 0

    def on_rate_limit(self):
        self.rate_limit_hits += 1
        self.success_streak = 0
        self.delay = min(0.5, self.delay * 2.0 + 0.05)
        logger.warning(f"Rate limit hit ({self.rate_limit_hits})! Increasing delay to {self.delay:.2f}s")


limiter = AdaptiveRateLimiter(initial_concurrency=30, initial_delay=0.01)


async def resolve_single_condition_id(
    session: aiohttp.ClientSession,
    cid: str,
) -> tuple[str, str, str, str, str, str, str]:
    """Look up a condition_id via CLOB API, resolve 3-tier taxonomy.
    
    Returns: (condition_id, title, icon, category, subcategory, league, slug)
    """
    if limiter.delay > 0:
        await asyncio.sleep(limiter.delay)

    title, icon, slug = "", "", ""
    cat, subcat, league = "OTHER", "", ""

    url = f"{CLOB_API_URL}/markets/{cid}"
    for attempt in range(2):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 429:
                    limiter.on_rate_limit()
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if resp.status == 200:
                    limiter.on_success()
                    data = await resp.json()
                    title = data.get("question") or ""
                    tags = data.get("tags") or []
                    slug = data.get("market_slug") or ""
                    icon = data.get("icon") or ""

                    if tags:
                        cat, subcat, league = resolve_gamma_tags(tags)
                        cat = cat.upper()

                    # Fallback to keyword classifier if tags gave OTHER
                    if (not cat or cat == "OTHER") and title:
                        raw_c, raw_s = classify_tags([title])
                        if raw_c and raw_c.upper() != "OTHER":
                            cat = raw_c.upper()
                            subcat = flatten_subcategory(raw_c, raw_s)
                            if cat == "SPORTS" and subcat == "Soccer":
                                t_low = title.lower()
                                s_low = (slug or "").lower()
                                if "fifa" in t_low or "world cup" in t_low or "fifwc" in s_low:
                                    league = "FIFA World Cup"
                                elif "champions league" in t_low or "ucl" in t_low:
                                    league = "UEFA Champions League"
                                elif "premier league" in t_low or "epl" in t_low:
                                    league = "Premier League"
                    break
        except Exception:
            pass

    return (cid, title, icon, cat, subcat, league, slug)


async def run_global_backfill():
    raise RuntimeError(
        "RETIRED_METRIC_REPAIR_NO_DB_ACCESS: global category backfill is retired"
    )
    logger.info("Connecting to database...")
    conn = await asyncpg.connect(DB_URL)
    try:
        logger.info("1. Creating helper indexes if not present...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_closed_pos_cid ON wallet_closed_positions_v2 (condition_id);
            CREATE INDEX IF NOT EXISTS idx_markets_cid ON markets_v2 (condition_id);
        """)

        logger.info("2. Finding unique condition_ids needing market metadata...")
        # Get missing condition_ids from wallet_closed_positions_v2
        # Prioritize condition_ids traded by tracked wallets
        missing_cids = await conn.fetch("""
            SELECT DISTINCT c.condition_id
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.condition_id IS NULL OR m.category IS NULL OR m.category = 'OTHER' OR m.category = ''
        """)
        
        all_cids = [r["condition_id"] for r in missing_cids if r["condition_id"]]
        total_count = len(all_cids)
        logger.info(f"Found {total_count:,} condition_ids to classify and backfill.")

        if not all_cids:
            logger.info("All condition_ids already classified!")
            return

        sem = asyncio.Semaphore(limiter.concurrency)

        async def worker(session: aiohttp.ClientSession, cid: str):
            async with sem:
                return await resolve_single_condition_id(session, cid)

        logger.info(f"3. Resolving market metadata via CLOB/Gamma APIs with concurrency={limiter.concurrency}...")
        batch_size = 1000
        start_time = time.time()
        total_upserted = 0

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            for i in range(0, total_count, batch_size):
                chunk = all_cids[i:i + batch_size]
                tasks = [worker(session, cid) for cid in chunk]
                resolved_batch = await asyncio.gather(*tasks)

                # Upsert into markets_v2
                valid_rows = [r for r in resolved_batch if r[1] or r[3] != "OTHER"]
                if valid_rows:
                    await conn.executemany("""
                        INSERT INTO markets_v2 (
                            condition_id, title, image_url, category, subcategory, league, event_slug, status, updated_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'RESOLVED', NOW())
                        ON CONFLICT (condition_id) DO UPDATE SET
                            title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
                            image_url = COALESCE(NULLIF(EXCLUDED.image_url, ''), markets_v2.image_url),
                            category = EXCLUDED.category,
                            subcategory = EXCLUDED.subcategory,
                            league = EXCLUDED.league,
                            event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug),
                            updated_at = NOW()
                    """, valid_rows)
                    total_upserted += len(valid_rows)

                elapsed = time.time() - start_time
                rate = (i + len(chunk)) / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {min(i + batch_size, total_count):,}/{total_count:,} "
                    f"({(min(i + batch_size, total_count)/total_count*100):.1f}%) | "
                    f"Upserted: {total_upserted:,} | "
                    f"Speed: {rate:.1f} mkts/sec"
                )

        logger.info(f"\nFinished market resolution. Total markets categorized: {total_upserted:,}")

        logger.info("\n4. Recomputing category_stats_v2 across Category, Subcategory, and League tiers for all wallets...")
        
        # Clear category_stats_v2
        await conn.execute("DELETE FROM category_stats_v2;")

        # Insert Category-level
        logger.info("  -> Inserting Category-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                '' AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER')
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        # Insert Subcategory-level
        logger.info("  -> Inserting Subcategory-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.subcategory IS NOT NULL AND m.subcategory != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        # Insert League-level
        logger.info("  -> Inserting League-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                m.league AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.league IS NOT NULL AND m.league != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory, m.league
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        total_stats = await conn.fetchval("SELECT count(*) FROM category_stats_v2;")
        logger.info(f"\n============================================================")
        logger.info(f"SUCCESS! Total category_stats_v2 rows recomputed: {total_stats:,}")
        logger.info(f"============================================================")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_global_backfill())
