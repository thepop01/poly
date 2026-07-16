"""Leaderboard router V2 for FastAPI (using new 10-table schema)."""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/leaderboard", tags=["leaderboard-v2"])

_cache: dict[str, dict] = {}
CACHE_TTL = 60

VALID_CATEGORIES = {
    "OVERALL", "POLITICS", "SPORTS", "ESPORTS", "CRYPTO",
    "CULTURE", "WEATHER", "ECONOMICS", "TECH", "FINANCE", "MENTIONS", "OTHER",
}

# Canonical tab model: tiers are mutually exclusive, is_dormant is orthogonal.
TAB_FILTERS = {
    "all":         "w.tier NOT IN ('DEAD', 'UNCLASSIFIED')",
    "standard":    "w.tier = 'STANDARD' AND w.is_dormant = FALSE",
    "low_balance": "w.tier = 'LOW_BALANCE' AND w.is_dormant = FALSE",
    "new":         "w.tier = 'NEW' AND w.is_dormant = FALSE",
    "hibernated":  "w.is_dormant = TRUE AND w.tier NOT IN ('DEAD', 'UNCLASSIFIED')",
}

WALLET_SORT_COLUMNS = {
    "pnl": "COALESCE(m.pm_pnl, m.total_pnl)",
    "volume": "COALESCE(m.pm_volume, m.total_volume)",
    "roi": "m.roi_pct",
    "balance": "m.balance",
    "position_value": "m.position_value",
    "deposits": "m.deposits",
    "last_trade_at": "w.last_trade_at",
    "added_at": "w.added_at",
}

WALLET_SOURCES = ("trade", "deposit", "leaderboard", "custom")


@router.get("/wallets")
async def get_wallets_tabbed(
    request: Request,
    tab: str = "all",
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if tab not in TAB_FILTERS:
        raise HTTPException(status_code=400, detail=f"invalid tab: {tab}")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    cache_key = f"v2_wallets_{tab}_{source}_{search}_{sort_by}_{sort_order}_{limit}_{offset}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    order_col = WALLET_SORT_COLUMNS.get(sort_by, WALLET_SORT_COLUMNS["pnl"])
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"

    where = [TAB_FILTERS[tab]]
    params: list[Any] = []
    if source in WALLET_SOURCES:
        params.append(source)
        where.append(
            f"EXISTS (SELECT 1 FROM wallet_sources_v2 s WHERE s.address = w.address AND s.source = ${len(params)})"
        )
    if search:
        params.append(f"%{search}%")
        where.append(f"(w.address ILIKE ${len(params)} OR w.username ILIKE ${len(params)})")
    params.extend([limit, offset])

    sql = f"""
        SELECT w.address, w.username, w.tier, w.is_dormant, w.might_cook_type,
               w.last_trade_at, w.added_at,
               COALESCE(m.pm_pnl, m.total_pnl) AS pnl,
               COALESCE(m.pm_volume, m.total_volume) AS volume,
               m.roi_pct, m.win_rate, m.balance, m.position_value, m.deposits,
               (SELECT array_agg(s.source ORDER BY s.spotted_at)
                  FROM wallet_sources_v2 s WHERE s.address = w.address) AS sources,
               COUNT(*) OVER() AS total_count
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE {' AND '.join(where)}
        ORDER BY {order_col} {direction} NULLS LAST
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    total = rows[0]["total_count"] if rows else 0
    wallets = []
    for r in rows:
        d = dict(r)
        d.pop("total_count", None)
        wallets.append(d)

    result = {"wallets": wallets, "total_count": total}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


@router.get("/wallets/counts")
async def get_wallet_counts(request: Request) -> dict[str, int]:
    cache_key = "v2_wallet_counts"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            SELECT
              COUNT(*) FILTER (WHERE {TAB_FILTERS['all'].replace('w.', '')}) AS all_count,
              COUNT(*) FILTER (WHERE {TAB_FILTERS['standard'].replace('w.', '')}) AS standard,
              COUNT(*) FILTER (WHERE {TAB_FILTERS['low_balance'].replace('w.', '')}) AS low_balance,
              COUNT(*) FILTER (WHERE {TAB_FILTERS['new'].replace('w.', '')}) AS new,
              COUNT(*) FILTER (WHERE {TAB_FILTERS['hibernated'].replace('w.', '')}) AS hibernated
            FROM wallets_v2
        """)

    result = {
        "all": row["all_count"], "standard": row["standard"],
        "low_balance": row["low_balance"], "new": row["new"],
        "hibernated": row["hibernated"],
    }
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


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
    cache_key = f"v2_global_{sort_by}_{sort_order}_{limit}_{offset}_{search}_{category}_{time_period}_{source_type}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    cat_upper = (category or "OVERALL").upper().strip()
    use_category = cat_upper and cat_upper in VALID_CATEGORIES and cat_upper != "OVERALL"
    
    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

    if use_category:
        allowed_sorts = {
            "total_volume": "c.volume",
            "total_pnl": "c.pnl",
            "website_pnl": "m.pm_pnl",
            "website_rank": "m.pm_rank",
            "last_trade_at": "w.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "c.pnl")

        query = f"""
            SELECT
                w.address,
                c.volume as total_volume,
                c.pnl as total_pnl,
                m.active_days,
                m.biggest_win,
                m.biggest_loss,
                m.position_value,
                m.balance,
                m.avg_position_size as max_trade_size,
                w.tier_reason as added_reason,
                w.added_at,
                m.pm_pnl as website_pnl,
                m.pm_volume as website_volume,
                m.pm_rank as website_rank,
                w.username,
                (SELECT s.source FROM wallet_sources_v2 s
                  WHERE s.address = w.address ORDER BY s.spotted_at LIMIT 1) as source_type,
                w.last_trade_at,
                $1 as active_category
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
            JOIN category_stats_v2 c ON w.address = c.address AND c.category = $1 AND c.window_size = 0
        """
        args: list[Any] = [cat_upper]
        conditions = ["w.last_trade_at >= NOW() - INTERVAL '30 days'"]

    else:
        allowed_sorts = {
            "total_volume": "m.total_volume",
            "total_pnl": "m.total_pnl",
            "website_pnl": "m.pm_pnl",
            "biggest_win": "m.biggest_win",
            "position_value": "m.position_value",
            "balance": "m.balance",
            "max_trade_size": "m.avg_position_size",
            "website_rank": "m.pm_rank",
            "last_trade_at": "w.last_trade_at",
        }
        order_col = allowed_sorts.get(sort_by, "m.total_pnl")

        query = f"""
            SELECT
                w.address,
                m.total_volume,
                m.total_pnl,
                m.active_days,
                m.biggest_win,
                m.biggest_loss,
                m.position_value,
                m.balance,
                m.avg_position_size as max_trade_size,
                w.tier_reason as added_reason,
                w.added_at,
                m.pm_pnl as website_pnl,
                m.pm_volume as website_volume,
                m.pm_rank as website_rank,
                w.username,
                (SELECT s.source FROM wallet_sources_v2 s
                  WHERE s.address = w.address ORDER BY s.spotted_at LIMIT 1) as source_type,
                w.last_trade_at,
                'OVERALL' as active_category
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
        """
        conditions = [
            "w.tier != 'DEAD'",
            "(m.balance + m.position_value) >= 1000",
            "w.last_trade_at >= NOW() - INTERVAL '30 days'"
        ]
        args = []

    if search:
        conditions.append(f"(w.address ILIKE ${len(args) + 1} OR w.username ILIKE ${len(args) + 1})")
        args.append(f"%{search}%")
    if source_type:
        conditions.append(
            f"EXISTS (SELECT 1 FROM wallet_sources_v2 sf WHERE sf.address = w.address AND sf.source = ${len(args) + 1})"
        )
        args.append(source_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += f" ORDER BY {order_col} {order_dir} NULLS LAST"
    query += f" LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
    args.extend([limit, offset])

    async with pool.acquire() as conn:
        count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
        count_args = args[:-2] if len(args) >= 2 else []
        total_count = await conn.fetchval(count_sql, *count_args)
        rows = await conn.fetch(query, *args)

    result = {"wallets": [dict(r) for r in rows], "total_count": total_count}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


@router.get("/curated-wallets")
async def get_curated_wallet_list(
    request: Request,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    category: Optional[str] = None,
    window: Optional[int] = 0,
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
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    if window not in (0, 100, 300, 800, 1500, 2500):
        window = 0

    cat_upper = (category or "OVERALL").upper().strip()
    
    is_overall_all_time = cat_upper == "OVERALL" and window == 0

    if is_overall_all_time:
        order_col = {
            "total_pnl": "m.total_pnl",
            "total_volume": "m.total_volume",
            "website_pnl": "m.pm_pnl",
            "last_trade_at": "w.last_trade_at",
        }.get(sort_by, "m.total_pnl")
        
        query = f"""
            SELECT 
                w.address, w.username, w.is_dormant, w.last_trade_at, w.added_at,
                m.total_pnl as total_pnl, m.total_volume as total_volume, m.win_rate, m.roi_pct,
                m.resolved_count, m.winning_count,
                m.pm_pnl as website_pnl, m.position_value, m.balance,
                'OVERALL' as active_category
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.tier = 'CURATED' AND w.is_dormant = FALSE
        """
        args: list[Any] = []
        pnl_col, vol_col, win_rate_col, roi_col, win_col = "m.total_pnl", "m.total_volume", "m.win_rate", "m.roi_pct", "m.winning_count"
    else:
        order_col = {
            "total_pnl": "c.pnl",
            "total_volume": "c.volume",
            "website_pnl": "m.pm_pnl",
            "last_trade_at": "w.last_trade_at",
        }.get(sort_by, "c.pnl")

        query = f"""
            SELECT 
                w.address, w.username, w.is_dormant, w.last_trade_at, w.added_at,
                c.pnl as total_pnl, c.volume as total_volume, c.win_rate, c.roi_pct,
                c.resolved_count, c.winning_count,
                m.pm_pnl as website_pnl, m.position_value, m.balance,
                c.category as active_category
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
            JOIN category_stats_v2 c ON w.address = c.address 
                AND c.category = $1 
                AND c.subcategory = '' 
                AND c.window_size = $2
            WHERE w.tier = 'CURATED' AND w.is_dormant = FALSE
        """
        args: list[Any] = [cat_upper, window]
        pnl_col, vol_col, win_rate_col, roi_col, win_col = "c.pnl", "c.volume", "c.win_rate", "c.roi_pct", "c.winning_count"

    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
    if search:
        query += f" AND (w.address ILIKE ${len(args)+1} OR w.username ILIKE ${len(args)+1})"
        args.append(f"%{search}%")
    if min_roi is not None:
        query += f" AND {roi_col} >= ${len(args)+1}"
        args.append(min_roi)
    if max_roi is not None:
        query += f" AND {roi_col} <= ${len(args)+1}"
        args.append(max_roi)
    if min_pnl is not None:
        query += f" AND {pnl_col} >= ${len(args)+1}"
        args.append(min_pnl)
    if max_pnl is not None:
        query += f" AND {pnl_col} <= ${len(args)+1}"
        args.append(max_pnl)
    if min_wins is not None:
        query += f" AND {win_col} >= ${len(args)+1}"
        args.append(min_wins)
    if max_wins is not None:
        query += f" AND {win_col} <= ${len(args)+1}"
        args.append(max_wins)
    if min_win_rate is not None:
        query += f" AND {win_rate_col} >= ${len(args)+1}"
        args.append(min_win_rate)
    if max_win_rate is not None:
        query += f" AND {win_rate_col} <= ${len(args)+1}"
        args.append(max_win_rate)

    query += f" ORDER BY {order_col} {order_dir} NULLS LAST LIMIT ${len(args)+1} OFFSET ${len(args)+2}"
    args.extend([limit, offset])

    async with pool.acquire() as conn:
        count_sql = "SELECT COUNT(*) FROM (" + query.rsplit(" ORDER BY", 1)[0] + ") sub"
        total_count = await conn.fetchval(count_sql, *args[:-2])
        rows = await conn.fetch(query, *args)

    return {"wallets": [dict(r) for r in rows], "total_count": total_count}

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
    window = int(trade_window) if trade_window and trade_window.isdigit() else 0
    return await get_curated_wallet_list(
        request, sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
        search=search, category=category, window=window,
        min_roi=min_roi, min_pnl=None, min_wins=None, min_win_rate=min_win_rate
    )

@router.get("/category-curated")
async def get_category_curated(
    request: Request,
    category: str,
    sort_by: str = "category_pnl",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    subcategory: Optional[str] = None
) -> dict[str, Any]:
    return await get_curated_wallet_list(
        request, sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
        search=search, category=category, filter_subcategory=subcategory
    )

@router.get("/global-wallets")
async def get_global_wallet_list_endpoint(
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
    return await get_global_leaderboard(
        request, sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
        search=search, category=category, source_type=source
    )

# Legacy tab names → canonical /wallets tabs
_MIGHT_COOK_TAB_MAP = {
    "new_wallets": "new",
    "zero_balance": "low_balance",
    "hibernated": "hibernated",
}
_MIGHT_COOK_SORT_MAP = {
    "deposited_at": "added_at",
    "balance": "balance",
    "total_pnl": "pnl",
    "position_value": "position_value",
    "last_trade_at": "last_trade_at",
}


def _legacy_row(w: dict) -> dict:
    """Map a /wallets row onto the legacy might-cook/hibernating response shape."""
    return {
        "wallet_address": w["address"],
        "address": w["address"],
        "amount_usdc": 0,
        "deposited_at": w["added_at"],
        "tx_hash": "",
        "total_pnl": w["pnl"],
        "total_volume": w["volume"],
        "website_pnl": w["pnl"],
        "balance": w["balance"],
        "position_value": w["position_value"],
        "username": w["username"],
        "source_type": (w.get("sources") or [None])[0],
        "last_trade_at": w["last_trade_at"],
    }


@router.get("/might-cook")
async def get_might_cook_wallets(
    request: Request,
    sort_by: str = "deposited_at",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    tab: str = "zero_balance",
) -> dict[str, Any]:
    """Thin delegate onto the canonical /wallets tabs (legacy response shape)."""
    result = await get_wallets_tabbed(
        request,
        tab=_MIGHT_COOK_TAB_MAP.get(tab, "low_balance"),
        sort_by=_MIGHT_COOK_SORT_MAP.get(sort_by, "added_at"),
        sort_order=sort_order, limit=limit, offset=offset,
    )
    return {
        "wallets": [_legacy_row(w) for w in result["wallets"]],
        "total_count": result["total_count"],
    }


@router.get("/hibernating")
async def get_hibernating_wallets(
    request: Request,
    limit: int = 50,
    offset: int = 0
) -> dict[str, Any]:
    """Thin delegate onto the canonical hibernated tab (legacy response shape)."""
    result = await get_wallets_tabbed(
        request, tab="hibernated",
        sort_by="last_trade_at", sort_order="asc",
        limit=limit, offset=offset,
    )
    return {
        "wallets": [_legacy_row(w) for w in result["wallets"]],
        "total_count": result["total_count"],
    }

@router.get("/subcategories")
async def get_subcategories(
    request: Request,
    category: Optional[str] = None,
) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
        
    if not category or category.lower() == "all":
        return {"subcategories": []}
        
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT subcategory FROM category_stats_v2 WHERE category ILIKE $1 AND subcategory != '' ORDER BY subcategory",
            category
        )
        
    return {"subcategories": [r["subcategory"] for r in rows]}
