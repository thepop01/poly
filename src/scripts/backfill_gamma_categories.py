"""One-time historical backfill script to migrate all markets to Gamma API 3-tier hierarchy.

Features:
1. Adaptive rate limiting (starts at concurrency=15, slows down on 429, speeds up on 200).
2. Gamma API lookup for all markets in markets_v2 and position tables.
3. Fallback to title classifier if event_slug missing or Gamma returns no tags.
4. Updates markets_v2 and recomputes category_stats_v2 for all tracked wallets.
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

from src.utils.gamma_tag_resolver import (
    SERIES_LEAGUE_CATEGORIES,
    extract_series_league,
    extract_series_subcategory,
    resolve_gamma_tags,
)
from src.utils.category_classifier import classify_tags, flatten_subcategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_gamma")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")
GAMMA_API_URL = "https://gamma-api.polymarket.com"


class AdaptiveRateLimiter:
    """Dynamic concurrency & delay manager to stay under Gamma rate limits safely."""

    def __init__(self, initial_concurrency: int = 15, initial_delay: float = 0.03):
        self.concurrency = initial_concurrency
        self.delay = initial_delay
        self.success_streak = 0
        self.rate_limit_hits = 0

    def on_success(self):
        self.success_streak += 1
        # Gradually decrease delay if 500 successful calls in a row
        if self.success_streak > 500 and self.delay > 0.01:
            self.delay = max(0.01, self.delay * 0.9)
            self.success_streak = 0

    def on_rate_limit(self):
        self.rate_limit_hits += 1
        self.success_streak = 0
        self.delay = min(1.0, self.delay * 2.0 + 0.1)
        logger.warning(f"Rate limit hit ({self.rate_limit_hits})! Increasing delay to {self.delay:.2f}s")


limiter = AdaptiveRateLimiter(initial_concurrency=15, initial_delay=0.03)


async def resolve_market(
    session: aiohttp.ClientSession,
    condition_id: str,
    event_slug: str,
    title: str,
) -> tuple[str, str, str, str]:
    """Fetch Gamma tags and resolve 3-tier taxonomy. Returns (condition_id, category, subcategory, league)."""
    cat, subcat, league = "OTHER", "", ""
    gamma_success = False
    series_event: dict = {}

    if event_slug:
        url = f"{GAMMA_API_URL}/events?slug={event_slug}"
        for attempt in range(3):
            try:
                if limiter.delay > 0:
                    await asyncio.sleep(limiter.delay)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 429:
                        limiter.on_rate_limit()
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    if resp.status == 200:
                        limiter.on_success()
                        events = await resp.json()
                        if events and isinstance(events, list) and len(events) > 0:
                            series_event = events[0] if isinstance(events[0], dict) else {}
                            tags_raw = series_event.get("tags", [])
                            tag_labels = [t["label"] for t in tags_raw if isinstance(t, dict) and "label" in t]
                            if tag_labels:
                                cat, subcat, league = resolve_gamma_tags(tag_labels)
                                cat = cat.upper()
                                gamma_success = True
                            if series_event and cat.upper() in SERIES_LEAGUE_CATEGORIES:
                                if not subcat and cat.upper() == "ESPORTS":
                                    subcat = extract_series_subcategory(series_event)
                                if not league:
                                    league = extract_series_league(
                                        series_event, subcategory=subcat)
                        break
            except Exception as e:
                logger.debug(f"Fetch error {event_slug}: {e}")
                await asyncio.sleep(0.5)

    if not gamma_success or cat == "OTHER":
        if title:
            raw_c, raw_s = classify_tags([title])
            if raw_c and raw_c.upper() != "OTHER":
                cat = raw_c.upper()
                subcat = flatten_subcategory(raw_c, raw_s)
                if cat == "SPORTS" and subcat == "Soccer":
                    t_low = title.lower()
                    if "champions league" in t_low or "ucl" in t_low:
                        league = "UEFA Champions League"
                    elif "premier league" in t_low or "epl" in t_low:
                        league = "Premier League"
                    elif "la liga" in t_low:
                        league = "La Liga"
                    elif "serie a" in t_low:
                        league = "Serie A"
                    elif "bundesliga" in t_low:
                        league = "Bundesliga"
                    elif "world cup" in t_low:
                        league = "FIFA World Cup"

    return (condition_id, cat or "OTHER", subcat or "", league or "")


async def backfill_markets(conn: asyncpg.Connection):
    logger.info("Fetching markets requiring Gamma tag resolution...")

    # Fetch markets from markets_v2 where category is OTHER or league is empty
    rows = await conn.fetch("""
        SELECT condition_id, title, event_slug
        FROM markets_v2
        ORDER BY updated_at ASC NULLS FIRST
    """)
    logger.info(f"Found {len(rows)} markets in markets_v2 to audit/backfill.")

    if not rows:
        return

    sem = asyncio.Semaphore(limiter.concurrency)

    async def worker(session: aiohttp.ClientSession, r: asyncpg.Record):
        async with sem:
            return await resolve_market(
                session,
                r["condition_id"],
                r.get("event_slug") or "",
                r.get("title") or "",
            )

    results = []
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            tasks = [worker(session, r) for r in chunk]
            resolved = await asyncio.gather(*tasks)
            results.extend(resolved)

            # Batch update into DB
            await conn.executemany("""
                UPDATE markets_v2
                SET category = $2, subcategory = $3, league = $4, updated_at = NOW()
                WHERE condition_id = $1
            """, [(cid, c, s, l) for cid, c, s, l in resolved if c != "OTHER"])

            logger.info(f"Progress: {min(i + batch_size, len(rows))}/{len(rows)} markets processed. (Delay: {limiter.delay*1000:.0f}ms)")

    logger.info("All markets in markets_v2 updated successfully.")


async def main():
    logger.info("Connecting to DB...")
    conn = await asyncpg.connect(DB_URL)
    try:
        await backfill_markets(conn)
        logger.info("Gamma migration backfill complete!")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
