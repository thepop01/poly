"""API router V2 for tracked wallets (using new schema)."""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
import time
import aiohttp
import logging

from src.utils.alchemy_client import alchemy_get_token_balances, PUSD_CONTRACT
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/wallets", tags=["tracked-wallets-v2"])

_cache: dict = {}
CACHE_TTL = 120  # 2 minutes


@router.get("/tracked")
async def get_tracked_wallets(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "total_pnl",
    sort_order: str = "desc",
    timeframe: str = "all",          # all | monthly | weekly (legacy, maps to all-time now)
    source: Optional[str] = None,
    min_win_rate: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_position_value: Optional[float] = None,
) -> dict[str, Any]:
    cache_key = f"v2_tracked_{limit}_{offset}_{sort_by}_{sort_order}_{timeframe}_{source}_{min_win_rate}_{min_volume}_{min_position_value}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    allowed_sorts = {
        "total_pnl":    "m.total_pnl",
        "total_volume": "m.total_volume",
        "win_rate":     "m.win_rate",
        "roi_pct":      "m.roi_pct",
        "deposits":     "m.deposits",
        "withdrawals":  "m.withdrawals",
        "balance":      "m.balance",
    }
    sort_col = allowed_sorts.get(sort_by, "m.total_pnl")
    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

    conditions = ["w.tier != 'UNCLASSIFIED'"]
    args: list[Any] = []

    if source:
        conditions.append(
            f"EXISTS (SELECT 1 FROM wallet_sources_v2 sf WHERE sf.address = w.address AND sf.source = ${len(args)+1})"
        )
        args.append(source)

    if min_win_rate is not None:
        conditions.append(f"m.win_rate >= ${len(args)+1}")
        args.append(min_win_rate)
        
    if min_volume is not None:
        conditions.append(f"m.total_volume >= ${len(args)+1}")
        args.append(min_volume)
        
    if min_position_value is not None:
        conditions.append(f"COALESCE(m.position_value, 0) >= ${len(args)+1}")
        args.append(min_position_value)
        
    where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            w.address,
            (SELECT s.source FROM wallet_sources_v2 s
              WHERE s.address = w.address ORDER BY s.spotted_at LIMIT 1) as discovery_source,
            m.total_pnl,
            m.total_volume,
            w.added_at,
            w.updated_at as last_indexed,
            COALESCE(m.position_value, 0) as position_value,
            m.balance,
            m.deposits,
            m.withdrawals,
            EXISTS (
                SELECT 1 FROM wallet_activity_v2 wa 
                WHERE wa.address = w.address 
                  AND wa.event_type = 'DEPOSIT'
                  AND wa.event_at > NOW() - INTERVAL '48 hours'
                  AND wa.amount_usdc >= 50000
            ) as has_recent_deposit
        FROM wallets_v2 w
        JOIN wallet_metrics_v2 m ON w.address = m.address
        {where_clause}
        ORDER BY {sort_col} {order_dir} NULLS LAST
        LIMIT ${len(args)+1} OFFSET ${len(args)+2}
    """
    args.extend([limit, offset])

    count_query = f"""
        SELECT COUNT(*)
        FROM wallets_v2 w
        JOIN wallet_metrics_v2 m ON w.address = m.address
        {where_clause}
    """
    
    async with pool.acquire() as conn:
        total_count = await conn.fetchval(count_query, *args[:-2]) if args[:-2] else await conn.fetchval(count_query)
        rows = await conn.fetch(query, *args)

    data = [dict(r) for r in rows]
    result = {"wallets": data, "total_count": total_count}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


@router.get("/tracked/count")
async def get_tracked_wallet_count(request: Request) -> dict[str, int]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as count FROM wallets_v2")
    return {"count": row["count"]}


@router.post("/queue/{address}")
async def add_to_discovery_queue(request: Request, address: str) -> dict[str, str]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO wallets_v2 (address, tier, tier_reason, added_at, updated_at)
                VALUES ($1, 'UNCLASSIFIED', 'Manual Queue', NOW(), NOW())
                ON CONFLICT (address) DO NOTHING
            """, address.lower())
            
            await conn.execute("""
                INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
                VALUES ($1, 'CUSTOM', 'Manually queued by user/admin', NOW())
                ON CONFLICT (address) DO NOTHING
            """, address.lower())
    return {"status": "queued", "address": address.lower()}
