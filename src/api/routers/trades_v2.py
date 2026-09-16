from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/v2/trades", tags=["trades-v2"])

class TradeResponseV2(BaseModel):
    trade_id: int
    tx_hash: Optional[str]
    wallet_address: str
    condition_id: Optional[str]
    market_title: Optional[str]
    side: Optional[str]
    size: float
    timestamp: datetime
    tier: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None

@router.get("", response_model=List[TradeResponseV2])
async def get_recent_trades(request: Request, limit: int = 50, min_size: Optional[float] = None):
    """Fetch the most recent global trades from V2 activity table."""
    pool = request.app.state.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")

    query = """
        SELECT 
            t.id as trade_id, t.tx_hash, t.address as wallet_address, t.condition_id, 
            t.title as market_title, t.outcome as side, t.amount_usdc as size, t.event_at as timestamp,
            w.tier, m.category, m.subcategory
        FROM wallet_activity_v2 t
        LEFT JOIN wallets_v2 w ON t.address = w.address
        LEFT JOIN markets_v2 m ON t.condition_id = m.condition_id
        WHERE t.event_type = 'TRADE'
    """
    
    args = []
    if min_size is not None:
        query += " AND t.amount_usdc >= $1"
        args.append(min_size)
        limit_idx = 2
    else:
        limit_idx = 1
        
    query += f" ORDER BY t.event_at DESC LIMIT ${limit_idx}"
    args.append(min(limit, 100))

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import Response

@router.get("/export")
async def export_trades(request: Request, condition_id: Optional[str] = None):
    pool = request.app.state.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")

    query = """
        SELECT 
            t.id as trade_id, t.tx_hash, t.address as wallet_address, t.condition_id, 
            t.title as market_title, t.outcome as side, t.amount_usdc as size, t.event_at as timestamp
        FROM wallet_activity_v2 t
        WHERE t.event_type = 'TRADE'
    """
    
    args = []
    if condition_id:
        query += " AND t.condition_id = $1"
        args.append(condition_id)
        
    query += " ORDER BY t.event_at DESC LIMIT 1000"

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            
            if not rows:
                return Response(content="No trades found", media_type="text/plain")

            headers = ["trade_id", "tx_hash", "wallet_address", "condition_id", "market_title", "side", "size", "timestamp"]
            csv_lines = [",".join(headers)]
            for r in rows:
                line = [str(r[h]).replace(",", " ") for h in headers]
                csv_lines.append(",".join(line))
                
            csv_content = "\n".join(csv_lines)
            
            return Response(
                content=csv_content, 
                media_type="text/csv", 
                headers={"Content-Disposition": "attachment; filename=trades_export_v2.csv"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
