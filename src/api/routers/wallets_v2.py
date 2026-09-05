"""Wallets router V2 for FastAPI (using new 10-table schema).

Live endpoints fetch directly from Polymarket Data API.
DB-backed endpoints serve from local PostgreSQL tables.
"""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
import aiohttp
import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
import asyncpg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/wallets", tags=["wallets-v2"])

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


def _parse_num(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def _pm_fetch(session: aiohttp.ClientSession, endpoint: str, params: dict, max_items: int = 200000) -> list[dict]:
    all_results: list[dict] = []
    offset = 0
    page_size = 50  # Polymarket Data API maximum limit per request is 50
    max_offset = 200000

    while offset < max_offset and len(all_results) < max_items:
        p = dict(params)
        p["limit"] = str(page_size)
        p["offset"] = str(offset)
        qs = "&".join(f"{k}={v}" for k, v in p.items())
        url = f"{DATA_API}/{endpoint}?{qs}"

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data:
                    break
                if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                    break
                all_results.extend(data)
                if len(data) < page_size:
                    break
                offset += len(data)
        except Exception as e:
            logger.warning(f"PM API {endpoint} error: {e}")
            break

    return all_results


# ── Activity reconciliation evidence ──────────────────────────────

@router.get("/{address}/reconciliation")
async def get_wallet_reconciliation(request: Request, address: str) -> dict[str, Any]:
    """Return the latest conservative Activity-vs-position audit.

    This endpoint exposes evidence and classifications for review. It never
    recomputes or overwrites canonical PnL.
    """
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    clean = address.lower()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (condition_id, outcome)
                condition_id, outcome, classification, comparison_quality,
                db_total_bought, db_avg_buy_price, db_cost_basis, db_realized_pnl,
                activity_buy_shares, activity_buy_usdc, activity_avg_buy_price,
                activity_sell_shares, activity_sell_usdc, activity_avg_sell_price,
                activity_redeem_shares, activity_redeem_usdc,
                activity_split_shares, activity_split_usdc,
                activity_merge_shares, activity_merge_usdc,
                activity_conversion_shares, activity_conversion_usdc,
                activity_reward_usdc, activity_rebate_usdc, activity_yield_usdc,
                activity_net_shares, activity_event_count, activity_distinct_event_count,
                activity_first_event_at, activity_last_event_at,
                acquisition_status, position_recommendation, baseline_complete,
                activity_outcomes
            FROM wallet_position_activity_reconciliations_v2
            WHERE address=$1
            ORDER BY condition_id, outcome, created_at DESC
        """, clean)
        activity_only = await conn.fetch("""
            SELECT DISTINCT ON (condition_id)
                condition_id, event_count, outcomes, has_open_position,
                activity_status, net_shares, buy_cost, average_buy_price,
                current_position_verified, is_redeemable,
                canonical_position_created, last_checked_at
            FROM wallet_activity_only_markets_v2
            WHERE address=$1
            ORDER BY condition_id, created_at DESC
        """, clean)
        state = await conn.fetchrow("""
            SELECT baseline_complete, baseline_start_at, baseline_end_at,
                   last_confirmed_timestamp, last_scan_at, last_audit_id,
                   last_error
            FROM wallet_activity_scan_state_v2 WHERE address=$1
        """, clean)
    def plain(row: asyncpg.Record | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = {}
        for key, value in dict(row).items():
            if isinstance(value, Decimal):
                result[key] = float(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "address": clean,
        "classification_counts": counts,
        "positions": [plain(row) for row in rows],
        "activity_only_markets": [plain(row) for row in activity_only],
        "scan_state": plain(state) if state else None,
    }


# ── Stats ──────────────────────────────────────────────────────────

@router.get("/{address}/stats")
async def get_wallet_stats(request: Request, address: str) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT w.*, m.*
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.address = $1
        """, address.lower())
        
        if not row:
            raise HTTPException(status_code=404, detail="Wallet not found")
            
        # Get top category
        cat = await conn.fetchrow("""
            SELECT category, pnl as category_pnl, volume as category_volume, roi_pct as category_roi
            FROM category_stats_v2
            WHERE address = $1 AND window_size = 0 AND category != 'OVERALL'
            ORDER BY pnl DESC NULLS LAST, volume DESC NULLS LAST LIMIT 1
        """, address.lower())
        
        # Get open positions count
        open_pos_count = await conn.fetchval("""
            SELECT COUNT(*) FROM wallet_positions_v2
            WHERE address = $1 AND COALESCE(current_value, 0) > 0
        """, address.lower())

    result = dict(row)
    result["open_positions_count"] = open_pos_count or 0
    result["open_count"] = open_pos_count or 0

    if result.get("resolved_count") is not None and result.get("winning_count") is not None:
        result["losing_count"] = max(0, int(result["resolved_count"]) - int(result["winning_count"]))
        result["losses_count"] = result["losing_count"]

    if cat:
        result["favourite_category"] = cat["category"]
        result["top_category_pnl"] = cat["category_pnl"]
        result["top_category_roi"] = cat["category_roi"]
        
    return result


@router.get("/{address}/categories")
async def get_wallet_categories(request: Request, address: str) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT category, subcategory, '' AS league,
                   CASE WHEN SUM(resolved_count) > 0
                        THEN SUM(winning_count)::float / SUM(resolved_count) * 100.0
                        ELSE NULL END AS win_rate,
                   SUM(winning_count) AS winning_count,
                   GREATEST(0, SUM(resolved_count) - SUM(winning_count)) AS losing_count,
                   SUM(resolved_count) AS resolved_count,
                   SUM(pnl) AS pnl,
                   SUM(volume) AS volume,
                   CASE WHEN SUM(volume) >= 10.0
                        THEN GREATEST(-100.0, LEAST(SUM(pnl) / SUM(volume) * 100.0, 10000.0))
                        ELSE NULL END AS roi_pct
            FROM category_stats_v2
            WHERE address = $1 AND window_size = 0
            GROUP BY category, subcategory
            ORDER BY
                CASE WHEN category = 'OVERALL' THEN 0 ELSE 1 END,
                pnl DESC NULLS LAST,
                volume DESC NULLS LAST
        """, address.lower())
    return [dict(r) for r in rows]


# ── Trades (live) ──────────────────────────────────────────────────

@router.get("/{address}/trades")
async def get_wallet_trades(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0,
    live: bool = True
) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    results: list[dict[str, Any]] = []
    if pool:
        async with pool.acquire() as conn:
            q = """
                SELECT id AS "trade_id", address AS "wallet_address", tx_hash,
                       title AS "market_title", outcome AS "side",
                       amount_usdc AS "total_size", event_at AS "timestamp"
                FROM wallet_activity_v2
                WHERE address = $1 AND event_type = 'TRADE'
                ORDER BY event_at DESC
            """
            if limit is not None and limit > 0:
                rows = await conn.fetch(q + " LIMIT $2 OFFSET $3", address.lower(), limit, offset)
            else:
                rows = await conn.fetch(q + " OFFSET $2", address.lower(), offset)
            results = [dict(r) for r in rows]
    if not results and live:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            results = await _pm_fetch(session, "trades", {"user": address})
        results.sort(key=lambda t: int(t.get("timestamp", 0) or 0), reverse=True)
        if limit is not None and limit > 0:
            return results[offset:offset + limit]
        elif offset > 0:
            return results[offset:]
    return results


async def _enrich_with_categories(pool, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach category/subcategory/league from markets_v2 or local classification."""
    if not items:
        return items
    cids = list({
        str(p.get("conditionId") or p.get("condition_id") or "")
        for p in items
        if p.get("conditionId") or p.get("condition_id")
    })
    cat_map: dict[str, tuple[str, str, str]] = {}
    if pool and cids:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT condition_id, category, subcategory, league FROM markets_v2 WHERE condition_id = ANY($1)",
                cids,
            )
        cat_map = {r["condition_id"]: (r["category"], r["subcategory"] or "", r["league"] or "") for r in rows}

    from src.utils.category_classifier import classify_market_title
    for p in items:
        cid = str(p.get("conditionId") or p.get("condition_id") or "")
        cat, subcat, league = cat_map.get(cid, (None, None, None))
        if cat and cat.upper() != "OTHER":
            p["category"] = cat
            p["subcategory"] = subcat
            p["league"] = league
        else:
            title = str(p.get("title") or p.get("market_title") or "")
            c, s, l = classify_market_title(title)
            p["category"] = c or "OTHER"
            p["subcategory"] = s or ""
            p["league"] = l or ""

    return items


from collections import OrderedDict
_OUTCOME_TEXT_CACHE: OrderedDict[str, str] = OrderedDict()

def _set_cached_outcome(token_id: str, label: str):
    if len(_OUTCOME_TEXT_CACHE) >= 10000:
        _OUTCOME_TEXT_CACHE.popitem(last=False)
    _OUTCOME_TEXT_CACHE[token_id] = label


def _is_token_id(value: Any) -> bool:
    v = str(value or "")
    return len(v) > 40 and v.isdigit()


_UNRESOLVED_CIDS: OrderedDict[str, int] = OrderedDict()  # cid -> failure count, max 500 entries
_UNRESOLVED_MAX_FAILURES = 3  # permanently skip only after 3 consecutive failures

def _mark_unresolved(cid: str) -> None:
    """Record a failed Gamma lookup. Only permanently skip after _UNRESOLVED_MAX_FAILURES."""
    if len(_UNRESOLVED_CIDS) >= 500:
        # Evict the oldest entry to keep the set bounded
        _UNRESOLVED_CIDS.popitem(last=False)
    _UNRESOLVED_CIDS[cid] = _UNRESOLVED_CIDS.get(cid, 0) + 1

def _is_permanently_unresolved(cid: str) -> bool:
    return _UNRESOLVED_CIDS.get(cid, 0) >= _UNRESOLVED_MAX_FAILURES


async def _fill_missing_titles_outcomes(pool, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve missing titles, slugs, and token-ID outcomes for DB-served rows.

    - Titles: markets_v2 lookup first, then Gamma /markets?condition_id (result cached into markets_v2).
    - Slugs: same lookup — independently of whether title is missing, since a row can have a
             title but an empty event_slug in markets_v2 (e.g. older markets ingested before slug was tracked).
    - Outcomes: Gamma /markets?clob_token_ids=<decimal ids> -> "Yes"/"No" text.
    Results are cached in-process so repeat requests are free.
    """
    if not items or not pool:
        return items

    need_title: list[str] = []
    need_slug: list[str] = []   # CIDs that have a title but no slug — need Gamma lookup for slug only

    for p in items:
        cid = str(p.get("conditionId") or "")
        if not cid:
            continue
        missing_title = not p.get("title") and not p.get("market_title")
        missing_slug = not p.get("slug") and not p.get("eventSlug")

        if missing_title and cid not in need_title and not _is_permanently_unresolved(cid):
            need_title.append(cid)
        elif missing_slug and cid not in need_slug and cid not in need_title and not _is_permanently_unresolved(cid):
            # Has a title but no slug — collect separately so we still do a Gamma hit
            need_slug.append(cid)

        oc = p.get("outcome")
        if _is_token_id(oc):
            oc_str = str(oc)
            if oc_str not in _OUTCOME_TEXT_CACHE:
                if cid not in need_title and not _is_permanently_unresolved(cid):
                    need_title.append(cid)

    # All CIDs we need to do any kind of lookup for
    all_need = need_title + [c for c in need_slug if c not in need_title]

    # Early-out only when nothing at all needs resolution (but still apply cached outcomes)
    if not all_need:
        for p in items:
            oc = p.get("outcome")
            if _is_token_id(oc):
                oc_str = str(oc)
                p["outcome"] = _OUTCOME_TEXT_CACHE.get(oc_str, oc_str)
        return items

    title_map: dict[str, str] = {}
    slug_map: dict[str, str] = {}

    # 1. DB lookup for all CIDs needing title or slug
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT condition_id, title, event_slug FROM markets_v2 WHERE condition_id = ANY($1)",
            all_need,
        )
        for r in rows:
            if r["title"]:
                title_map[r["condition_id"]] = r["title"]
                title_map[r["condition_id"].lower()] = r["title"]
            if r["event_slug"]:
                slug_map[r["condition_id"]] = r["event_slug"]
                slug_map[r["condition_id"].lower()] = r["event_slug"]

    # 2. Gamma fallback for CIDs still missing title OR slug after DB lookup
    unresolved_title = [c for c in need_title if c not in title_map and c.lower() not in title_map and not _is_permanently_unresolved(c)]
    unresolved_slug = [c for c in need_slug if c not in slug_map and c.lower() not in slug_map and not _is_permanently_unresolved(c)]
    gamma_fetch_cids = list(dict.fromkeys(unresolved_title + unresolved_slug))[:50]  # deduplicated, capped

    if gamma_fetch_cids:
        sem = asyncio.Semaphore(15)

        async def fetch_single_gamma(session: aiohttp.ClientSession, cid: str):
            titles: dict[str, str] = {}
            slugs: dict[str, str] = {}
            outcomes: list[tuple[str, str]] = []
            try:
                async with sem:
                    async with session.get(
                        f"{GAMMA_API}/markets?condition_id={cid}",
                        timeout=aiohttp.ClientTimeout(total=4),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, list) and len(data) > 0:
                                for mkt in data:
                                    mcid = mkt.get("conditionId") or cid
                                    t = mkt.get("question") or mkt.get("title") or ""
                                    # Prefer the parent event-level slug (used in polymarket.com/event/<slug>)
                                    # over the market-level slug, since grouped markets share one event page.
                                    mkt_events = mkt.get("events") or []
                                    event_slug = (mkt_events[0].get("slug") or "") if mkt_events else ""
                                    s = event_slug or mkt.get("slug") or ""
                                    if mcid and t:
                                        titles[mcid] = t
                                        titles[mcid.lower()] = t
                                        titles[cid] = t
                                        titles[cid.lower()] = t
                                    if mcid and s:
                                        slugs[mcid] = s
                                        slugs[mcid.lower()] = s
                                        slugs[cid] = s
                                        slugs[cid.lower()] = s
                                    raw_ids = mkt.get("clobTokenIds") or "[]"
                                    raw_outcomes = mkt.get("outcomes") or "[]"
                                    try:
                                        ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
                                        outs = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
                                    except (json.JSONDecodeError, TypeError):
                                        continue
                                    if isinstance(ids, list) and isinstance(outs, list):
                                        for tid, label in zip(ids, outs):
                                            if tid and label:
                                                outcomes.append((str(tid), str(label)))
                            else:
                                _mark_unresolved(cid)
                        else:
                            _mark_unresolved(cid)
            except Exception as e:
                _mark_unresolved(cid)
                logger.debug(f"title/outcome fetch error for {cid}: {e}")
            return titles, slugs, outcomes

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            results = await asyncio.gather(*(fetch_single_gamma(session, c) for c in gamma_fetch_cids))

        # Merge HTTP results (no connection held during I/O), then batch-write once
        for titles, slugs, outcomes in results:
            title_map.update(titles)
            slug_map.update(slugs)
            for tid, label in outcomes:
                _set_cached_outcome(tid, label)

        # Persist newly resolved titles + slugs back to markets_v2
        pending_upserts = []
        seen_upsert_cids: set[str] = set()
        for cid in gamma_fetch_cids:
            t = title_map.get(cid) or title_map.get(cid.lower()) or ""
            s = slug_map.get(cid) or slug_map.get(cid.lower()) or ""
            norm = cid.lower()
            if norm not in seen_upsert_cids and (t or s):
                pending_upserts.append((norm, t, s))
                seen_upsert_cids.add(norm)
        if pending_upserts:
            async with pool.acquire() as wconn:
                await wconn.executemany("""
                    INSERT INTO markets_v2 (condition_id, title, event_slug, category, subcategory)
                    VALUES ($1, $2, $3, 'OTHER', '')
                    ON CONFLICT (condition_id) DO UPDATE SET
                        title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
                        event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug)
                """, pending_upserts)

    # Apply resolved values to every item
    for p in items:
        cid = str(p.get("conditionId") or "")
        if not p.get("title") and not p.get("market_title"):
            t = title_map.get(cid) or title_map.get(cid.lower())
            if t:
                p["title"] = t
        if not p.get("slug") and not p.get("eventSlug"):
            s = slug_map.get(cid) or slug_map.get(cid.lower())
            if s:
                p["slug"] = s
                p["eventSlug"] = s
        oc = p.get("outcome")
        if _is_token_id(oc):
            oc_str = str(oc)
            p["outcome"] = _OUTCOME_TEXT_CACHE.get(oc_str) or (
                "Combo" if "COMBO" in str(p.get("title", "")).upper() or "PARLAY" in str(p.get("title", "")).upper() else oc
            )

    return items

@router.get("/{address}/positions")
async def get_wallet_positions(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0,
    live: bool = True,
    enrich_categories: bool = False,
) -> list[dict[str, Any]]:
    if not live:
        pool = getattr(request.app.state, "pool", None)
        if pool:
            async with pool.acquire() as conn:
                q = """
                    SELECT p.condition_id AS "conditionId", p.outcome, p.size, p.avg_price AS "avgPrice",
                           p.current_value AS "currentValue", p.unrealized_pnl AS "cashPnl",
                           p.entry_at AS "entryAt",
                           m.title AS "title", m.category AS "category", m.subcategory AS "subcategory",
                           m.event_slug AS "slug", m.event_slug AS "eventSlug"
                    FROM wallet_positions_v2 p
                    LEFT JOIN markets_v2 m ON m.condition_id = p.condition_id
                    WHERE p.address = $1
                    ORDER BY p.current_value DESC NULLS LAST
                """
                if limit is not None and limit > 0:
                    rows = await conn.fetch(q + " LIMIT $2 OFFSET $3", address.lower(), limit, offset)
                else:
                    rows = await conn.fetch(q + " OFFSET $2", address.lower(), offset)
                return [dict(r) for r in rows]
        return []

    pool = getattr(request.app.state, "pool", None)
    results: list[dict[str, Any]] = []
    if pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.condition_id AS "conditionId", p.outcome, p.size, p.avg_price AS "avgPrice",
                       p.current_value AS "currentValue", p.unrealized_pnl AS "cashPnl",
                       p.entry_at AS "entryAt",
                       m.title AS "title", m.category AS "category", m.subcategory AS "subcategory",
                       m.event_slug AS "slug", m.event_slug AS "eventSlug"
                FROM wallet_positions_v2 p
                LEFT JOIN markets_v2 m ON m.condition_id = p.condition_id
                WHERE p.address = $1 AND COALESCE(p.current_value, 0) > 0
                ORDER BY p.current_value DESC NULLS LAST
                """,
                address.lower(),
            )
            results = [dict(r) for r in rows]
    if not results:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            results = await _pm_fetch(session, "positions", {"user": address})
        results = [p for p in results if _parse_num(p.get("currentValue")) > 0]
        if pool and results:
            try:
                async with pool.acquire() as conn:
                    pos_tuples = []
                    for p in results:
                        cid = str(p.get("conditionId") or p.get("condition_id") or "")
                        oc = str(p.get("outcome") or "")
                        sz = _parse_num(p.get("size"))
                        avg_p = _parse_num(p.get("avgPrice"))
                        cur_v = _parse_num(p.get("currentValue"))
                        pnl = _parse_num(p.get("cashPnl") or p.get("unrealizedPnl"))
                        is_par = _is_parlay_position(p)
                        if cid:
                            pos_tuples.append((address.lower(), cid, oc, sz, avg_p, cur_v, pnl, is_par))
                    if pos_tuples:
                        await conn.executemany("""
                            INSERT INTO wallet_positions_v2 (address, condition_id, outcome, size, avg_price, current_value, unrealized_pnl, is_parlay, computed_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                            ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
                                size = EXCLUDED.size,
                                avg_price = EXCLUDED.avg_price,
                                current_value = EXCLUDED.current_value,
                                unrealized_pnl = EXCLUDED.unrealized_pnl,
                                is_parlay = EXCLUDED.is_parlay,
                                computed_at = NOW()
                        """, pos_tuples)
            except Exception as e:
                logger.debug(f"Failed to cache live positions: {e}")

    results = [p for p in results if _parse_num(p.get("currentValue")) > 0]
    results = await _fill_missing_titles_outcomes(pool, results)
    if limit is not None and limit > 0:
        results = results[offset:offset + limit]
    elif offset > 0:
        results = results[offset:]
    if enrich_categories:
        results = await _enrich_with_categories(getattr(request.app.state, "pool", None), results)
    return results


# ── Closed Positions (live) ────────────────────────────────────────

def _parse_pos_ts(p: dict) -> float:
    raw = p.get("endDate") or p.get("end_date") or p.get("closed_at") or p.get("resolved_at")
    if isinstance(raw, datetime):
        return raw.timestamp()
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    return 0.0


@router.get("/{address}/closed-positions")
async def get_wallet_closed_positions(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0,
    enrich_categories: bool = False,
) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    results: list[dict[str, Any]] = []
    if pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.condition_id AS "conditionId", c.outcome,
                       c.total_bought AS "totalBought", c.avg_buy_price AS "avgPrice",
                       c.realized_pnl AS "realizedPnl", COALESCE(c.closed_at, c.resolved_at) AS "endDate",
                       COALESCE(c.is_redeemable, FALSE) AS "isRedeemable",
                       COALESCE(c.is_redeemable, FALSE) AS "is_redeemable",
                       m.title AS "title", m.category AS "category", m.subcategory AS "subcategory",
                       m.event_slug AS "slug", m.event_slug AS "eventSlug"
                FROM wallet_closed_positions_v2 c
                LEFT JOIN markets_v2 m ON m.condition_id = c.condition_id
                WHERE c.address = $1
                  AND COALESCE(c.metrics_eligible, TRUE)
                ORDER BY COALESCE(c.closed_at, c.resolved_at) DESC NULLS LAST
                """,
                address.lower(),
            )
            results = [dict(r) for r in rows]
    if not results:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            results = await _pm_fetch(session, "closed-positions", {"user": address})
        results.sort(key=_parse_pos_ts, reverse=True)
    
    if limit is not None and limit > 0:
        results = results[offset:offset + limit]
    elif offset > 0:
        results = results[offset:]

    results = await _fill_missing_titles_outcomes(pool, results)

    if enrich_categories:
        from src.utils.category_classifier import classify_market_title
        for p in results:
            if not p.get("category") or str(p.get("category")).upper() == "OTHER":
                c, s, l = classify_market_title(str(p.get("title") or ""))
                if c and c != "OTHER":
                    p["category"] = c
                    p["subcategory"] = s
                    p["league"] = l
    return results


def _is_parlay_position(pos: dict) -> bool:
    if pos.get("isCombo") is True or pos.get("is_combo") is True or pos.get("is_parlay") is True:
        return True
    cid = str(pos.get("conditionId") or pos.get("condition_id") or "")
    if cid.startswith("0x03") and len(cid) >= 66 and cid.endswith("0000000000"):
        return True
    title = pos.get("title") or pos.get("market_title") or pos.get("market") or ""
    upper = str(title).upper()
    if "COMBO" in upper or "PARLAY" in upper or " AND " in upper:
        return True
    return False


# ── Parlays (Open & Closed Combo Activity) ─────────────────────────

@router.get("/{address}/parlays")
async def get_wallet_parlays(
    request: Request,
    address: str,
    enrich_categories: bool = False,
) -> dict[str, Any]:
    clean_addr = address.lower().strip()
    open_combos: list[dict] = []
    closed_combos: list[dict] = []
    seen_open_cids = set()
    seen_closed_cids = set()

    pool = getattr(request.app.state, "pool", None)

    # 1. DB: wallet_combo_positions
    if pool:
        try:
            async with pool.acquire() as conn:
                db_combos = await conn.fetch("""
                    SELECT * FROM wallet_combo_positions
                    WHERE address = $1
                    ORDER BY first_entry_at DESC NULLS LAST
                """, clean_addr)
                for r in db_combos:
                    cid = r["combo_condition_id"]
                    status = (r["status"] or "").upper()
                    shares = float(r["shares_balance"] or 0)
                    avg_p = float(r["entry_avg_price_usdc"] or 0)
                    cost = float(r["entry_cost_usdc"] or r["total_cost_usdc"] or 0)
                    payout = float(r["realized_payout_usdc"] or 0)
                    legs = r["legs_total"] or 2
                    title = f"Parlay ({legs} Legs) · {cid[:10]}..."

                    if status == "OPEN" and cid not in seen_open_cids:
                        seen_open_cids.add(cid)
                        entry_dt = r["first_entry_at"]
                        open_combos.append({
                            "conditionId": cid,
                            "asset": cid,
                            "title": title,
                            "size": shares,
                            "tokens": shares,
                            "avgPrice": avg_p,
                            "currentValue": cost,
                            "invested": cost,
                            "cashPnl": 0.0,
                            "unrealizedPnl": 0.0,
                            "entryAt": entry_dt.isoformat() if entry_dt else None,
                            "isCombo": True,
                            "category": "Sports",
                            "subcategory": "Sports",
                        })
                    elif status in ("RESOLVED_WIN", "RESOLVED_LOSS") and cid not in seen_closed_cids:
                        seen_closed_cids.add(cid)
                        realized = (payout - cost) if payout > 0 else -cost
                        resolved_dt = r["resolved_at"]
                        closed_combos.append({
                            "conditionId": cid,
                            "asset": cid,
                            "title": title,
                            "size": shares,
                            "totalBought": shares,
                            "tokens": shares,
                            "avgPrice": avg_p,
                            "entryCost": cost,
                            "payout": payout,
                            "realizedPnl": realized,
                            "closedAt": resolved_dt.isoformat() if resolved_dt else None,
                            "endDate": resolved_dt.isoformat() if resolved_dt else None,
                            "entryAt": r["first_entry_at"].isoformat() if r["first_entry_at"] else None,
                            "isCombo": True,
                            "category": "Sports",
                            "subcategory": "Sports",
                        })

                # 2. DB: parlay-flagged open positions
                db_open = await conn.fetch("""
                    SELECT p.condition_id AS "conditionId", p.outcome AS "asset",
                           p.size, p.avg_price AS "avgPrice",
                           p.current_value AS "currentValue", p.unrealized_pnl AS "unrealizedPnl",
                           p.entry_at AS "entryAt",
                           m.title AS "title", m.category AS "category", m.subcategory AS "subcategory",
                           m.event_slug AS "slug", m.event_slug AS "eventSlug"
                    FROM wallet_positions_v2 p
                    LEFT JOIN markets_v2 m ON m.condition_id = p.condition_id
                    WHERE p.address = $1 AND p.is_parlay AND COALESCE(p.current_value, 0) > 0
                    ORDER BY p.current_value DESC NULLS LAST
                """, clean_addr)
                for p in db_open:
                    cid = p["conditionId"]
                    if cid and cid not in seen_open_cids:
                        seen_open_cids.add(cid)
                        tokens = _parse_num(p["size"]) or 0
                        avg_price = _parse_num(p["avgPrice"]) or 0
                        cur_val = _parse_num(p["currentValue"]) or 0
                        entry_dt = p["entryAt"]
                        open_combos.append({
                            "conditionId": cid,
                            "asset": p["asset"] or "",
                            "title": p["title"] or "Parlay Bet",
                            "slug": p["slug"] or "",
                            "eventSlug": p["eventSlug"] or "",
                            "size": tokens,
                            "tokens": tokens,
                            "avgPrice": avg_price,
                            "currentValue": cur_val,
                            "invested": tokens * avg_price if tokens and avg_price else cur_val,
                            "cashPnl": _parse_num(p["unrealizedPnl"]),
                            "unrealizedPnl": _parse_num(p["unrealizedPnl"]),
                            "entryAt": entry_dt.isoformat() if entry_dt else None,
                            "isCombo": True,
                            "category": p["category"] or "Sports",
                            "subcategory": p["subcategory"] or "Sports",
                        })

                # 3. DB: parlay-flagged closed positions
                db_closed = await conn.fetch("""
                    SELECT c.condition_id AS "conditionId", c.outcome AS "asset",
                           c.total_bought AS "totalBought", c.avg_buy_price AS "avgPrice",
                           c.realized_pnl AS "realizedPnl",
                           c.closed_at AS "closedAt", c.resolved_at AS "resolvedAt",
                           COALESCE(c.closed_at, c.resolved_at) AS "endDate",
                           m.title AS "title", m.category AS "category", m.subcategory AS "subcategory",
                           m.event_slug AS "slug", m.event_slug AS "eventSlug"
                    FROM wallet_closed_positions_v2 c
                    LEFT JOIN markets_v2 m ON m.condition_id = c.condition_id
                    WHERE c.address = $1 AND c.is_parlay
                      AND COALESCE(c.metrics_eligible, TRUE)
                    ORDER BY COALESCE(c.closed_at, c.resolved_at) DESC NULLS LAST
                """, clean_addr)
                for cp in db_closed:
                    cid = cp["conditionId"]
                    if cid and cid not in seen_closed_cids:
                        seen_closed_cids.add(cid)
                        tokens = _parse_num(cp["totalBought"]) or 0
                        avg_price = _parse_num(cp["avgPrice"]) or 0
                        entry_cost = tokens * avg_price if tokens and avg_price else 0
                        closed_at_val = cp["closedAt"].isoformat() if cp["closedAt"] else None
                        end_date_val = cp["endDate"].isoformat() if cp["endDate"] else None
                        closed_combos.append({
                            "conditionId": cid,
                            "asset": cp["asset"] or "",
                            "title": cp["title"] or "Parlay Bet",
                            "slug": cp["slug"] or "",
                            "eventSlug": cp["eventSlug"] or "",
                            "size": tokens,
                            "totalBought": tokens,
                            "tokens": tokens,
                            "avgPrice": avg_price,
                            "entryCost": entry_cost,
                            "realizedPnl": _parse_num(cp["realizedPnl"]),
                            "closedAt": closed_at_val,
                            "closed_at": closed_at_val,
                            "endDate": end_date_val,
                            "end_date": end_date_val,
                            "isCombo": True,
                            "category": cp["category"] or "Sports",
                            "subcategory": cp["subcategory"] or "Sports",
                        })
        except Exception as e:
            logger.warning(f"DB parlay query error for {clean_addr}: {e}")

    if enrich_categories and pool:
        open_combos = await _enrich_with_categories(pool, open_combos)
        closed_combos = await _enrich_with_categories(pool, closed_combos)

    return {
        "open_parlays": open_combos,
        "closed_parlays": closed_combos,
    }



# ── PnL Chart (live, from closed-positions) ────────────────────────

@router.get("/{address}/pnl-chart")
async def get_wallet_pnl_chart(request: Request, address: str) -> list[dict[str, Any]]:
    from datetime import datetime

    dated = []
    pool = getattr(request.app.state, "pool", None)
    if pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT COALESCE(closed_at, resolved_at) as closed_at, realized_pnl
                FROM wallet_closed_positions_v2
                WHERE address = $1 
                  AND COALESCE(metrics_eligible, TRUE)
                  AND COALESCE(closed_at, resolved_at) IS NOT NULL 
                  AND realized_pnl IS NOT NULL
                ORDER BY COALESCE(closed_at, resolved_at) ASC
                """,
                address.lower(),
            )
        for r in rows:
            if r["closed_at"] and r["realized_pnl"] is not None:
                dated.append((r["closed_at"].date(), float(r["realized_pnl"])))

    if not dated:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            closed = await _pm_fetch(session, "closed-positions", {"user": address})
        for cp in closed:
            end_date = cp.get("endDate") or cp.get("end_date")
            if end_date:
                try:
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    dated.append((dt.date(), _parse_num(cp.get("realizedPnl", cp.get("cashPnl", 0)))))
                except Exception:
                    pass

    dated.sort(key=lambda x: x[0])
    chart_data = []
    cumulative = 0.0
    for d, pnl in dated:
        cumulative += pnl
        chart_data.append({"date": d.isoformat(), "pnl": round(cumulative, 2)})

    return chart_data


# ── Whales (DB) ────────────────────────────────────────────────────

@router.get("/whales")
async def get_curated_whales(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.address, w.username, m.win_rate, m.roi_pct, m.resolved_count, m.total_volume, m.total_pnl
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE m.win_rate >= 70 AND m.resolved_count >= 20 AND m.total_volume >= 5000
            ORDER BY COALESCE(m.total_pnl, 0) DESC NULLS LAST LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


# ── Deposits (DB) ──────────────────────────────────────────────────

@router.get("/{address}/deposits")
async def get_wallet_deposits(request: Request, address: str, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, address as wallet_address, tx_hash, amount_usdc, event_at as deposited_at
            FROM wallet_activity_v2
            WHERE address = $1 AND event_type = 'DEPOSIT'
            ORDER BY event_at DESC LIMIT $2
        """, address.lower(), limit)
    return [dict(r) for r in rows]


@router.get("/deposit-alerts/recent")
async def get_deposit_alerts(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id, a.address as wallet_address, a.tx_hash, a.amount_usdc, a.event_at as deposited_at,
                   m.total_pnl, m.total_volume
            FROM wallet_activity_v2 a
            LEFT JOIN wallet_metrics_v2 m ON a.address = m.address
            WHERE a.event_type = 'DEPOSIT' AND a.amount_usdc >= 50000
            ORDER BY a.event_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


@router.get("/smart-money-trades")
async def get_smart_money_trades(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id as trade_id, a.address as wallet_address, a.tx_hash, a.title as market_name,
                   a.outcome as side, a.amount_usdc, a.event_at as timestamp,
                   m.total_pnl, m.total_volume
            FROM wallet_activity_v2 a
            LEFT JOIN wallet_metrics_v2 m ON a.address = m.address
            WHERE a.event_type = 'TRADE' AND a.amount_usdc >= 10000
            ORDER BY a.event_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


# ── Funding & P2P Lineage ──────────────────────────────────────────

@router.get("/{address}/funding")
@router.get("/{address}/lineage")
async def get_wallet_funding(address: str, request: Request, limit: int = 500) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    
    clean_addr = address.lower().strip()
    limit = max(1, min(limit, 1000))
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow("""
            SELECT w.address, w.funding_source, w.funded_by, w.transferred_positions_count,
                   fw.username as funder_username, fw.tier as funder_tier
            FROM wallets_v2 w
            LEFT JOIN wallets_v2 fw ON w.funded_by = fw.address
            WHERE w.address = $1
        """, clean_addr)

        inflows = await conn.fetch("""
            SELECT f.id, f.funder_address, f.asset, f.amount, f.amount_usd, f.tx_hash, f.block_number, f.funded_at,
                   w.username as funder_username, w.tier as funder_tier
            FROM wallet_internal_funding_v2 f
            LEFT JOIN wallets_v2 w ON f.funder_address = w.address
            WHERE f.funded_address = $1
            ORDER BY f.funded_at DESC LIMIT $2
        """, clean_addr, limit)

        outflows = await conn.fetch("""
            SELECT f.id, f.funded_address, f.asset, f.amount, f.amount_usd, f.tx_hash, f.block_number, f.funded_at,
                   w.username as funded_username, w.tier as funded_tier
            FROM wallet_internal_funding_v2 f
            LEFT JOIN wallets_v2 w ON f.funded_address = w.address
            WHERE f.funder_address = $1
            ORDER BY f.funded_at DESC LIMIT $2
        """, clean_addr, limit)

        total_received = await conn.fetchval("SELECT SUM(amount_usd) FROM wallet_internal_funding_v2 WHERE funded_address = $1", clean_addr) or 0.0
        total_sent = await conn.fetchval("SELECT SUM(amount_usd) FROM wallet_internal_funding_v2 WHERE funder_address = $1", clean_addr) or 0.0
        total_inflows_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_internal_funding_v2 WHERE funded_address = $1", clean_addr) or 0
        total_outflows_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_internal_funding_v2 WHERE funder_address = $1", clean_addr) or 0

    return {
        "address": clean_addr,
        "funding_source": wallet["funding_source"] if wallet else "cex_deposit",
        "funded_by": wallet["funded_by"] if wallet else None,
        "funder_username": wallet["funder_username"] if wallet else None,
        "funder_tier": wallet["funder_tier"] if wallet else None,
        "transferred_positions_count": wallet["transferred_positions_count"] if wallet else 0,
        "total_funding_received_usd": float(total_received),
        "total_funding_sent_usd": float(total_sent),
        "total_inflows_count": total_inflows_count,
        "total_outflows_count": total_outflows_count,
        "inflows": [dict(r) for r in inflows],
        "outflows": [dict(r) for r in outflows],
    }


@router.get("/{address}/position-transfers")
async def get_wallet_position_transfers(address: str, request: Request, limit: int = 500) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    
    clean_addr = address.lower().strip()
    limit = max(1, min(limit, 1000))
    async with pool.acquire() as conn:
        total_incoming_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_position_transfers_v2 WHERE to_address = $1", clean_addr) or 0
        total_outgoing_count = await conn.fetchval("SELECT COUNT(*) FROM wallet_position_transfers_v2 WHERE from_address = $1", clean_addr) or 0

        incoming = await conn.fetch("""
            SELECT t.id, t.from_address, t.token_id, t.amount, t.condition_id,
                   COALESCE(t.market_name, m.title, 'Outcome Token ' || SUBSTRING(t.token_id, 1, 8)) as market_name,
                   COALESCE(t.outcome, 'YES') as outcome,
                   t.tx_hash, t.block_number, t.transferred_at,
                   w.username as from_username, w.tier as from_tier
            FROM wallet_position_transfers_v2 t
            LEFT JOIN wallets_v2 w ON t.from_address = w.address
            LEFT JOIN markets_v2 m ON t.condition_id = m.condition_id
            WHERE t.to_address = $1
            ORDER BY t.transferred_at DESC LIMIT $2
        """, clean_addr, limit)

        outgoing = await conn.fetch("""
            SELECT t.id, t.to_address, t.token_id, t.amount, t.condition_id,
                   COALESCE(t.market_name, m.title, 'Outcome Token ' || SUBSTRING(t.token_id, 1, 8)) as market_name,
                   COALESCE(t.outcome, 'YES') as outcome,
                   t.tx_hash, t.block_number, t.transferred_at,
                   w.username as to_username, w.tier as to_tier
            FROM wallet_position_transfers_v2 t
            LEFT JOIN wallets_v2 w ON t.to_address = w.address
            LEFT JOIN markets_v2 m ON t.condition_id = m.condition_id
            WHERE t.from_address = $1
            ORDER BY t.transferred_at DESC LIMIT $2
        """, clean_addr, limit)

    return {
        "address": clean_addr,
        "total_incoming_count": total_incoming_count,
        "total_outgoing_count": total_outgoing_count,
        "incoming_count": len(incoming),
        "outgoing_count": len(outgoing),
        "incoming": [dict(r) for r in incoming],
        "outgoing": [dict(r) for r in outgoing],
    }


GAMMA_API = "https://gamma-api.polymarket.com"


@router.get("/market-resolution/{condition_id}")
async def check_market_resolution(condition_id: str) -> dict[str, Any]:
    """Check if a Polymarket market is resolved via the Gamma API.

    Returns { condition_id, resolved: bool, closed: bool, active: bool, title: str|null }.
    """
    url = f"{GAMMA_API}/markets?condition_ids={condition_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail=f"Gamma API returned {resp.status}")
            data = await resp.json()
            if not isinstance(data, list) or not data:
                return {"condition_id": condition_id, "resolved": None, "closed": None, "active": None, "title": None, "error": "Market not found"}
            market = data[0]
            return {
                "condition_id": condition_id,
                "closed": market.get("closed", False),
                "active": market.get("active", False),
                "resolved": market.get("closed", False) and not market.get("active", False),
                "title": market.get("question"),
            }


@router.get("/{address}/resolved-positions")
async def get_resolved_positions(address: str) -> dict[str, Any]:
    """Check a wallet's open positions for ones where the market has concluded.

    Returns positions with redeemable=True (market resolved, payout unclaimed)
    along with their PnL data for win-rate calculation.
    """
    clean_addr = address.strip().lower()

    async with aiohttp.ClientSession() as session:
        all_positions = await _pm_fetch(session, "positions", {"user": clean_addr})

    redeemable = []
    for p in all_positions:
        if not p.get("redeemable", False):
            continue
        realized_pnl = _parse_num(p.get("realizedPnl"))
        cur_val = _parse_num(p.get("currentValue"))
        avg_price = _parse_num(p.get("avgPrice"))
        bought_val = _parse_num(p.get("totalBought"))
        
        actual_bought = bought_val if bought_val > 0 else 0.0
        actual_cost = actual_bought * avg_price if (avg_price > 0 and actual_bought > 0) else 0.0
        is_win = cur_val > 0
        total_pnl = realized_pnl + (cur_val - actual_cost) if is_win else realized_pnl - actual_cost

        redeemable.append({
            "conditionId": p.get("conditionId"),
            "outcome": p.get("outcome"),
            "title": p.get("title"),
            "avgPrice": avg_price,
            "totalBought": bought_val,
            "curPrice": _parse_num(p.get("curPrice")),
            "realizedPnl": realized_pnl,
            "cashPnl": _parse_num(p.get("cashPnl")),
            "totalPnl": total_pnl,
            "is_win": is_win,
        })

    total_open = len(all_positions)
    return {
        "address": clean_addr,
        "total_open_positions": total_open,
        "redeemable_count": len(redeemable),
        "redeemable": redeemable,
    }
