from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException

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
        wm.total_volume as wallet_total_volume,
        wm.balance as wallet_balance,
        wm.position_value as wallet_position_value
    FROM wallet_activity_v2 a
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR w.tier = 'MIGHT_COOK' OR wm.total_volume >= 10000)
    """
    
    count_query = """
    SELECT COUNT(*) 
    FROM wallet_activity_v2 a
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR w.tier = 'MIGHT_COOK' OR wm.total_volume >= 10000)
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
        if tier == "Tier 4":
            query += " AND a.amount_usdc >= 100000"
            count_query += " AND a.amount_usdc >= 100000"
        elif tier == "Tier 3":
            query += " AND a.amount_usdc >= 50000 AND a.amount_usdc < 100000"
            count_query += " AND a.amount_usdc >= 50000 AND a.amount_usdc < 100000"
        elif tier == "Tier 2":
            query += " AND a.amount_usdc >= 20000 AND a.amount_usdc < 50000"
            count_query += " AND a.amount_usdc >= 20000 AND a.amount_usdc < 50000"
        elif tier == "Tier 1":
            query += " AND a.amount_usdc >= 5000 AND a.amount_usdc < 20000"
            count_query += " AND a.amount_usdc >= 5000 AND a.amount_usdc < 20000"
        
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
