from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/trades", tags=["trades"])

class TradeResponse(BaseModel):
    trade_id: int
    tx_hash: str
    wallet_address: str
    market_id: str
    market_title: str
    token_id: str
    side: str
    price: float
    size: float
    timestamp: datetime
    strategy: Optional[str] = None

@router.get("", response_model=List[TradeResponse])
async def get_recent_trades(request: Request, limit: int = 50, min_size: Optional[float] = None):
    """Fetch the most recent global trades."""
    pool = request.app.state.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")

    query = """
        SELECT 
            t.trade_id, t.tx_hash, t.wallet_address, t.market_id, 
            m.title as market_title, t.token_id, t.side, t.price, t.size, t.timestamp,
            ws.strategy
        FROM trades t
        JOIN markets m ON t.market_id = m.market_id
        LEFT JOIN wallet_stats ws ON t.wallet_address = ws.address
    """
    
    args = []
    if min_size is not None:
        query += " WHERE t.size >= $1"
        args.append(min_size)
        limit_idx = 2
    else:
        limit_idx = 1
        
    query += f" ORDER BY t.timestamp DESC LIMIT ${limit_idx}"
    args.append(min(limit, 100))

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.responses import Response

@router.get("/export")
async def export_trades(request: Request, market_id: Optional[str] = None):
    pool = request.app.state.pool
    if not pool:
        raise HTTPException(status_code=503, detail="Database pool not initialized")

    query = """
        SELECT 
            t.trade_id, t.tx_hash, t.wallet_address, t.market_id, 
            m.title as market_title, t.token_id, t.side, t.price, t.size, t.timestamp
        FROM trades t
        JOIN markets m ON t.market_id = m.market_id
    """
    
    args = []
    if market_id:
        query += " WHERE t.market_id = $1"
        args.append(market_id)
        
    query += " ORDER BY t.timestamp DESC LIMIT 1000"

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            
            if not rows:
                return Response(content="No trades found", media_type="text/plain")

            headers = ["trade_id", "tx_hash", "wallet_address", "market_id", "market_title", "token_id", "side", "price", "size", "timestamp"]
            csv_lines = [",".join(headers)]
            for r in rows:
                line = [str(r[h]).replace(",", " ") for h in headers]
                csv_lines.append(",".join(line))
                
            csv_content = "\n".join(csv_lines)
            
            return Response(
                content=csv_content, 
                media_type="text/csv", 
                headers={"Content-Disposition": "attachment; filename=trades_export.csv"}
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
