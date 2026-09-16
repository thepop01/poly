"""Resolve position condition_ids missing from markets_v2.

Position sync workers write position rows but never market rows, so a large
share of positions (38% of opens, 15% of eligible closed) LEFT JOIN to
nothing and collapse into OTHER/blank taxonomy. This script enumerates
DISTINCT missing condition_ids (open positions first -- live money) and, for
each, fetches one holder-partitioned Data API page (`/positions?user=&market=`,
the documented bounded-partition pattern) to recover the title and event
slug. The slug then goes through the shared Gamma tag + series + title logic
and the row is inserted. Existing rows are never touched
(INSERT ... ON CONFLICT DO NOTHING).

Progress (attempted condition_ids, including unresolvable ones) is appended
to a scratch file so interrupted runs resume; re-running is idempotent.
Category aggregates refresh through Worker B's natural recompute cycle.

Usage:
    python src/scripts/backfill_missing_markets.py --source open --dry-run
    python src/scripts/backfill_missing_markets.py --source open --limit 30000
    python src/scripts/backfill_missing_markets.py --source closed --limit 50000

Markets are attempted highest position value first (opens) or largest
absolute realized PnL first (closed), so limited API throughput links real
money before dust. See learner.md "Backfill concurrency" for the measured
concurrency curve (default 20).
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("backfill_missing_markets")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace(
    "localhost", "127.0.0.1")
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

# Mutable run stats (requests, 429s, inserts). Read by benchmarks and logs.
STATS = {"requests": 0, "rate_limited": 0, "inserts": 0}


def _note_request(resp: aiohttp.ClientResponse) -> None:
    STATS["requests"] += 1
    if resp.status == 429:
        STATS["rate_limited"] += 1


def resolve_market_object(market: dict) -> tuple[str, str, str, str, str]:
    """Resolve one Gamma market object to (title, event_slug, category, subcategory, league)."""
    title = str(market.get("question") or market.get("title") or "")
    events = market.get("events") or []
    event = events[0] if events and isinstance(events[0], dict) else {}
    event_slug = str(event.get("slug") or "")
    tags_raw = event.get("tags", []) if event else []
    tag_labels = [t["label"] for t in tags_raw if isinstance(t, dict) and "label" in t]
    cat, subcat, league = "OTHER", "", ""
    if tag_labels:
        cat, subcat, league = resolve_gamma_tags(tag_labels)
        cat = cat.upper()
    if event and cat in SERIES_LEAGUE_CATEGORIES:
        if not subcat and cat == "ESPORTS":
            subcat = extract_series_subcategory(event)
        if not league:
            league = extract_series_league(event, subcategory=subcat)
    if (cat == "OTHER" or (not subcat and not league)) and title:
        t_cat, t_sub, t_lg = classify_market_title(title)
        if t_cat and t_cat != "OTHER":
            cat = t_cat
            if t_sub:
                subcat = t_sub
            if t_lg:
                league = t_lg
    return title, event_slug, cat or "OTHER", subcat or "", league or ""


async def fetch_partition(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                          holder: str, condition_id: str,
                          endpoint: str = "positions") -> tuple[str, str]:
    """Recover (title, event_slug) for one market via a holder partition.

    Uses the documented bounded-partition pattern (`/positions?user=&market=`,
    falling back to `/closed-positions?user=&market=` for stale local opens).
    Returns ("", "") when no holder row matches or the page fails.
    """
    url = f"{DATA_API_URL}/{endpoint}"
    params = {"user": holder, "market": condition_id, "limit": 10}
    for attempt in range(5):
        try:
            async with sem:
                await asyncio.sleep(0.05)
                async with session.get(url, params=params,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    _note_request(resp)
                    if resp.status == 429:
                        await asyncio.sleep(_backoff(resp, attempt))
                        continue
                    if resp.status != 200:
                        return "", ""
                    data = await resp.json()
                    if not isinstance(data, list):
                        return "", ""
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("conditionId") or "").lower() == condition_id.lower():
                            return (str(row.get("title") or ""),
                                    str(row.get("eventSlug") or ""))
                    return "", ""
        except Exception as e:
            logger.debug(f"Partition fetch error {condition_id[:12]}: {e}")
            await asyncio.sleep(0.5)
    return "", ""


def _backoff(resp: aiohttp.ClientResponse, attempt: int) -> float:
    """Honor Retry-After when present, else exponential backoff with jitter."""
    try:
        retry_after = float(resp.headers.get("Retry-After", "0"))
    except (TypeError, ValueError):
        retry_after = 0.0
    import random
    return max(retry_after, min(30.0, 1.5 * (attempt + 1))) + random.uniform(0, 0.5)


async def fetch_gamma_event(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                            event_slug: str) -> dict:
    """Fetch one Gamma event payload by slug; {} when unavailable."""
    url = f"{GAMMA_API_URL}/events?slug={event_slug}"
    for attempt in range(5):
        try:
            async with sem:
                await asyncio.sleep(0.03)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    _note_request(resp)
                    if resp.status == 429:
                        await asyncio.sleep(_backoff(resp, attempt))
                        continue
                    if resp.status != 200:
                        return {}
                    data = await resp.json()
                    if data and isinstance(data, list) and isinstance(data[0], dict):
                        return data[0]
                    return {}
        except Exception as e:
            logger.debug(f"Gamma fetch error {event_slug}: {e}")
            await asyncio.sleep(0.5)
    return {}


async def resolve_one_market(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                             cid: str, holders: list[str]):
    """Full pipeline for one missing market; (cid, None) when unresolvable.

    Module-level so benchmarks and retries share the exact production path.
    """
    title, slug = "", ""
    seen_holders: set[str] = set()
    for holder in holders[:2]:
        # The two holder picks are often the same wallet; don't pay twice.
        if holder.lower() in seen_holders:
            continue
        seen_holders.add(holder.lower())
        title, slug = await fetch_partition(session, sem, holder, cid, "positions")
        if title or slug:
            break
    if not title and not slug and holders:
        # Stale local open row: the exit usually exists as a closed row.
        title, slug = await fetch_partition(session, sem, holders[0], cid,
                                            "closed-positions")
    if not title and not slug:
        return (cid, None)
    if slug:
        event = await fetch_gamma_event(session, sem, slug)
        if event:
            tags_raw = event.get("tags", [])
            tag_labels = [t["label"] for t in tags_raw
                          if isinstance(t, dict) and "label" in t]
            cat, subcat, league = "OTHER", "", ""
            if tag_labels:
                cat, subcat, league = resolve_gamma_tags(tag_labels)
                cat = cat.upper()
            if cat in SERIES_LEAGUE_CATEGORIES:
                if not subcat and cat == "ESPORTS":
                    subcat = extract_series_subcategory(event)
                if not league:
                    league = extract_series_league(event, subcategory=subcat)
            if cat == "OTHER" or (not subcat and not league):
                t_cat, t_sub, t_lg = classify_market_title(title)
                if t_cat and t_cat != "OTHER":
                    cat = t_cat
                    subcat = subcat or t_sub
                    league = league or t_lg
            return (cid, (title, slug, cat or "OTHER", subcat or "", league or ""))
    # No slug (or dead event): title rules only.
    t_cat, t_sub, t_lg = classify_market_title(title)
    if t_cat and t_cat != "OTHER":
        return (cid, (title, "", t_cat, t_sub, t_lg))
    return (cid, None)


def _progress_path(source: str) -> str:
    return os.path.join("scratch", f"missing_markets_{source}_done.txt")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("open", "closed"), default="open")
    parser.add_argument("--limit", type=int, default=None, help="Max markets to attempt")
    parser.add_argument("--concurrency", type=int, default=20,
                        help="Measured sweet spot is 20 (max 429-free throughput); "
                             "40 roughly doubles speed but draws heavy 429s.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=30,
                                     timeout=60, command_timeout=600)
    try:
        if args.source == "open":
            # Active wallets only: dormant holders' "open" rows are usually
            # stale exits (proven by holder-partition checks), so resolving
            # them burns API budget for dead markets.
            missing_sql = """
                SELECT p.condition_id,
                       MIN(CASE WHEN COALESCE(p.current_value, 0) > 0
                                 AND COALESCE(p.is_resolved, FALSE) = FALSE
                                THEN p.address END) AS open_holder,
                       MIN(p.address) AS any_holder
                FROM wallet_positions_v2 p
                LEFT JOIN markets_v2 m ON m.condition_id = p.condition_id
                JOIN wallets_v2 w ON w.address = p.address
                WHERE m.condition_id IS NULL
                  AND COALESCE(w.is_dormant, FALSE) = FALSE
                GROUP BY p.condition_id
                ORDER BY SUM(COALESCE(p.current_value, 0)) DESC"""
        else:
            missing_sql = """
                SELECT p.condition_id, NULL AS open_holder, MIN(p.address) AS any_holder
                FROM wallet_closed_positions_v2 p
                LEFT JOIN markets_v2 m ON m.condition_id = p.condition_id
                WHERE m.condition_id IS NULL AND COALESCE(p.metrics_eligible, TRUE)
                GROUP BY p.condition_id
                ORDER BY SUM(ABS(COALESCE(p.realized_pnl, 0))) DESC"""
        async with pool.acquire() as conn:
            rows = await conn.fetch(missing_sql)
        # (condition_id, [holders to try]): live open holders first; a stale
        # local open row usually exists as a closed row for the same wallet.
        targets = [(r["condition_id"],
                    [h for h in (r["open_holder"], r["any_holder"]) if h])
                   for r in rows]
        logger.info(f"{len(targets)} distinct missing markets for source={args.source}.")

        done: set[str] = set()
        progress_path = _progress_path(args.source)
        if os.path.exists(progress_path):
            with open(progress_path) as f:
                done = {line.strip().lower() for line in f if line.strip()}
        pending = [(c, h) for c, h in targets if c.lower() not in done]
        if args.limit:
            pending = pending[:args.limit]
        logger.info(f"{len(pending)} pending after progress file ({len(done)} done).")
        if not pending:
            return
        if args.dry_run:
            logger.info(f"Dry run: would attempt {len(pending)} holder-partition resolutions.")
            return

        sem = asyncio.Semaphore(args.concurrency)
        to_insert: list[tuple] = []
        attempted: list[str] = []
        t0 = time.time()

        # aiohttp defaults to 100 total connections: raise the ceiling so the
        # configured semaphore is the actual throttle, not the connector.
        connector = aiohttp.TCPConnector(limit=args.concurrency + 20)
        async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"}, connector=connector) as session:
            batch = 500
            for i in range(0, len(pending), batch):
                chunk = pending[i:i + batch]
                before_429 = STATS["rate_limited"]
                results = await asyncio.gather(
                    *[resolve_one_market(session, sem, cid, holder) for cid, holder in chunk])
                batch_rows = []
                for cid, resolved in results:
                    attempted.append(cid)
                    if resolved is None:
                        continue
                    title, slug, cat, sub, league = resolved
                    batch_rows.append((cid, title[:500] if title else f"Market {cid[:8]}",
                                       cat, sub, league, slug))
                if batch_rows:
                    async with pool.acquire() as conn:
                        await conn.executemany(
                            """INSERT INTO markets_v2
                                   (condition_id, title, category, subcategory, league, event_slug, updated_at)
                               VALUES ($1, $2, $3, $4, $5, $6, NOW())
                               ON CONFLICT (condition_id) DO NOTHING""",
                            batch_rows)
                    to_insert.extend(batch_rows)
                with open(progress_path, "a") as f:
                    f.write("\n".join(cid for cid, _ in chunk) + "\n")
                dt = time.time() - t0
                logger.info(f"Progress {min(i + batch, len(pending))}/{len(pending)} | "
                            f"inserted {len(to_insert)} | {len(to_insert) / dt:.1f}/s | "
                            f"429s {STATS['rate_limited'] - before_429} (total {STATS['rate_limited']}).")
        logger.info(f"Done. Inserted {len(to_insert)} markets, "
                    f"{len(attempted) - len(to_insert)} unresolvable, "
                    f"in {(time.time() - t0) / 60:.1f} min.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
