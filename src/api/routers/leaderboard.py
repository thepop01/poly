"""Leaderboard router for FastAPI.

Two sections:
  - /leaderboard/global   → all discovered wallets (deposits + trades), no filters
  - /leaderboard/curated  → filtered subset based on conditions (win rate, ROI, etc.)

Category filter: when a category is specified (SPORTS, POLITICS, etc.), the endpoint
fetches directly from Polymarket's /v1/leaderboard API for that category.
"""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
import time
import aiohttp
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

_cache: dict[str, dict] = {}
CACHE_TTL = 60

DATA_API = "https://data-api.polymarket.com"

VALID_CATEGORIES = {
    "OVERALL", "POLITICS", "SPORTS", "ESPORTS", "CRYPTO",
    "CULTURE", "WEATHER", "ECONOMICS", "TECH", "FINANCE", "MENTIONS", "OTHER",
}


async def _fetch_pm_leaderboard(
    category: str = "OVERALL",
    time_period: str = "ALL",
    order_by: str = "PNL",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Fetch from Polymarket's public /v1/leaderboard endpoint."""
    params = {
        "category": category,
        "timePeriod": time_period,
        "orderBy": order_by,
        "limit": str(limit),
        "offset": str(offset),
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{DATA_API}/v1/leaderboard?{qs}"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                if not isinstance(data, list):
                    return []
                return data
    except Exception as e:
        logger.warning("PM leaderboard fetch error: %s", e)
        return []


def _pm_entry_to_wallet(entry: dict) -> dict:
    """Convert a Polymarket leaderboard entry to our wallet format."""
    name = (entry.get("userName") or "").strip()[:255]
    if name.lower().startswith("0x") and len(name) > 10:
        name = ""
    pnl = float(entry.get("pnl", 0) or 0)
    vol = float(entry.get("vol", 0) or 0)
    roi = (pnl / vol * 100) if vol > 0 else 0.0
    return {
        "address": entry.get("proxyWallet", ""),
        "username": name,
        "website_pnl": pnl,
        "website_volume": vol,
        "website_rank": int(entry.get("rank", 0) or 0),
        "total_pnl": pnl,
        "total_volume": vol,
        "roi_pct": round(roi, 2),
        "strategy": None,
        "active_days": 0,
                "biggest_win": None,
        "biggest_loss": None,
        "position_value": 0,
        "max_trade_size": 0,
        "added_reason": None,
        "added_at": None,
    }


# ---------------------------------------------------------------------------
# Global leaderboard — all wallets discovered via deposits / trades
# ---------------------------------------------------------------------------

@router.get("/global")
async def get_global_leaderboard(
    request: Request,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    time_period: str = "ALL",
    source_type: Optional[str] = None,
) -> dict[str, Any]:
    """All discovered wallets (from deposit watcher + trade watcher). No filters.

    When category is set to a specific category (not OVERALL), the stats columns
    (PnL, volume, win_rate, ROI, resolved_count) show per-category numbers
    instead of overall numbers.
    """
    cache_key = f"global_{sort_by}_{sort_order}_{limit}_{offset}_{search}_{category}_{time_period}_{source_type}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    cat_upper = (category or "OVERALL").upper().strip()
    use_category = cat_upper and cat_upper in VALID_CATEGORIES and cat_upper != "OVERALL"

    if use_category:
        # Per-category view: use wallet_category_stats for the selected category
        allowed_sorts = {
            "total_volume": "COALESCE(wcs.total_volume, 0)",
            "total_pnl": "COALESCE(wcs.total_pnl, 0)",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "website_rank": "COALESCE(tw.website_rank, 999999999)",
            "last_trade_at": "tw.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "COALESCE(wcs.total_pnl, 0)")

        query = """
            SELECT
                ws.address,
                COALESCE(wcs.total_volume, 0) as total_volume,
                COALESCE(wcs.total_pnl, 0) as total_pnl,
                ws.strategy,
                ws.active_days,
ws.biggest_win,
                ws.biggest_loss,
                COALESCE(tw.position_value, 0) as position_value,
                COALESCE(tw.balance, 0) as balance,
                COALESCE(tw.max_trade_size, 0) as max_trade_size,
                ws.added_reason,
                tw.added_at,
                tw.website_pnl,
                tw.website_volume,
                tw.website_rank,
                tw.username,
                tw.source_type,
                tw.last_trade_at,
                $1 as active_category
            FROM wallet_stats ws
            LEFT JOIN tracked_wallets tw ON ws.address = tw.address
            LEFT JOIN wallet_category_stats wcs ON ws.address = wcs.address AND wcs.category = $1
        """
        args: list[Any] = [cat_upper]
        conditions: list[str] = [
            "wcs.address IS NOT NULL",
            "tw.last_trade_at >= NOW() - INTERVAL '30 days'"
        ]

        if search:
            conditions.append(f"ws.address ILIKE ${len(args) + 1}")
            args.append(f"%{search}%")
        if source_type:
            conditions.append(f"tw.source_type = ${len(args) + 1}")
            args.append(source_type)

        query += " WHERE " + " AND ".join(conditions)
        order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
        query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
        query += f" LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
        args.extend([limit, offset])

        async with pool.acquire() as conn:
            count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
            count_args = args[:-2]
            total_count = await conn.fetchval(count_sql, *count_args)
            rows = await conn.fetch(query, *args)

    else:
        # Overall view: stats from tracked_wallets
        allowed_sorts = {
            "total_volume": "COALESCE(tw.total_volume, ws.total_volume, 0)",
            "total_pnl": "COALESCE(tw.total_pnl, ws.total_pnl, tw.website_pnl, 0)",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "biggest_win": "ws.biggest_win",
                        "position_value": "COALESCE(tw.position_value, 0)",
            "balance": "COALESCE(tw.balance, 0)",
            "max_trade_size": "COALESCE(tw.max_trade_size, 0)",
            "website_rank": "COALESCE(tw.website_rank, 999999999)",
            "last_trade_at": "tw.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "COALESCE(tw.total_pnl, ws.total_pnl, 0)")

        query = """
            SELECT
                tw.address,
                COALESCE(tw.total_volume, ws.total_volume, 0) as total_volume,
                COALESCE(tw.total_pnl, ws.total_pnl, tw.website_pnl, 0) as total_pnl,
                ws.strategy,
                ws.active_days,
ws.biggest_win,
                ws.biggest_loss,
                COALESCE(tw.position_value, 0) as position_value,
                COALESCE(tw.balance, 0) as balance,
                COALESCE(tw.max_trade_size, 0) as max_trade_size,
                ws.added_reason,
                tw.added_at,
                tw.website_pnl,
                tw.website_volume,
                tw.website_rank,
                tw.username,
                tw.source_type,
                tw.last_trade_at,
                'OVERALL' as active_category
            FROM tracked_wallets tw
            LEFT JOIN wallet_stats ws ON tw.address = ws.address
        """
        conditions: list[str] = [
            "tw.status = 'ACTIVE'",
            "(COALESCE(tw.balance, 0) + COALESCE(tw.position_value, 0)) >= 1000",
            "tw.last_trade_at >= NOW() - INTERVAL '30 days'"
        ]
        args: list[Any] = []

        if search:
            conditions.append(f"(tw.address ILIKE ${len(args) + 1} OR tw.username ILIKE ${len(args) + 1})")
            args.append(f"%{search}%")
        if source_type:
            conditions.append(f"tw.source_type = ${len(args) + 1}")
            args.append(source_type)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
        query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
        query += f" LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
        args.extend([limit, offset])

        async with pool.acquire() as conn:
            count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
            count_args = args[:-2] if len(args) >= 2 else []
            total_count = await conn.fetchval(count_sql, *count_args)
            rows = await conn.fetch(query, *args)

    data = [dict(r) for r in rows]
    result = {"wallets": data, "total_count": total_count}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


# ---------------------------------------------------------------------------
# Curated leaderboard — filtered subset with conditions
# ---------------------------------------------------------------------------

@router.get("/curated")
async def get_curated_leaderboard(
    request: Request,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    
    min_win_rate: Optional[float] = None,
    min_roi: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_resolved: Optional[int] = None,
    min_active_days: Optional[int] = None,
    search: Optional[str] = None,
    trade_window: Optional[str] = None,
    category: Optional[str] = None,
    time_period: str = "ALL",
) -> dict[str, Any]:
    """Curated wallets — filtered by performance conditions.

    trade_window: "all" | "100" | "500" | "1000" | "2000"
      When set to anything other than "all", the endpoint returns an empty list
      until per-wallet trade-window stats are pre-computed and stored.

    category: Polymarket market category (SPORTS, POLITICS, CRYPTO, etc.)
    """
    cache_key = f"curated_{sort_by}_{sort_order}_{limit}_{offset}_{min_win_rate}_{min_roi}_{min_volume}_{min_resolved}_{min_active_days}_{search}_{trade_window}_{category}_{time_period}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    if trade_window and trade_window != "all":
        result = {"wallets": [], "total_count": 0}
        _cache[cache_key] = {"time": time.time(), "data": result}
        return result

    cat_upper = (category or "OVERALL").upper().strip()
    use_category = cat_upper and cat_upper in VALID_CATEGORIES and cat_upper != "OVERALL"

    if use_category:
        allowed_sorts = {
            "total_volume": "COALESCE(wcs.total_volume, 0)",
            "total_pnl": "COALESCE(wcs.total_pnl, 0)",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "website_rank": "COALESCE(tw.website_rank, 999999999)",
            "last_trade_at": "tw.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "COALESCE(wcs.total_pnl, 0)")

        query = """
            SELECT
                ws.address,
                COALESCE(wcs.total_volume, 0) as total_volume,
                COALESCE(wcs.total_pnl, 0) as total_pnl,
                ws.strategy,
                ws.active_days,
ws.biggest_win,
                ws.biggest_loss,
                COALESCE(tw.position_value, 0) as position_value,
                COALESCE(tw.balance, 0) as balance,
                COALESCE(tw.max_trade_size, 0) as max_trade_size,
                ws.added_reason,
                tw.added_at,
                tw.website_pnl,
                tw.website_volume,
                tw.website_rank,
                tw.username,
                tw.last_trade_at,
                $1 as active_category
            FROM wallet_stats ws
            LEFT JOIN tracked_wallets tw ON ws.address = tw.address
            LEFT JOIN wallet_category_stats wcs ON ws.address = wcs.address AND wcs.category = $1
            WHERE wcs.address IS NOT NULL
        """
        args: list[Any] = [cat_upper]
        param_idx = 2

        if min_win_rate is not None:
            query += f" AND COALESCE(wcs.win_rate, 0) >= ${param_idx}"
            args.append(min_win_rate)
            param_idx += 1

        if min_roi is not None:
            query += f" AND COALESCE(wcs.roi_pct, 0) >= ${param_idx}"
            args.append(min_roi)
            param_idx += 1

        if min_volume is not None:
            query += f" AND COALESCE(wcs.total_volume, 0) >= ${param_idx}"
            args.append(min_volume)
            param_idx += 1

        if min_resolved is not None:
            query += f" AND COALESCE(wcs.resolved_count, 0) >= ${param_idx}"
            args.append(min_resolved)
            param_idx += 1

        if search:
            query += f" AND ws.address ILIKE ${param_idx}"
            args.append(f"%{search}%")
            param_idx += 1

        order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
        query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
        query += f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        args.extend([limit, offset])

        async with pool.acquire() as conn:
            count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
            count_args = args[:-2]
            total_count = await conn.fetchval(count_sql, *count_args)
            rows = await conn.fetch(query, *args)

    else:
        allowed_sorts = {
            "total_volume": "ws.total_volume",
            "total_pnl": "ws.total_pnl",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "biggest_win": "ws.biggest_win",
                        "position_value": "COALESCE(tw.position_value, 0)",
            "max_trade_size": "COALESCE(tw.max_trade_size, 0)",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "website_rank": "COALESCE(tw.website_rank, 999999999)",
            "last_trade_at": "tw.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "ws.total_pnl")

        query = """
            SELECT
                ws.address,
                ws.total_volume,
                ws.total_pnl,
                ws.strategy,
                ws.active_days,
ws.biggest_win,
                ws.biggest_loss,
                COALESCE(tw.position_value, 0) as position_value,
                COALESCE(tw.balance, 0) as balance,
                COALESCE(tw.max_trade_size, 0) as max_trade_size,
                ws.added_reason,
                tw.added_at,
                tw.website_pnl,
                tw.website_volume,
                tw.website_rank,
                tw.username,
                tw.last_trade_at,
                'OVERALL' as active_category
            FROM wallet_stats ws
            LEFT JOIN tracked_wallets tw ON ws.address = tw.address
            WHERE 1=1
        """
        args: list[Any] = []
        param_idx = 1

        if min_win_rate is not None:
            query += f" AND ws.win_rate >= ${param_idx}"
            args.append(min_win_rate)
            param_idx += 1

        if min_roi is not None:
            query += f" AND ws.roi_pct >= ${param_idx}"
            args.append(min_roi)
            param_idx += 1

        if min_volume is not None:
            query += f" AND ws.total_volume >= ${param_idx}"
            args.append(min_volume)
            param_idx += 1

        if min_resolved is not None:
            query += f" AND ws.resolved_count >= ${param_idx}"
            args.append(min_resolved)
            param_idx += 1

        if min_active_days is not None:
            query += f" AND ws.active_days >= ${param_idx}"
            args.append(min_active_days)
            param_idx += 1

        if search:
            query += f" AND ws.address ILIKE ${param_idx}"
            args.append(f"%{search}%")
            param_idx += 1

        order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
        query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
        query += f" LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        args.extend([limit, offset])

        async with pool.acquire() as conn:
            count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
            count_args = args[:-2]
            total_count = await conn.fetchval(count_sql, *count_args)
            rows = await conn.fetch(query, *args)

    data = [dict(r) for r in rows]
    result = {"wallets": data, "total_count": total_count}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result




# ---------------------------------------------------------------------------
# SUBCATEGORIES (for filter dropdown)
# ---------------------------------------------------------------------------

@router.get("/subcategories")
async def get_subcategories(
    request: Request,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """Return distinct subcategories for a given category from wallet_tags."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    if not category or category.lower() == "all":
        return {"subcategories": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT subcategory FROM wallet_tags WHERE category ILIKE $1 AND subcategory IS NOT NULL ORDER BY subcategory",
            category,
        )

    return {"subcategories": [r["subcategory"] for r in rows]}


# ---------------------------------------------------------------------------
# GLOBAL WALLET LIST (with source_type + dormancy filters)
# ---------------------------------------------------------------------------

@router.get("/global-wallets")
async def get_global_wallet_list(
    request: Request,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    include_dormant: bool = True,
    filter_category: Optional[str] = None,
    filter_subcategory: Optional[str] = None,
) -> dict[str, Any]:
    """All tracked wallets with source type and dormancy info."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    cat_upper = (category or "").upper().strip()
    use_category = cat_upper and cat_upper in VALID_CATEGORIES and cat_upper != "OVERALL"

    # Global list
    if use_category:
        order_col = {
            "total_pnl": "COALESCE(wcs.total_pnl, 0)",
            "total_volume": "COALESCE(wcs.total_volume, 0)",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
        }.get(sort_by, "COALESCE(wcs.total_pnl, 0)")
        query = (
            "SELECT tw.address, tw.username, tw.source_type, tw.is_dormant, "
            "tw.last_trade_at, tw.added_at, tw.track_count, "
            "COALESCE(wcs.total_pnl, 0) as total_pnl, "
            "COALESCE(wcs.total_volume, 0) as total_volume, "
            "COALESCE(tw.website_pnl, 0) as website_pnl, "
            "COALESCE(tw.website_volume, 0) as website_volume, "
            "COALESCE(tw.position_value, 0) as position_value, "
            "COALESCE(tw.balance, 0) as balance, "
            "wt.category, wt.subcategory, $1 as active_category "
            "FROM tracked_wallets tw "
            "LEFT JOIN wallet_category_stats wcs ON tw.address=wcs.address AND wcs.category ILIKE $1 "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
            "WHERE wcs.address IS NOT NULL AND tw.status = 'ACTIVE' "
            "AND (COALESCE(tw.balance, 0) + COALESCE(tw.position_value, 0)) >= 1000"
        )
        args: list[Any] = [cat_upper]
    else:
        order_col = {
            "total_pnl": "COALESCE(tw.total_pnl, 0)",
            "total_volume": "tw.total_volume",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "last_trade_at": "tw.last_trade_at",
            "balance": "tw.balance",
        }.get(sort_by, "COALESCE(tw.website_pnl, 0)")
        query = (
            "SELECT tw.address, tw.username, tw.source_type, tw.is_dormant, "
            "tw.last_trade_at, tw.added_at, tw.track_count, "
            "COALESCE(tw.total_pnl, 0) as total_pnl, "
            
            "COALESCE(tw.total_volume, 0) as total_volume, "
            
            "COALESCE(tw.website_pnl, 0) as website_pnl, "
            "COALESCE(tw.website_volume, 0) as website_volume, "
            "COALESCE(tw.position_value, 0) as position_value, "
            "COALESCE(tw.balance, 0) as balance, "
            "wt.category, wt.subcategory, NULL as active_category "
            "FROM tracked_wallets tw "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
            "WHERE tw.status = 'ACTIVE' "
            "AND (COALESCE(tw.balance, 0) + COALESCE(tw.position_value, 0)) >= 1000"
        )
        args = []

    if not include_dormant:
        query += " AND (tw.is_dormant = FALSE OR tw.is_dormant IS NULL)"
    if source and source in ("deposit", "trade", "manual", "leaderboard"):
        query += f" AND tw.source_type = ${len(args)+1}"
        args.append(source)
    if search:
        query += f" AND (tw.address ILIKE ${len(args)+1} OR tw.username ILIKE ${len(args)+1})"
        args.append(f"%{search}%")
    if filter_category and filter_category.lower() != "all":
        query += f" AND wt.category = ${len(args)+1}"
        args.append(filter_category)
    if filter_subcategory and filter_subcategory.lower() != "all":
        query += f" AND wt.subcategory = ${len(args)+1}"
        args.append(filter_subcategory)

    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
    query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
    query += f" LIMIT ${len(args)+1} OFFSET ${len(args)+2}"
    args.extend([limit, offset])

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        # Count query with same joins and filters
        count_query = (
            "SELECT COUNT(*) FROM tracked_wallets tw "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
        )
        if use_category:
            count_query += " LEFT JOIN wallet_category_stats wcs ON tw.address=wcs.address AND wcs.category=$1 "
        count_query += " WHERE 1=1 AND (COALESCE(tw.balance, 0) + COALESCE(tw.position_value, 0)) >= 1000"
        count_args: list[Any] = []
        if use_category:
            count_args.append(cat_upper)
            count_query += f" AND wcs.address IS NOT NULL"
        else:
            count_query += f" AND tw.status = 'ACTIVE'"
        if not include_dormant:
            count_query += " AND (tw.is_dormant = FALSE OR tw.is_dormant IS NULL)"
        if source and source in ("deposit", "trade", "manual", "leaderboard"):
            count_query += f" AND tw.source_type = ${len(count_args)+1}"
            count_args.append(source)
        if search:
            count_query += f" AND (tw.address ILIKE ${len(count_args)+1} OR tw.username ILIKE ${len(count_args)+1})"
            count_args.append(f"%{search}%")
        if filter_category and filter_category.lower() != "all":
            count_query += f" AND wt.category = ${len(count_args)+1}"
            count_args.append(filter_category)
        if filter_subcategory and filter_subcategory.lower() != "all":
            count_query += f" AND wt.subcategory = ${len(count_args)+1}"
            count_args.append(filter_subcategory)
        total_count = await conn.fetchval(count_query, *count_args)

    return {"wallets": [dict(r) for r in rows], "total_count": total_count}


# ---------------------------------------------------------------------------
# CURATED WALLET LIST
# ---------------------------------------------------------------------------

@router.get("/curated-wallets")
async def get_curated_wallet_list(
    request: Request,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    window: Optional[int] = None,
    filter_category: Optional[str] = None,
    filter_subcategory: Optional[str] = None,
    min_roi: Optional[float] = None,
    max_roi: Optional[float] = None,
    min_pnl: Optional[float] = None,
    max_pnl: Optional[float] = None,
    min_wins: Optional[int] = None,
    max_wins: Optional[int] = None,
    min_win_rate: Optional[float] = None,
    max_win_rate: Optional[float] = None,
) -> dict[str, Any]:
    """Quality wallets meeting curated criteria, with category filtering.
    
    Window can be 100, 300, 800, 1500, or 2500.
    """
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    if window is not None and window not in (100, 300, 800, 1500, 2500):
        raise HTTPException(status_code=400, detail="Invalid window tier. Must be one of 100, 300, 800, 1500, 2500")

    cat_upper = (category or "").upper().strip()
    use_category = cat_upper and cat_upper in VALID_CATEGORIES and cat_upper != "OVERALL"

    # Windowed sourcing: when a whitelisted window is requested, every metric is
    # served from the precomputed wallet_window_<win> table for the relevant
    # category. `win` comes ONLY from the validated int (never raw user input).
    win = window if window in (100, 300, 800, 1500, 2500) else None
    win_cat = cat_upper if use_category else "OVERALL"

    if use_category:
        order_col = {
            "total_pnl": "COALESCE(wcs.total_pnl, 0)",
            "total_volume": "COALESCE(wcs.total_volume, 0)",
            "last_trade_at": "tw.last_trade_at",
        }.get(sort_by, "COALESCE(wcs.total_pnl, 0)")
        args: list[Any] = [cat_upper]
        if win:
            args.append(win_cat)
            _wp = len(args)
            win_tbl = f"wallet_window_{win}"
            win_join = (
                f" LEFT JOIN {win_tbl} ww ON tw.address=ww.address "
                f"AND ww.category=${_wp} "
            )
            metric_select = (
                "COALESCE(ww.pnl, 0) as total_pnl, "
                "COALESCE(ww.volume, 0) as total_volume, "
                "COALESCE(ww.win_rate, 0) as win_rate, "
                "COALESCE(ww.roi_pct, 0) as roi_pct, "
                "COALESCE(ww.resolved_count, 0) as resolved_count, "
                "COALESCE(ww.winning_count, 0) as winning_count, "
                "ww.last_active as last_active, "
            )
        else:
            win_join = ""
            metric_select = (
                "COALESCE(wcs.total_pnl, 0) as total_pnl, "
                "COALESCE(wcs.total_volume, 0) as total_volume, "
                "COALESCE(wcs.win_rate, 0) as win_rate, "
                "COALESCE(wcs.roi_pct, 0) as roi_pct, "
                "COALESCE(wcs.resolved_count, 0) as resolved_count, "
                "COALESCE(wcs.winning_count, 0) as winning_count, "
                "COALESCE(ws.avg_buy_price, 0) as avg_buy_price, "
                "COALESCE(ws.buys_below_15c, 0) as buys_below_15c, "
                "COALESCE(ws.buys_15_30c, 0) as buys_15_30c, "
                "COALESCE(ws.buys_30_45c, 0) as buys_30_45c, "
                "COALESCE(ws.buys_45_60c, 0) as buys_45_60c, "
                "COALESCE(ws.buys_60_75c, 0) as buys_60_75c, "
                "COALESCE(ws.buys_above_75c, 0) as buys_above_75c, "
                "COALESCE(ws.wins_below_15c, 0) as wins_below_15c, "
                "COALESCE(ws.wins_15_30c, 0) as wins_15_30c, "
                "COALESCE(ws.wins_30_45c, 0) as wins_30_45c, "
                "COALESCE(ws.wins_45_60c, 0) as wins_45_60c, "
                "COALESCE(ws.wins_60_75c, 0) as wins_60_75c, "
                "COALESCE(ws.wins_above_75c, 0) as wins_above_75c, "
                "COALESCE(ws.losses_below_15c, 0) as losses_below_15c, "
                "COALESCE(ws.losses_15_30c, 0) as losses_15_30c, "
                "COALESCE(ws.losses_30_45c, 0) as losses_30_45c, "
                "COALESCE(ws.losses_45_60c, 0) as losses_45_60c, "
                "COALESCE(ws.losses_60_75c, 0) as losses_60_75c, "
                "COALESCE(ws.losses_above_75c, 0) as losses_above_75c, "
            )
        query = (
            "SELECT tw.address, tw.username, tw.source_type, tw.is_dormant, "
            "tw.last_trade_at, tw.curated_at, "
            "tw.last_checked_for_curated, tw.track_count, "
            + metric_select +
            "COALESCE(tw.website_pnl, 0) as website_pnl, "
            "COALESCE(tw.position_value, 0) as position_value, "
            "COALESCE(tw.balance, 0) as balance, "
            "wt.category, wt.subcategory, $1 as active_category "
            "FROM tracked_wallets tw "
            "LEFT JOIN wallet_stats ws ON tw.address=ws.address "
            "LEFT JOIN wallet_category_stats wcs ON tw.address=wcs.address AND wcs.category ILIKE $1 "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
            + win_join +
            "WHERE tw.is_curated=TRUE AND tw.is_dormant=FALSE AND wcs.address IS NOT NULL"
        )
    else:
        order_col = {
            "total_pnl": "COALESCE(ws.total_pnl, 0)",
            "total_volume": "ws.total_volume",
            "website_pnl": "COALESCE(tw.website_pnl, 0)",
            "last_trade_at": "tw.last_trade_at",
        }.get(sort_by, "COALESCE(ws.total_pnl, 0)")
        args = []
        if win:
            args.append(win_cat)
            _wp = len(args)
            win_tbl = f"wallet_window_{win}"
            win_join = (
                f" LEFT JOIN {win_tbl} ww ON tw.address=ww.address "
                f"AND ww.category=${_wp} "
            )
            metric_select = (
                "COALESCE(ww.pnl, 0) as total_pnl, "
                "COALESCE(ww.volume, 0) as total_volume, "
                "COALESCE(ww.win_rate, 0) as win_rate, "
                "COALESCE(ww.roi_pct, 0) as roi_pct, "
                "COALESCE(ww.resolved_count, 0) as resolved_count, "
                "COALESCE(ww.winning_count, 0) as winning_count, "
                "ww.last_active as last_active, "
            )
        else:
            win_join = ""
            metric_select = (
                "COALESCE(ws.total_pnl, 0) as total_pnl, "
                "COALESCE(ws.total_volume, 0) as total_volume, "
                "COALESCE(ws.win_rate, 0) as win_rate, "
                "COALESCE(ws.roi_pct, 0) as roi_pct, "
                "COALESCE(ws.resolved_count, 0) as resolved_count, "
                "COALESCE(ws.winning_count, 0) as winning_count, "
                "COALESCE(ws.avg_buy_price, 0) as avg_buy_price, "
                "COALESCE(ws.buys_below_15c, 0) as buys_below_15c, "
                "COALESCE(ws.buys_15_30c, 0) as buys_15_30c, "
                "COALESCE(ws.buys_30_45c, 0) as buys_30_45c, "
                "COALESCE(ws.buys_45_60c, 0) as buys_45_60c, "
                "COALESCE(ws.buys_60_75c, 0) as buys_60_75c, "
                "COALESCE(ws.buys_above_75c, 0) as buys_above_75c, "
                "COALESCE(ws.wins_below_15c, 0) as wins_below_15c, "
                "COALESCE(ws.wins_15_30c, 0) as wins_15_30c, "
                "COALESCE(ws.wins_30_45c, 0) as wins_30_45c, "
                "COALESCE(ws.wins_45_60c, 0) as wins_45_60c, "
                "COALESCE(ws.wins_60_75c, 0) as wins_60_75c, "
                "COALESCE(ws.wins_above_75c, 0) as wins_above_75c, "
                "COALESCE(ws.losses_below_15c, 0) as losses_below_15c, "
                "COALESCE(ws.losses_15_30c, 0) as losses_15_30c, "
                "COALESCE(ws.losses_30_45c, 0) as losses_30_45c, "
                "COALESCE(ws.losses_45_60c, 0) as losses_45_60c, "
                "COALESCE(ws.losses_60_75c, 0) as losses_60_75c, "
                "COALESCE(ws.losses_above_75c, 0) as losses_above_75c, "
            )
        query = (
            "SELECT tw.address, tw.username, tw.source_type, tw.is_dormant, "
            "tw.last_trade_at, tw.curated_at, "
            "tw.last_checked_for_curated, tw.track_count, "
            + metric_select +
            "COALESCE(tw.website_pnl, 0) as website_pnl, "
            "COALESCE(tw.position_value, 0) as position_value, "
            "COALESCE(tw.balance, 0) as balance, "
            "wt.category, wt.subcategory, NULL as active_category "
            "FROM tracked_wallets tw "
            "LEFT JOIN wallet_stats ws ON tw.address=ws.address "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
            + win_join +
            "WHERE tw.is_curated=TRUE AND (tw.is_dormant=FALSE OR tw.is_dormant IS NULL)"
        )

    # When windowed, ordering must also come from the window table.
    if win:
        _pnl_sorts = {"total_pnl", "pnl_100", "pnl_300", "pnl_800", "pnl_1500", "pnl_2500"}
        _ww_order = {
            "total_volume": "COALESCE(ww.volume, 0)",
        }
        if sort_by in _pnl_sorts:
            order_col = "COALESCE(ww.pnl, 0)"
        elif sort_by in _ww_order:
            order_col = _ww_order[sort_by]

    if search:
        query += f" AND (tw.address ILIKE ${len(args)+1} OR tw.username ILIKE ${len(args)+1})"
        args.append(f"%{search}%")
    if filter_category and filter_category.lower() != "all":
        query += f" AND wt.category ILIKE ${len(args)+1}"
        args.append(filter_category)
    if filter_subcategory and filter_subcategory.lower() != "all":
        query += f" AND wt.subcategory = ${len(args)+1}"
        args.append(filter_subcategory)
    if min_roi is not None:
        query += f" AND ws.roi_pct >= ${len(args)+1}"
        args.append(min_roi)
    if max_roi is not None:
        query += f" AND ws.roi_pct <= ${len(args)+1}"
        args.append(max_roi)
    if min_pnl is not None:
        query += f" AND COALESCE(ws.total_pnl, 0) >= ${len(args)+1}"
        args.append(min_pnl)
    if max_pnl is not None:
        query += f" AND COALESCE(ws.total_pnl, 0) <= ${len(args)+1}"
        args.append(max_pnl)
    if min_wins is not None:
        query += f" AND ws.winning_count >= ${len(args)+1}"
        args.append(min_wins)
    if max_wins is not None:
        query += f" AND ws.winning_count <= ${len(args)+1}"
        args.append(max_wins)
    if min_win_rate is not None:
        query += f" AND ws.win_rate >= ${len(args)+1}"
        args.append(min_win_rate)
    if max_win_rate is not None:
        query += f" AND ws.win_rate <= ${len(args)+1}"
        args.append(max_win_rate)

    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
    query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
    query += f" LIMIT ${len(args)+1} OFFSET ${len(args)+2}"
    args.extend([limit, offset])

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        
        # Fetch qualifying categories for all wallets
        addresses = [r["address"] for r in rows]
        if addresses:
            cat_rows = await conn.fetch("""
                SELECT address, array_agg(category) as categories
                FROM wallet_category_stats
                WHERE address = ANY($1)
                  AND resolved_count >= 5
                  AND win_rate >= 70
                  AND roi_pct > 30
                GROUP BY address
            """, addresses)
            categories_map = {r["address"]: [c for c in r["categories"] if c] for r in cat_rows}
            
            sub_rows = await conn.fetch("""
                SELECT address, array_agg(DISTINCT subcategory) as subcategories
                FROM wallet_subcategory_stats
                WHERE address = ANY($1)
                  AND resolved_count >= 5
                  AND win_rate >= 70
                  AND roi_pct > 30
                GROUP BY address
            """, addresses)
            subcategories_map = {r["address"]: [s for s in r["subcategories"] if s] for r in sub_rows}
        else:
            categories_map = {}
            subcategories_map = {}
        
        # Build response with qualifying categories
        wallets = []
        for r in rows:
            w = dict(r)
            w["categories"] = categories_map.get(w["address"], [])
            w["subcategories"] = subcategories_map.get(w["address"], [])
            wallets.append(w)
        
        # Build count query with same filters
        count_query = (
            "SELECT COUNT(*) FROM tracked_wallets tw "
            "LEFT JOIN wallet_stats ws ON tw.address=ws.address "
            "LEFT JOIN wallet_tags wt ON tw.address=wt.address "
        )
        if use_category:
            count_query += " LEFT JOIN wallet_category_stats wcs ON tw.address=wcs.address AND wcs.category=$1 "
        count_query += " WHERE tw.is_curated=TRUE"
        count_args: list[Any] = []
        if use_category:
            count_args.append(cat_upper)
            count_query += " AND tw.is_dormant=FALSE AND wcs.address IS NOT NULL"
        else:
            count_query += " AND (tw.is_dormant=FALSE OR tw.is_dormant IS NULL)"
        if search:
            count_query += f" AND (tw.address ILIKE ${len(count_args)+1} OR tw.username ILIKE ${len(count_args)+1})"
            count_args.append(f"%{search}%")
        if filter_category and filter_category.lower() != "all":
            count_query += f" AND wt.category = ${len(count_args)+1}"
            count_args.append(filter_category)
        if filter_subcategory and filter_subcategory.lower() != "all":
            count_query += f" AND wt.subcategory = ${len(count_args)+1}"
            count_args.append(filter_subcategory)
        if min_roi is not None:
            count_query += f" AND ws.roi_pct >= ${len(count_args)+1}"
            count_args.append(min_roi)
        if max_roi is not None:
            count_query += f" AND ws.roi_pct <= ${len(count_args)+1}"
            count_args.append(max_roi)
        if min_pnl is not None:
            count_query += f" AND COALESCE(ws.total_pnl, 0) >= ${len(count_args)+1}"
            count_args.append(min_pnl)
        if max_pnl is not None:
            count_query += f" AND COALESCE(ws.total_pnl, 0) <= ${len(count_args)+1}"
            count_args.append(max_pnl)
        if min_wins is not None:
            count_query += f" AND ws.winning_count >= ${len(count_args)+1}"
            count_args.append(min_wins)
        if max_wins is not None:
            count_query += f" AND ws.winning_count <= ${len(count_args)+1}"
            count_args.append(max_wins)
        if min_win_rate is not None:
            count_query += f" AND ws.win_rate >= ${len(count_args)+1}"
            count_args.append(min_win_rate)
        if max_win_rate is not None:
            count_query += f" AND ws.win_rate <= ${len(count_args)+1}"
            count_args.append(max_win_rate)
        total_count = await conn.fetchval(count_query, *count_args)

    return {"wallets": wallets, "total_count": total_count}


@router.get("/category-curated")
async def get_category_curated_wallet_list(
    request: Request,
    category: str,
    subcategory: Optional[str] = None,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """Wallets specifically curated for a category or subcategory."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    cat_upper = category.upper().strip()
    tag_type = "subcategory" if subcategory and subcategory.lower() != "all" else "category"
    sub_val = subcategory if tag_type == "subcategory" else ""

    _sort_map = {
        "total_pnl": "cct.category_pnl",
        "total_volume": "cct.category_volume",
        "last_trade_at": "tw.last_trade_at",
    }
    order_col = _sort_map.get(sort_by, "cct.category_pnl")

    query = (
        "SELECT tw.address, tw.username, tw.source_type, tw.is_dormant, "
        "tw.last_trade_at, tw.curated_at, "
        "tw.last_checked_for_curated, tw.track_count, "
        "COALESCE(cct.category_pnl, 0) as total_pnl, "
        "COALESCE(cct.category_volume, 0) as total_volume, "
        "0 as winning_count, "
        "COALESCE(tw.website_pnl, 0) as website_pnl, "
        "COALESCE(tw.position_value, 0) as position_value, "
        "COALESCE(tw.balance, 0) as balance, "
        "cct.category as active_category, "
        "wt.subcategory "
        "FROM curated_category_tags cct "
        "JOIN tracked_wallets tw ON cct.address = tw.address "
        "LEFT JOIN wallet_tags wt ON cct.address = wt.address "
        "WHERE cct.category ILIKE $1 AND cct.tag_type = $2 AND cct.subcategory = $3 "
        "AND (tw.is_dormant=FALSE OR tw.is_dormant IS NULL)"
    )
    args: list[Any] = [cat_upper, tag_type, sub_val]

    if search:
        query += f" AND (tw.address ILIKE ${len(args)+1} OR tw.username ILIKE ${len(args)+1})"
        args.append(f"%{search}%")

    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
    query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
    query += f" LIMIT ${len(args)+1} OFFSET ${len(args)+2}"
    args.extend([limit, offset])

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        
        count_query = (
            "SELECT COUNT(*) FROM curated_category_tags cct "
            "JOIN tracked_wallets tw ON cct.address = tw.address "
            "WHERE cct.category ILIKE $1 AND cct.tag_type = $2 AND cct.subcategory = $3 "
            "AND (tw.is_dormant=FALSE OR tw.is_dormant IS NULL)"
        )
        count_args: list[Any] = [cat_upper, tag_type, sub_val]
        if search:
            count_query += f" AND (tw.address ILIKE ${len(count_args)+1} OR tw.username ILIKE ${len(count_args)+1})"
            count_args.append(f"%{search}%")
            
        total_count = await conn.fetchval(count_query, *count_args)

    return {"wallets": [dict(r) for r in rows], "total_count": total_count}

# HIBERNATOR WALLETS
# ---------------------------------------------------------------------------

@router.get("/hibernating")
async def get_hibernating_wallets(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Wallets that have been marked as HIBERNATING (inactive for > 30 days)."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    query = (
        "SELECT address, last_active, added_at, total_pnl, total_volume, "
        "balance, username "
        "FROM tracked_wallets "
        "WHERE status = 'HIBERNATING' "
        "ORDER BY last_active DESC NULLS LAST "
        "LIMIT $1 OFFSET $2"
    )

    async with pool.acquire() as conn:
        total_count = await conn.fetchval(
            "SELECT COUNT(*) FROM tracked_wallets WHERE status = 'HIBERNATING'"
        )
        rows = await conn.fetch(query, limit, offset)

    return {"wallets": [dict(r) for r in rows], "total_count": total_count}
