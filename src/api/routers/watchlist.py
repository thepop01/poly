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
    SELECT
        tw.address, tw.username, tw.tier, tw.is_dormant, tw.last_trade_at,
        wm.total_pnl AS pnl, wm.roi_pct, wm.win_rate,
        wm.balance, wm.total_volume AS volume, wm.position_value,
        uw.alerts_enabled, uw.added_at
    FROM user_watchlists uw
    LEFT JOIN wallets_v2 tw ON uw.wallet_address = tw.address
    LEFT JOIN wallet_metrics_v2 wm ON uw.wallet_address = wm.address
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
    
    async with pool.acquire() as conn:
        await conn.execute(query, user_id, address)
        # Note: wallet_discovery_queue was dropped in V2. We can skip it here.
        # If the wallet needs to be discovered, we should just insert into wallets_v2 if it doesn't exist,
        # but that is handled by other workers now.
        
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


@router.get("/status")
async def get_watchlist_status(request: Request, addresses: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Check which addresses from a comma-separated list are in the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]
    addr_list = [a.strip().lower() for a in addresses.split(",") if a.strip()]
    if not addr_list:
        return {"liked": []}

    query = """
    SELECT wallet_address FROM user_watchlists
    WHERE user_id = $1::uuid AND LOWER(wallet_address) = ANY($2::text[])
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, addr_list)

    return {"liked": [r["wallet_address"] for r in rows]}


@router.get("/counts")
async def get_watchlist_counts(request: Request, addresses: str) -> dict[str, Any]:
    """Get the favorite count for a list of addresses."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    addr_list = [a.strip().lower() for a in addresses.split(",") if a.strip()]
    if not addr_list:
        return {"counts": {}}

    query = """
    SELECT LOWER(wallet_address) as wallet_address, COUNT(*)::int as count
    FROM user_watchlists
    WHERE LOWER(wallet_address) = ANY($1::text[])
    GROUP BY LOWER(wallet_address)
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, addr_list)

    counts = {r["wallet_address"]: r["count"] for r in rows}
    return {"counts": counts}

