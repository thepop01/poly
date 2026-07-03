"""Leaderboard router for FastAPI.

Two sections:
  - /leaderboard/global   → all discovered wallets (deposits + trades), no filters
  - /leaderboard/curated  → filtered subset based on conditions (win rate, ROI, tier, etc.)
"""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
import time

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

_cache: dict[str, dict] = {}
CACHE_TTL = 60


# ---------------------------------------------------------------------------
# Global leaderboard — all wallets discovered via deposits / trades
# ---------------------------------------------------------------------------

@router.get("/global")
async def get_global_leaderboard(
    request: Request,
    sort_by: str = "total_pnl",
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """All discovered wallets (from deposit watcher + trade watcher). No filters."""
    cache_key = f"global_{sort_by}_{limit}_{offset}_{search}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    allowed_sorts = {
        "win_rate": "ws.win_rate",
        "roi_pct": "ws.roi_pct",
        "total_volume": "ws.total_volume",
        "total_pnl": "ws.total_pnl",
        "realized_pnl": "COALESCE(tw.realized_pnl, 0)",
        "unrealized_pnl": "COALESCE(tw.unrealized_pnl, 0)",
        "biggest_win": "ws.biggest_win",
        "alpha_score": "ws.alpha_score",
        "position_value": "COALESCE(tw.position_value, 0)",
        "max_trade_size": "COALESCE(tw.max_trade_size, 0)",
        "resolved_count": "ws.resolved_count",
        "tier": "ws.tier",
        "website_pnl": "COALESCE(tw.website_pnl, 0)",
        "website_rank": "COALESCE(tw.website_rank, 999999999)",
    }
    order_col = allowed_sorts.get(sort_by, "ws.total_pnl")

    query = """
        SELECT
            ws.address,
            ws.win_rate,
            ws.roi_pct,
            ws.resolved_count,
            ws.winning_count,
            ws.total_volume,
            ws.total_pnl,
            COALESCE(tw.realized_pnl, 0) as realized_pnl,
            COALESCE(tw.unrealized_pnl, 0) as unrealized_pnl,
            ws.tier,
            ws.strategy,
            ws.active_days,
            ws.alpha_score,
            ws.biggest_win,
            ws.biggest_loss,
            COALESCE(tw.position_value, 0) as position_value,
            COALESCE(tw.max_trade_size, 0) as max_trade_size,
            ws.added_reason,
            tw.added_at,
            tw.website_pnl,
            tw.website_volume,
            tw.website_rank,
            tw.username
        FROM wallet_stats ws
        LEFT JOIN tracked_wallets tw ON ws.address = tw.address
    """
    conditions: list[str] = []
    args: list[Any] = []

    if search:
        conditions.append(f"ws.address ILIKE ${len(args) + 1}")
        args.append(f"%{search}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += f" ORDER BY {order_col} DESC NULLS LAST"
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
    limit: int = 50,
    offset: int = 0,
    tier: Optional[str] = None,
    min_win_rate: Optional[float] = None,
    min_roi: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_resolved: Optional[int] = None,
    min_realized_pnl: Optional[float] = None,
    min_active_days: Optional[int] = None,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """Curated wallets — filtered by performance conditions."""
    cache_key = f"curated_{sort_by}_{limit}_{offset}_{tier}_{min_win_rate}_{min_roi}_{min_volume}_{min_resolved}_{min_realized_pnl}_{min_active_days}_{search}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    allowed_sorts = {
        "win_rate": "ws.win_rate",
        "roi_pct": "ws.roi_pct",
        "total_volume": "ws.total_volume",
        "total_pnl": "ws.total_pnl",
        "realized_pnl": "COALESCE(tw.realized_pnl, 0)",
        "unrealized_pnl": "COALESCE(tw.unrealized_pnl, 0)",
        "biggest_win": "ws.biggest_win",
        "alpha_score": "ws.alpha_score",
        "position_value": "COALESCE(tw.position_value, 0)",
        "max_trade_size": "COALESCE(tw.max_trade_size, 0)",
        "resolved_count": "ws.resolved_count",
        "tier": "ws.tier",
        "website_pnl": "COALESCE(tw.website_pnl, 0)",
        "website_rank": "COALESCE(tw.website_rank, 999999999)",
    }
    order_col = allowed_sorts.get(sort_by, "ws.total_pnl")

    query = """
        SELECT
            ws.address,
            ws.win_rate,
            ws.roi_pct,
            ws.resolved_count,
            ws.winning_count,
            ws.total_volume,
            ws.total_pnl,
            COALESCE(tw.realized_pnl, 0) as realized_pnl,
            COALESCE(tw.unrealized_pnl, 0) as unrealized_pnl,
            ws.tier,
            ws.strategy,
            ws.active_days,
            ws.alpha_score,
            ws.biggest_win,
            ws.biggest_loss,
            COALESCE(tw.position_value, 0) as position_value,
            COALESCE(tw.max_trade_size, 0) as max_trade_size,
            ws.added_reason,
            tw.added_at,
            tw.website_pnl,
            tw.website_volume,
            tw.website_rank,
            tw.username
        FROM wallet_stats ws
        LEFT JOIN tracked_wallets tw ON ws.address = tw.address
        WHERE 1=1
    """
    args: list[Any] = []
    param_idx = 1

    if tier and tier.lower() != "all tiers":
        query += f" AND ws.tier ILIKE ${param_idx}"
        args.append(tier)
        param_idx += 1

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

    if min_realized_pnl is not None:
        query += f" AND COALESCE(tw.realized_pnl, 0) >= ${param_idx}"
        args.append(min_realized_pnl)
        param_idx += 1

    if min_active_days is not None:
        query += f" AND ws.active_days >= ${param_idx}"
        args.append(min_active_days)
        param_idx += 1

    if search:
        query += f" AND ws.address ILIKE ${param_idx}"
        args.append(f"%{search}%")
        param_idx += 1

    query += f" ORDER BY {order_col} DESC NULLS LAST"
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
