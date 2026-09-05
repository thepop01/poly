# src/workers/market_metadata.py
"""Shared market-metadata upsert for position sync workers.

Position payloads already carry `title` and `eventSlug`; persisting them
into markets_v2 at sync time costs zero extra API calls and stops the
position↔market linkage leak (positions whose condition_id has no market
row collapse into OTHER/blank taxonomy downstream).

Taxonomy comes from the pure title classifier only — no network. Gamma
series enrichment for these rows happens offline via the existing scripts,
which key off the stored event_slug. Existing curated taxonomy is never
overwritten: the conflict clause only fills OTHER/blank slots (same guarded
semantics as the legacy winrate backfiller).
"""

import logging

import asyncpg

from src.utils.category_classifier import classify_market

logger = logging.getLogger("market_metadata")


async def upsert_position_markets(
    conn: asyncpg.Connection, positions: list[dict]
) -> int:
    """Upsert markets_v2 rows for raw Data API position payloads.

    Returns the number of distinct markets written. Rows with neither title
    nor event slug are skipped (nothing linkable to store).
    """
    markets: dict[str, tuple] = {}
    for position in positions:
        condition_id = str(position.get("conditionId") or "")
        if not condition_id:
            continue
        title = str(position.get("title") or "")
        event_slug = str(position.get("eventSlug") or position.get("event_slug") or "")
        if not title and not event_slug:
            continue
        category, subcategory, league = classify_market(title, event_slug)
        markets[condition_id] = (
            condition_id, title, category, subcategory, league, event_slug
        )
    if not markets:
        return 0

    await conn.executemany("""
        INSERT INTO markets_v2 (
            condition_id, title, category, subcategory, league, event_slug, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (condition_id) DO UPDATE SET
            title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
            event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug),
            category = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.category ELSE markets_v2.category END,
            subcategory = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.subcategory ELSE markets_v2.subcategory END,
            league = CASE
                WHEN UPPER(COALESCE(markets_v2.category, 'OTHER')) = 'OTHER'
                  OR (UPPER(markets_v2.category) = 'SPORTS' AND COALESCE(markets_v2.subcategory, '') = '')
                THEN EXCLUDED.league ELSE markets_v2.league END,
            updated_at = NOW()
    """, list(markets.values()))
    return len(markets)
