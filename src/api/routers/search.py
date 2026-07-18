"""Search router for FastAPI."""

from typing import Any
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/search", tags=["search"])

@router.get("")
async def global_search(request: Request, q: str) -> dict[str, Any]:
    """Search for wallets."""
    if len(q) < 2:
        return {"wallets": []}

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    search_term = f"%{q}%"
    
    wallets_query = """
    SELECT address, win_rate, total_volume
    FROM wallet_stats
    WHERE address ILIKE $1
    ORDER BY total_volume DESC NULLS LAST
    LIMIT 5
    """

    markets_query = """
    SELECT market_id, title, status
    FROM markets
    WHERE title ILIKE $1
    LIMIT 5
    """
    
    async with pool.acquire() as conn:
        wallets = await conn.fetch(wallets_query, search_term)
        
    return {
        "wallets": [dict(w) for w in wallets],
    }
