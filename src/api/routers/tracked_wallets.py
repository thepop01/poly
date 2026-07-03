"""API router for tracked wallets."""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
import time
import aiohttp
import logging

from src.utils.alchemy_client import alchemy_get_token_balances, USDC_CONTRACT
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wallets", tags=["wallets"])

_cache: dict = {}
CACHE_TTL = 120  # 2 minutes


@router.get("/tracked")
async def get_tracked_wallets(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "total_pnl",
    timeframe: str = "all",          # all | monthly | weekly
    source: Optional[str] = None,    # pnl_alltime | volume_alltime | whale_trade | etc.
    min_win_rate: Optional[float] = None,
    min_volume: Optional[float] = None,
    min_trade_size: Optional[float] = None,
    min_realized_pnl: Optional[float] = None,
) -> dict[str, Any]:
    """
    Get the tracked high-performance wallets.
    Supports sorting by PnL, volume, win_rate, roi_pct.
    Timeframe filters to weekly or monthly columns.
    """
    cache_key = f"{limit}_{offset}_{sort_by}_{timeframe}_{source}_{min_win_rate}_{min_volume}_{min_trade_size}_{min_realized_pnl}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["time"] < CACHE_TTL:
        return cached["data"]

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    # Map timeframe to column prefix
    col_map = {
        "weekly":  {"pnl": "pnl_weekly",  "volume": "volume_weekly"},
        "monthly": {"pnl": "pnl_monthly", "volume": "volume_monthly"},
        "all":     {"pnl": "total_pnl",   "volume": "total_volume"},
    }
    tf = col_map.get(timeframe, col_map["all"])

    # Resolve sort column
    allowed_sorts = {
        "total_pnl":    tf["pnl"],
        "total_volume": tf["volume"],
        "win_rate":     "win_rate",
        "roi_pct":      "roi_pct",
        "alpha_score":  "alpha_score",
        "realized_pnl": "realized_pnl",
        "deposits":     "deposits",
        "withdrawals":  "withdrawals",
        "balance":      "balance",
    }
    sort_col = allowed_sorts.get(sort_by, tf["pnl"])

    conditions = []
    args: list[Any] = []

    if source:
        conditions.append(f"${len(args)+1} = ANY(discovery_source)")
        args.append(source)

    if min_win_rate is not None:
        conditions.append(f"win_rate >= ${len(args)+1}")
        args.append(min_win_rate)
        
    if min_volume is not None:
        conditions.append(f"total_volume >= ${len(args)+1}")
        args.append(min_volume)
        
    if min_trade_size is not None:
        conditions.append(f"max_trade_size >= ${len(args)+1}")
        args.append(min_trade_size)
        
    if min_realized_pnl is not None:
        conditions.append(f"realized_pnl >= ${len(args)+1}")
        args.append(min_realized_pnl)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            tw.address,
            tw.discovery_source,
            tw.total_pnl,
            tw.realized_pnl,
            tw.unrealized_pnl,
            tw.total_volume,
            tw.pnl_weekly,
            tw.pnl_monthly,
            tw.volume_weekly,
            tw.volume_monthly,
            tw.win_rate,
            tw.roi_pct,
            tw.resolved_count,
            tw.winning_count,
            tw.tier,
            tw.alpha_score,
            tw.added_at,
            tw.last_indexed,
            tw.max_trade_size,
            tw.balance,
            tw.deposits,
            tw.withdrawals,
            EXISTS (
                SELECT 1 FROM wallet_deposits wd 
                WHERE wd.wallet_address = tw.address 
                  AND wd.deposited_at > NOW() - INTERVAL '48 hours'
                  AND (wd.flagged_single = TRUE OR wd.flagged_cumulative = TRUE)
            ) as has_recent_deposit
        FROM tracked_wallets tw
        {where_clause.replace("win_rate", "tw.win_rate").replace("discovery_source", "tw.discovery_source")}
        ORDER BY tw.{sort_col} DESC NULLS LAST
        LIMIT ${len(args)+1} OFFSET ${len(args)+2}
    """
    args.extend([limit, offset])

    count_query = f"""
        SELECT COUNT(*)
        FROM tracked_wallets tw
        {where_clause.replace("win_rate", "tw.win_rate").replace("discovery_source", "tw.discovery_source")}
    """
    
    async with pool.acquire() as conn:
        total_count = await conn.fetchval(count_query, *args[:-2]) if args else await conn.fetchval(count_query)
        rows = await conn.fetch(query, *args)

    data = [dict(r) for r in rows]
    result = {"wallets": data, "total_count": total_count}
    _cache[cache_key] = {"time": time.time(), "data": result}
    return result


@router.get("/tracked/count")
async def get_tracked_wallet_count(request: Request) -> dict[str, int]:
    """Return total count of tracked wallets."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as count FROM tracked_wallets")
    return {"count": row["count"]}


@router.get("/tracked/{address}")
async def get_tracked_wallet(request: Request, address: str) -> dict[str, Any]:
    """Get full stats for a specific tracked wallet."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tracked_wallets WHERE address = $1",
            address.lower()
        )
    if not row:
        raise HTTPException(status_code=404, detail="Wallet not tracked")
    return dict(row)


@router.post("/queue/{address}")
async def add_to_discovery_queue(request: Request, address: str) -> dict[str, str]:
    """Manually add a wallet to the discovery queue."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO wallet_discovery_queue (address, spotted_at, processed)
            VALUES ($1, NOW(), FALSE)
            ON CONFLICT (address) DO NOTHING
        """, address.lower())
    return {"status": "queued", "address": address.lower()}


async def _fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    try:
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception:
        pass
    return 0.0


async def _fetch_positions(session: aiohttp.ClientSession, address: str) -> tuple[float, int]:
    position_value = 0.0
    open_count = 0
    offset = 0
    limit = 500
    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data or not isinstance(data, list):
                    break
                for pos in data:
                    curr_val = float(pos.get("currentValue", 0) or 0)
                    if curr_val > 0:
                        position_value += curr_val
                        open_count += 1
                if len(data) < limit:
                    break
                offset += limit
        except Exception:
            break
    return position_value, open_count


@router.post("/tracked/{address}")
async def add_tracked_wallet_direct(
    request: Request,
    address: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Directly add a wallet to tracked_wallets (bypasses discovery queue).
    Fetches live balance and positions from Alchemy + Polymarket API."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    address = address.lower()
    logger.info(f"Direct add requested for wallet {address[:10]}... by user {user.get('sub', 'unknown')}")

    # Check if already tracked
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT 1 FROM tracked_wallets WHERE address = $1", address)
        if existing:
            raise HTTPException(status_code=409, detail="Wallet already tracked")

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        balance = await _fetch_balance(session, address)
        position_value, open_count = await _fetch_positions(session, address)

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO tracked_wallets (
                address, discovery_source, total_pnl, realized_pnl, unrealized_pnl, total_volume,
                pnl_weekly, pnl_monthly, volume_weekly, volume_monthly,
                win_rate, roi_pct, resolved_count, winning_count, tier, alpha_score,
                last_indexed, max_trade_size, balance, deposits, withdrawals, position_value,
                start_balance, start_deposits, start_withdrawals, start_stats_at
            ) VALUES ($1, $2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'Silver', 0, NOW(), 0, $3, 0, 0, $4,
                     $3, 0, 0, NOW())
            ON CONFLICT (address) DO UPDATE SET
                balance = EXCLUDED.balance,
                position_value = EXCLUDED.position_value,
                last_indexed = NOW()
        """, address, ["Manual"], balance, position_value)

        await conn.execute("""
            INSERT INTO wallet_stats (
                address, total_pnl, total_volume, win_rate, roi_pct,
                resolved_count, winning_count, active_days,
                avg_position_size, avg_hold_time_hours,
                biggest_win, biggest_loss, unrealised_pnl,
                tier, alpha_score, last_updated,
                trades_2x, trades_1_5x, strategy, added_reason
            ) VALUES ($1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 'Silver', 0, NOW(), 0, 0, 'Unknown', 'Manual')
            ON CONFLICT (address) DO NOTHING
        """, address)

        # Also queue for worker processing
        await conn.execute("""
            INSERT INTO wallet_discovery_queue (address, spotted_at, processed, source)
            VALUES ($1, NOW(), FALSE, 'Manual')
            ON CONFLICT (address) DO UPDATE SET
                processed = FALSE,
                source = CASE WHEN wallet_discovery_queue.source = 'Unknown' THEN 'Manual' ELSE wallet_discovery_queue.source END
        """, address)

    logger.info(f"Wallet {address[:10]}... added directly | balance=${balance:,.2f} pos_val=${position_value:,.2f} open_pos={open_count}")
    return {
        "status": "added",
        "address": address,
        "balance": balance,
        "position_value": position_value,
        "open_positions": open_count,
    }
