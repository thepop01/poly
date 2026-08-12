from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from .auth import get_current_user

router = APIRouter(prefix="/v2/alpha-calls", tags=["alpha-calls-v2"])


@router.get("/smart-money")
async def get_smart_money_alerts(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    alert_type: Optional[str] = None,  # TRADE or DEPOSIT
    tier: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
) -> dict[str, Any]:
    """Get the live feed of smart money alerts (large deposits and trades).
    Optionally filter by alert_type, tier (amount range), or category (e.g. Sports, Politics, Crypto)."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    query = """
    SELECT 
        a.id, a.address, 
        CASE WHEN a.event_type = 'DEPOSIT' THEN 'LARGE_DEPOSIT' ELSE 'LARGE_TRADE' END as alert_type, 
        a.amount_usdc, a.tx_hash as transaction_hash, 
        a.condition_id, a.outcome, a.title as market_title, a.event_at as created_at,
        m.category, m.subcategory,
        w.username as wallet_name,
        w.tier as wallet_tier,
        wm.total_volume as wallet_total_volume,
        wm.balance as wallet_balance,
        wm.position_value as wallet_position_value
    FROM wallet_activity_v2 a
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR wm.total_volume >= 10000)
    AND a.amount_usdc >= 100
    """
    
    count_query = """
    SELECT COUNT(*) 
    FROM wallet_activity_v2 a
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR wm.total_volume >= 10000)
    AND a.amount_usdc >= 100
    """
    
    args: list[Any] = []
    
    if alert_type:
        mapped_type = alert_type.upper()
        if mapped_type == "LARGE_DEPOSIT":
            mapped_type = "DEPOSIT"
            query += " AND a.amount_usdc >= 10000"
            count_query += " AND a.amount_usdc >= 10000"
        elif mapped_type == "LARGE_TRADE":
            mapped_type = "TRADE"
            query += " AND a.amount_usdc >= 1000"
            count_query += " AND a.amount_usdc >= 1000"
            
        args.append(mapped_type)
        query += f" AND a.event_type = ${len(args)}"
        count_query += f" AND a.event_type = ${len(args)}"
        
    if category:
        args.append(category)
        query += f" AND m.category = ${len(args)}"
        count_query += f" AND m.category = ${len(args)}"
        
    if subcategory:
        args.append(subcategory)
        query += f" AND m.subcategory = ${len(args)}"
        count_query += f" AND m.subcategory = ${len(args)}"
        
    if tier and tier != "all":
        t = tier.upper()
        if t in ("TIER 4", "100K", "$100K+"):
            query += " AND a.amount_usdc >= 100000"
            count_query += " AND a.amount_usdc >= 100000"
        elif t in ("TIER 3", "50K", "$50K+"):
            query += " AND a.amount_usdc >= 50000 AND a.amount_usdc < 100000"
            count_query += " AND a.amount_usdc >= 50000 AND a.amount_usdc < 100000"
        elif t in ("TIER 2", "20K", "$20K+"):
            query += " AND a.amount_usdc >= 20000 AND a.amount_usdc < 50000"
            count_query += " AND a.amount_usdc >= 20000 AND a.amount_usdc < 50000"
        elif t in ("TIER 1", "5K", "$5K+"):
            query += " AND a.amount_usdc >= 100 AND a.amount_usdc < 20000"
            count_query += " AND a.amount_usdc >= 100 AND a.amount_usdc < 20000"
        
    query += f" ORDER BY a.event_at DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
    args_with_pagination = args + [limit, offset]
    
    async with pool.acquire() as conn:
        total_count = await conn.fetchval(count_query, *args)
        rows = await conn.fetch(query, *args_with_pagination)
        
        alerts = []
        for r in rows:
            alert = dict(r)
            wallet_stats = {
                "total_volume": alert.pop("wallet_total_volume", None),
                "balance": alert.pop("wallet_balance", None),
                "position_value": alert.pop("wallet_position_value", None)
            }
            if wallet_stats["balance"] is not None:
                wallet_stats["balance"] = float(wallet_stats["balance"])
            if wallet_stats["position_value"] is not None:
                wallet_stats["position_value"] = float(wallet_stats["position_value"])
            alert["wallet_stats"] = wallet_stats
            alerts.append(alert)
            
    return {"alerts": alerts, "total_count": total_count}


@router.get("/summary")
async def get_alpha_calls_summary(request: Request) -> dict[str, Any]:
    """Aggregate stats for the Alpha Calls stat cards, over the smart-money feed."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    # Same universe as the feed: curated / might-cook wallets or >= $10k volume.
    base = """
    FROM wallet_activity_v2 a
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR wm.total_volume >= 10000)
    """

    counts_query = f"""
    SELECT
        COUNT(*) FILTER (WHERE a.event_type = 'TRADE'   AND a.amount_usdc >= 1000)  AS trades,
        COUNT(*) FILTER (WHERE a.event_type = 'DEPOSIT' AND a.amount_usdc >= 10000) AS deposits,
        COALESCE(SUM(a.amount_usdc) FILTER (WHERE a.event_type = 'DEPOSIT' AND a.amount_usdc >= 10000), 0) AS deposit_inflow
    {base}
    """

    biggest_query = f"""
    SELECT a.amount_usdc, a.address, w.username AS wallet_name
    {base}
      AND ((a.event_type = 'TRADE' AND a.amount_usdc >= 1000)
        OR (a.event_type = 'DEPOSIT' AND a.amount_usdc >= 10000))
    ORDER BY a.amount_usdc DESC
    LIMIT 1
    """

    async with pool.acquire() as conn:
        counts = await conn.fetchrow(counts_query)
        biggest = await conn.fetchrow(biggest_query)

    trades = int(counts["trades"] or 0)
    deposits = int(counts["deposits"] or 0)
    return {
        "live_events": trades + deposits,
        "trades": trades,
        "deposits": deposits,
        "deposit_inflow": float(counts["deposit_inflow"] or 0),
        "biggest": {
            "amount": float(biggest["amount_usdc"]) if biggest else 0,
            "address": biggest["address"] if biggest else None,
            "wallet_name": biggest["wallet_name"] if biggest else None,
        },
    }


@router.get("/tracked-alerts")
async def get_tracked_wallet_alerts(
    request: Request,
    limit: int = 20,
    user: dict = Depends(get_current_user)
) -> dict[str, Any]:
    """Get recent smart-money activity alerts filtered to wallets in the user's watchlist."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
    SELECT 
        a.id, a.address, 
        CASE WHEN a.event_type = 'DEPOSIT' THEN 'LARGE_DEPOSIT' ELSE 'LARGE_TRADE' END as alert_type, 
        a.amount_usdc, a.tx_hash as transaction_hash, 
        a.condition_id, a.outcome, a.title as market_title, a.event_at as created_at,
        m.category, m.subcategory,
        w.username as wallet_name,
        w.tier as wallet_tier,
        wm.total_volume as wallet_total_volume,
        wm.balance as wallet_balance,
        wm.position_value as wallet_position_value
    FROM wallet_activity_v2 a
    JOIN user_watchlists uw ON LOWER(a.address) = LOWER(uw.wallet_address)
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON LOWER(a.address) = LOWER(w.address)
    JOIN wallet_metrics_v2 wm ON LOWER(a.address) = LOWER(wm.address)
    WHERE uw.user_id = $1::uuid
    ORDER BY a.event_at DESC
    LIMIT $2
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, limit)

    result = []
    for r in rows:
        item = dict(r)
        item["wallet_stats"] = {
            "total_volume": float(r["wallet_total_volume"]) if r["wallet_total_volume"] is not None else None,
            "balance": float(r["wallet_balance"]) if r["wallet_balance"] is not None else None,
            "position_value": float(r["wallet_position_value"]) if r["wallet_position_value"] is not None else None,
        }
        item["amount_usdc"] = float(r["amount_usdc"]) if r["amount_usdc"] is not None else 0.0
        result.append(item)

    return {"alerts": result}

