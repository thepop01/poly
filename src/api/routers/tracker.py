from typing import Any
from fastapi import APIRouter, Request, HTTPException
import logging

router = APIRouter(prefix="/tracker", tags=["tracker"])
logger = logging.getLogger(__name__)

@router.get("/new-markets")
async def get_new_markets(request: Request, limit: int = 50) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    query = """
        SELECT market_id, title, category, end_date, current_price, volume, liquidity, created_at, status
        FROM markets
        WHERE status = 'active'
        ORDER BY created_at DESC
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
        
    return {"markets": [dict(r) for r in rows]}

@router.get("/smart-money")
async def get_smart_money_trades(request: Request, limit: int = 50) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    query = """
        SELECT 
            t.trade_id, t.tx_hash, t.wallet_address, t.market_id, t.side, t.price, t.size, t.timestamp,
            m.title as market_title, m.category,
            ws.win_rate, ws.total_pnl
        FROM trades t
        JOIN markets m ON t.market_id = m.market_id
        JOIN wallet_stats ws ON t.wallet_address = ws.address
        WHERE ws.win_rate > 0.6
        ORDER BY t.timestamp DESC
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
        
    return {"trades": [dict(r) for r in rows]}

@router.get("/whales")
async def get_whale_trades(request: Request, limit: int = 50) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    query = """
        SELECT 
            t.trade_id, t.tx_hash, t.wallet_address, t.market_id, t.side, t.price, t.size, t.timestamp,
            m.title as market_title, m.category
        FROM trades t
        JOIN markets m ON t.market_id = m.market_id
        WHERE t.size >= 10000
        ORDER BY t.timestamp DESC
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
        
    return {"trades": [dict(r) for r in rows]}
