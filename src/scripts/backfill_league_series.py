"""Backfill blank sports/esports leagues from Gamma series + title rules.

Scope: markets_v2 rows in competition-style categories with a blank league
(plus blank-subcategory Esports rows, where the series names the game).
For rows with an event_slug the Gamma event payload is fetched and the league
comes from tags (canonical) with the event `series` title as fallback
(e.g. "JCL T20"); rows without a slug use only the title classifier. Only
blank leagues are ever filled -- existing values are never overwritten, and
leagues from another subcategory's taxonomy are skipped.

Wallets holding updated markets get their category_stats_v2 recomputed via
Worker B, so the Wallets page league filter and research scopes pick up the
new leagues.

Usage:
    python src/scripts/backfill_league_series.py --subcategory Cricket --dry-run
    python src/scripts/backfill_league_series.py --category ESPORTS --limit 5000
    python src/scripts/backfill_league_series.py --limit 5000 --concurrency 10
"""

import argparse
import asyncio
import logging
import os
import sys
import time

import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.category_classifier import classify_market_title
from src.utils.gamma_tag_resolver import (
    SERIES_LEAGUE_CATEGORIES,
    extract_series_league,
    extract_series_subcategory,
    resolve_gamma_tags,
)
from src.workers.compute_category_stats import compute_category_stats_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("backfill_league_series")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace(
    "localhost", "127.0.0.1")
GAMMA_API_URL = "https://gamma-api.polymarket.com"


async def resolve_league(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                         event_slug: str, title: str,
                         stored_category: str) -> tuple[str, str, str]:
    """Return (category, subcategory, league); ""s when nothing defensible is found."""
    if event_slug:
        url = f"{GAMMA_API_URL}/events?slug={event_slug}"
        for attempt in range(3):
            try:
                async with sem:
                    await asyncio.sleep(0.05)
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 429:
                            await asyncio.sleep(1.0 * (attempt + 1))
                            continue
                        if resp.status != 200:
                            break
                        events = await resp.json()
                        if not events or not isinstance(events, list):
                            break
                        event = events[0] if isinstance(events[0], dict) else {}
                        tags_raw = event.get("tags", [])
                        tag_labels = [t["label"] for t in tags_raw
                                      if isinstance(t, dict) and "label" in t]
                        subcat, league = "", ""
                        cat = ""
                        if tag_labels:
                            cat, subcat, league = resolve_gamma_tags(tag_labels)
                            cat = cat.upper()
                        if event and cat in SERIES_LEAGUE_CATEGORIES:
                            if not subcat and cat == "ESPORTS":
                                subcat = extract_series_subcategory(event)
                            if not league:
                                league = extract_series_league(event, subcategory=subcat)
                        # Never reclassify across top-level categories here;
                        # this script only fills leagues within one category.
                        if cat and cat != stored_category.upper():
                            return "", "", ""
                        return subcat, league, cat
            except Exception as e:
                logger.debug(f"Gamma fetch error {event_slug}: {e}")
                await asyncio.sleep(0.5)
    if title:
        t_cat, subcat, league = classify_market_title(title)
        if t_cat.upper() != stored_category.upper():
            return "", "", ""
        return subcat, league, t_cat.upper()
    return "", "", ""


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max markets to process")
    parser.add_argument("--category", type=str, default="SPORTS")
    parser.add_argument("--subcategory", type=str, default=None, help="Only this subcategory")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=30,
                                     timeout=30, command_timeout=300)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT condition_id, title, event_slug, subcategory
                   FROM markets_v2
                   WHERE category = $1 AND COALESCE(league, '') = ''
                     AND (COALESCE(subcategory, '') <> '' OR $1 = 'ESPORTS')
                     AND ($2::text IS NULL OR subcategory = $2)
                   ORDER BY updated_at ASC NULLS FIRST
                   LIMIT $3""",
                args.category, args.subcategory, args.limit or 1_000_000_000)
        logger.info(f"Found {len(rows)} blank-league {args.category} markets to resolve.")
        if not rows:
            return

        sem = asyncio.Semaphore(args.concurrency)
        resolved: list[tuple[str, str, str]] = []
        skipped_mismatch = 0
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            batch_size = 200
            for i in range(0, len(rows), batch_size):
                chunk = rows[i:i + batch_size]
                found = await asyncio.gather(*[
                    resolve_league(session, sem, r["event_slug"] or "", r["title"] or "",
                                   args.category)
                    for r in chunk
                ])
                for r, (subcat, league, _) in zip(chunk, found):
                    stored = r["subcategory"] or ""
                    # Never attach a league from another subcategory's taxonomy
                    # (e.g. NCAA Football on a Cricket-stored market). A blank
                    # stored subcategory may always be filled (Esports games).
                    if stored and subcat and subcat.upper() != stored.upper():
                        skipped_mismatch += 1
                        logger.debug(f"Skipping {r['condition_id'][:12]}: league {league} "
                                     f"belongs to {subcat}, market is {stored}")
                        continue
                    # Skip only when there is nothing to gain: no league, and
                    # no subcategory fill for a blank stored subcategory.
                    if not league and not (not stored and subcat):
                        continue
                    resolved.append((r["condition_id"], league, subcat))
                logger.info(f"Gamma progress: {min(i + batch_size, len(rows))}/{len(rows)} "
                            f"markets, {len(resolved)} leagues found, "
                            f"{skipped_mismatch} cross-subcategory skipped.")

        logger.info(f"Resolved leagues for {len(resolved)}/{len(rows)} markets "
                      f"({skipped_mismatch} cross-subcategory skipped).")
        if args.dry_run or not resolved:
            if args.dry_run:
                from collections import Counter
                logger.info(f"Dry run league histogram: "
                            f"{Counter(lg for _, lg, _ in resolved if lg).most_common(15)}")
                sub_fills = sum(1 for _, lg, sc in resolved if not lg and sc)
                logger.info(f"Dry run: {len(resolved)} markets would improve "
                            f"({sub_fills} subcategory-only).")
            return

        async with pool.acquire() as conn:
            await conn.executemany(
                """UPDATE markets_v2 SET league = $2,
                          subcategory = CASE WHEN COALESCE(subcategory, '') = ''
                                            THEN COALESCE(NULLIF($3, ''), subcategory)
                                            ELSE subcategory END,
                          updated_at = NOW()
                   WHERE condition_id = $1 AND COALESCE(league, '') = ''""",
                resolved)
        logger.info("markets_v2 leagues updated (blanks only).")

        # Recompute category stats for wallets holding updated markets, in chunks.
        cids = [cid for cid, _, _ in resolved]
        wallet_sem = asyncio.Semaphore(20)
        recomputed = 0
        t0 = time.time()
        for i in range(0, len(cids), batch_size):
            chunk = cids[i:i + batch_size]
            async with pool.acquire() as conn:
                addrs = await conn.fetch(
                    """SELECT DISTINCT address FROM (
                         SELECT address FROM wallet_closed_positions_v2 WHERE condition_id = ANY($1)
                         UNION
                         SELECT address FROM wallet_positions_v2 WHERE condition_id = ANY($1)
                       ) t""", chunk)
            wallets = [r["address"] for r in addrs]

            async def _recompute(addr: str):
                async with wallet_sem:
                    async with pool.acquire() as conn:
                        try:
                            await compute_category_stats_for_wallet(conn, addr)
                        except Exception as e:
                            logger.warning(f"Recompute failed for {addr[:10]}: {e}")

            await asyncio.gather(*[_recompute(a) for a in wallets])
            recomputed += len(wallets)
            dt = time.time() - t0
            logger.info(f"Wallets recomputed: {recomputed} ({recomputed / dt:.1f}/s).")
        logger.info(f"Done. {len(resolved)} markets, {recomputed} wallets in {(time.time() - t0) / 60:.1f} min.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
