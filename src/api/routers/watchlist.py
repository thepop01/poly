"""Watchlist router for FastAPI."""

from typing import Any
from fastapi import APIRouter, Request, HTTPException, Depends
from .auth import get_current_user

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

@router.get("")
async def get_watchlist(request: Request, user: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
    SELECT tw.*, uw.alerts_enabled 
    FROM user_watchlists uw
    LEFT JOIN tracked_wallets tw ON uw.wallet_address = tw.address
    WHERE uw.user_id = $1::uuid
    ORDER BY uw.added_at DESC
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id)
        
    return [dict(r) for r in rows]

@router.post("/{address}")
async def add_to_watchlist(request: Request, address: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Add a wallet to the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
    INSERT INTO user_watchlists (user_id, wallet_address)
    VALUES ($1::uuid, $2)
    ON CONFLICT DO NOTHING
    """
    
    discovery_query = """
    INSERT INTO wallet_discovery_queue (address, spotted_at, processed, source)
    VALUES ($1, NOW(), FALSE, 'User Watchlist')
    ON CONFLICT (address) DO UPDATE SET
        processed = FALSE,
        source = CASE WHEN wallet_discovery_queue.source = 'Unknown' THEN 'User Watchlist' ELSE wallet_discovery_queue.source END
    """
    
    async with pool.acquire() as conn:
        await conn.execute(query, user_id, address)
        # Queue the wallet for evaluation — workers will backfill stats into tracked_wallets
        await conn.execute(discovery_query, address)
        
    return {"status": "added", "address": address}

@router.delete("/{address}")
async def remove_from_watchlist(request: Request, address: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Remove a wallet from the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
    DELETE FROM user_watchlists 
    WHERE user_id = $1::uuid AND wallet_address = $2
    """
    
    async with pool.acquire() as conn:
        await conn.execute(query, user_id, address)
        
    return {"status": "removed", "address": address}

@router.post("/{address}/alerts")
async def toggle_watchlist_alerts(request: Request, address: str, enabled: bool, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Toggle alerts for a specific wallet in the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
    UPDATE user_watchlists 
    SET alerts_enabled = $3
    WHERE user_id = $1::uuid AND wallet_address = $2
    RETURNING alerts_enabled
    """
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id, address, enabled)
        if not row:
            raise HTTPException(status_code=404, detail="Wallet not found in user watchlist")
            
    return {"status": "success", "address": address, "alerts_enabled": row["alerts_enabled"]}
