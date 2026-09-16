from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/alpha-calls", tags=["alpha-calls"])


@router.get("/smart-money")
async def get_smart_money_alerts(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    alert_type: Optional[str] = None,
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
        sma.*,
        tw.total_volume as wallet_total_volume,
        tw.balance as wallet_balance,
        tw.position_value as wallet_position_value
    FROM smart_money_alerts sma
    LEFT JOIN tracked_wallets tw ON sma.address = tw.address
    WHERE 1=1
    """
    
    count_query = """
    SELECT COUNT(*) 
    FROM smart_money_alerts sma
    WHERE 1=1
    """
    
    args: list[Any] = []
    
    if alert_type:
        args.append(alert_type)
        query += f" AND sma.alert_type = ${len(args)}"
        count_query += f" AND sma.alert_type = ${len(args)}"
        
    if category:
        args.append(category)
        query += f" AND sma.category = ${len(args)}"
        count_query += f" AND sma.category = ${len(args)}"
        
    if subcategory:
        args.append(subcategory)
        query += f" AND sma.subcategory = ${len(args)}"
        count_query += f" AND sma.subcategory = ${len(args)}"
        
    if tier and tier != "all":
        if tier == "Tier 4":
            query += " AND sma.amount_usdc >= 100000"
            count_query += " AND sma.amount_usdc >= 100000"
        elif tier == "Tier 3":
            query += " AND sma.amount_usdc >= 50000 AND sma.amount_usdc < 100000"
            count_query += " AND sma.amount_usdc >= 50000 AND sma.amount_usdc < 100000"
        elif tier == "Tier 2":
            query += " AND sma.amount_usdc >= 20000 AND sma.amount_usdc < 50000"
            count_query += " AND sma.amount_usdc >= 20000 AND sma.amount_usdc < 50000"
        elif tier == "Tier 1":
            query += " AND sma.amount_usdc >= 5000 AND sma.amount_usdc < 20000"
            count_query += " AND sma.amount_usdc >= 5000 AND sma.amount_usdc < 20000"
        
    query += f" ORDER BY sma.created_at DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
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
