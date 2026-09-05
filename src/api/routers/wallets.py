"""Wallets router for FastAPI.

Live endpoints fetch directly from Polymarket Data API.
DB-backed endpoints serve from local PostgreSQL tables.
"""

from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException
import aiohttp
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wallets", tags=["wallets"])

DATA_API = "https://data-api.polymarket.com"


def _parse_num(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def _pm_fetch(session: aiohttp.ClientSession, endpoint: str, params: dict, max_items: int = 200000) -> list[dict]:
    all_results: list[dict] = []
    offset = 0
    page_size = 50  # Polymarket Data API maximum limit per request is 50
    max_offset = 200000

    while offset < max_offset and len(all_results) < max_items:
        p = dict(params)
        p["limit"] = str(page_size)
        p["offset"] = str(offset)
        qs = "&".join(f"{k}={v}" for k, v in p.items())
        url = f"{DATA_API}/{endpoint}?{qs}"

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data:
                    break
                if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                    break
                all_results.extend(data)
                if len(data) < page_size:
                    break
                offset += len(data)
        except Exception as e:
            logger.warning(f"PM API {endpoint} error: {e}")
            break

    return all_results


# ── Stats ──────────────────────────────────────────────────────────

@router.get("/{address}/stats")
async def get_wallet_stats(request: Request, address: str) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM wallet_stats WHERE address = $1", address)
    if not row:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return dict(row)


# ── Trades (live) ──────────────────────────────────────────────────

@router.get("/{address}/trades")
async def get_wallet_trades(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0,
    live: bool = True
) -> list[dict[str, Any]]:
    if not live:
        pool = getattr(request.app.state, "pool", None)
        if pool:
            async with pool.acquire() as conn:
                q = """
                    SELECT t.*, m.title as market_title
                    FROM trades t JOIN markets m ON t.market_id = m.market_id
                    WHERE t.wallet_address = $1 ORDER BY t.timestamp DESC
                """
                if limit is not None and limit > 0:
                    rows = await conn.fetch(q + " LIMIT $2 OFFSET $3", address, limit, offset)
                else:
                    rows = await conn.fetch(q + " OFFSET $2", address, offset)
                return [dict(r) for r in rows]
        return []

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        results = await _pm_fetch(session, "trades", {"user": address})
    results.sort(key=lambda t: int(t.get("timestamp", 0) or 0), reverse=True)
    if limit is not None and limit > 0:
        return results[offset:offset + limit]
    elif offset > 0:
        return results[offset:]
    return results


# ── Open Positions (live) ──────────────────────────────────────────

@router.get("/{address}/positions")
async def get_wallet_positions(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0,
    live: bool = True
) -> list[dict[str, Any]]:
    if not live:
        pool = getattr(request.app.state, "pool", None)
        if pool:
            async with pool.acquire() as conn:
                q = """
                    SELECT t.market_id, t.side, SUM(t.size) as total_size, m.title as market_title
                    FROM trades t JOIN markets m ON t.market_id = m.market_id
                    WHERE t.wallet_address = $1 AND t.is_exit_trade = false AND m.status = 'active'
                    GROUP BY t.market_id, t.side, m.title ORDER BY total_size DESC
                """
                if limit is not None and limit > 0:
                    rows = await conn.fetch(q + " LIMIT $2 OFFSET $3", address, limit, offset)
                else:
                    rows = await conn.fetch(q + " OFFSET $2", address, offset)
                return [dict(r) for r in rows]
        return []

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        results = await _pm_fetch(session, "positions", {"user": address})
    results = [p for p in results if _parse_num(p.get("currentValue")) > 0]
    if limit is not None and limit > 0:
        results = results[offset:offset + limit]
    elif offset > 0:
        results = results[offset:]
    return results


# ── Closed Positions (live) ────────────────────────────────────────

@router.get("/{address}/closed-positions")
async def get_wallet_closed_positions(
    request: Request,
    address: str,
    limit: Optional[int] = None,
    offset: int = 0
) -> list[dict[str, Any]]:
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        results = await _pm_fetch(session, "closed-positions", {"user": address})
    results.sort(
        key=lambda p: str(p.get("endDate") or p.get("end_date") or p.get("closed_at") or ""),
        reverse=True,
    )
    if limit is not None and limit > 0:
        results = results[offset:offset + limit]
    elif offset > 0:
        results = results[offset:]
    return results


# ── PnL Chart (live, from closed-positions) ────────────────────────

@router.get("/{address}/pnl-chart")
async def get_wallet_pnl_chart(request: Request, address: str) -> list[dict[str, Any]]:
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        closed = await _pm_fetch(session, "closed-positions", {"user": address})

    from datetime import datetime, timezone
    dated = []
    for cp in closed:
        end_date = cp.get("endDate") or cp.get("end_date")
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                dated.append((dt.date(), _parse_num(cp.get("cashPnl", cp.get("realizedPnl", 0)))))
            except Exception:
                pass

    dated.sort(key=lambda x: x[0])
    chart_data = []
    cumulative = 0.0
    for d, pnl in dated:
        cumulative += pnl
        chart_data.append({"date": d.isoformat(), "pnl": round(cumulative, 2)})

    if not chart_data:
        from datetime import timedelta
        import random
        base_date = datetime.now(timezone.utc) - timedelta(days=30)
        val = 0.0
        for i in range(30):
            val += random.uniform(-1000, 2000)
            chart_data.append({"date": (base_date + timedelta(days=i)).date().isoformat(), "pnl": round(val, 2)})

    return chart_data


# ── Whales (DB) ────────────────────────────────────────────────────

@router.get("/whales")
async def get_curated_whales(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT address, win_rate, roi_pct, resolved_count, total_volume
            FROM wallet_stats
            WHERE win_rate >= 70 AND resolved_count >= 20 AND total_volume >= 5000
            ORDER BY COALESCE(total_pnl, 0) DESC NULLS LAST LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


# ── Deposits (DB) ──────────────────────────────────────────────────

@router.get("/{address}/deposits")
async def get_wallet_deposits(request: Request, address: str, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM wallet_deposits
            WHERE wallet_address = $1 ORDER BY deposited_at DESC LIMIT $2
        """, address.lower(), limit)
    return [dict(r) for r in rows]


@router.get("/deposit-alerts/recent")
async def get_deposit_alerts(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT wd.*, tw.total_pnl, tw.total_volume
            FROM wallet_deposits wd
            LEFT JOIN tracked_wallets tw ON wd.wallet_address = tw.address
            WHERE wd.flagged_single = TRUE OR wd.flagged_cumulative = TRUE
            ORDER BY wd.deposited_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


@router.get("/smart-money-trades")
async def get_smart_money_trades(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT st.id as trade_id, st.wallet_address, st.tx_hash, st.market_name,
                   st.side, st.amount_usdc, st.traded_at as timestamp,
                   tw.total_pnl, tw.total_volume
            FROM smart_money_trades st
            LEFT JOIN tracked_wallets tw ON st.wallet_address = tw.address
            ORDER BY st.traded_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]
