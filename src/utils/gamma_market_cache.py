"""Async DB-cached Gamma API tag resolution service.

Features:
1. Two-tier caching: Local in-memory dict + PostgreSQL markets_v2.
2. Gamma API lookup via event_slug (authoritative tags).
3. Fallback to category_classifier title regex if Gamma has no tags or fails.
4. Auto-upserts new or updated markets into markets_v2.
"""

import asyncio
import logging
from typing import Any, Optional
import aiohttp
import asyncpg

from src.utils.gamma_tag_resolver import (
    SERIES_LEAGUE_CATEGORIES,
    extract_series_league,
    extract_series_subcategory,
    resolve_gamma_tags,
)
from src.utils.category_classifier import classify_market_title, classify_tags, flatten_subcategory

logger = logging.getLogger("gamma_market_cache")

GAMMA_API_URL = "https://gamma-api.polymarket.com"

# Process-level in-memory cache: condition_id -> (category, subcategory, league)
_MEMORY_CACHE: dict[str, tuple[str, str, str]] = {}
_MAX_MEMORY_CACHE = 20000


async def get_market_tags(
    session: Optional[aiohttp.ClientSession],
    conn: Optional[asyncpg.Connection],
    condition_id: str,
    event_slug: str = "",
    title: str = "",
) -> tuple[str, str, str]:
    """Retrieve (category, subcategory, league) for a market."""
    if not condition_id:
        if title:
            return classify_market_title(title)
        return ("OTHER", "", "")

    # 1. In-memory cache
    if condition_id in _MEMORY_CACHE:
        cached = _MEMORY_CACHE[condition_id]
        if cached[0] and cached[0] != "OTHER" and (cached[1] or cached[2]):
            return cached

    # 2. Database lookup
    if conn:
        try:
            row = await conn.fetchrow(
                "SELECT category, subcategory, league FROM markets_v2 WHERE condition_id = $1",
                condition_id,
            )
            if row and row["category"] and row["category"].upper() != "OTHER" and (row["subcategory"] or row["league"]):
                res = (row["category"], row["subcategory"] or "", row["league"] or "")
                if len(_MEMORY_CACHE) < _MAX_MEMORY_CACHE:
                    _MEMORY_CACHE[condition_id] = res
                return res
        except Exception as e:
            logger.debug(f"DB lookup failed for {condition_id[:12]}: {e}")

    # 3. Gamma API lookup
    cat, subcat, league = "OTHER", "", ""
    gamma_success = False
    series_event: dict = {}

    if event_slug and session:
        try:
            url = f"{GAMMA_API_URL}/events?slug={event_slug}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    events = await resp.json()
                    if events and isinstance(events, list) and len(events) > 0:
                        series_event = events[0] if isinstance(events[0], dict) else {}
                        tags_raw = series_event.get("tags", [])
                        tag_labels = [t["label"] for t in tags_raw if isinstance(t, dict) and "label" in t]
                        if tag_labels:
                            cat, subcat, league = resolve_gamma_tags(tag_labels)
                            cat = cat.upper()
                            gamma_success = True
        except Exception as e:
            logger.debug(f"Gamma API lookup error for slug {event_slug}: {e}")

    # 4. Fallback or enrichment via title classifier
    if not gamma_success or cat == "OTHER" or (not subcat and not league):
        if title:
            t_cat, t_sub, t_lg = classify_market_title(title)
            if t_cat and t_cat != "OTHER":
                cat = t_cat
                if t_sub:
                    subcat = t_sub
                if t_lg:
                    league = t_lg

    # 5. Series fallback: Polymarket series carry competition detail tags
    # lack (e.g. "JCL T20"). New competitions appear automatically; the tag
    # maps only canonicalize known ones. Restricted to competition-style
    # categories -- other categories use per-question series that would
    # pollute filters.
    if series_event and cat.upper() in SERIES_LEAGUE_CATEGORIES:
        if not subcat and cat.upper() == "ESPORTS":
            subcat = extract_series_subcategory(series_event)
        if not league:
            league = extract_series_league(series_event, subcategory=subcat)

    result = (cat or "OTHER", subcat or "", league or "")

    # Save to in-memory cache
    if len(_MEMORY_CACHE) < _MAX_MEMORY_CACHE:
        _MEMORY_CACHE[condition_id] = result

    # Save / Upsert to Database
    if conn and condition_id:
        try:
            await conn.execute("""
                INSERT INTO markets_v2 (condition_id, title, category, subcategory, league, event_slug, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (condition_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    league = EXCLUDED.league,
                    event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug),
                    title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
                    updated_at = NOW()
            """, condition_id, title or f"Market {condition_id[:8]}", cat, subcat, league, event_slug)
        except Exception as e:
            logger.debug(f"Failed to upsert market {condition_id[:12]}: {e}")

    return result


async def batch_get_market_tags(
    session: Optional[aiohttp.ClientSession],
    conn: Optional[asyncpg.Connection],
    items: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """Resolve a list of position items concurrently."""
    tasks = []
    for item in items:
        cid = str(item.get("conditionId") or item.get("condition_id") or "")
        event_slug = str(item.get("eventSlug") or item.get("event_slug") or "")
        title = str(item.get("title") or item.get("market_title") or "")
        tasks.append(get_market_tags(session, conn, cid, event_slug, title))
    return await asyncio.gather(*tasks)
