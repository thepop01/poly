from typing import Any
from fastapi import APIRouter, Request, HTTPException, Depends
import logging

from .auth import get_current_user

router = APIRouter(prefix="/tracker", tags=["tracker"])
logger = logging.getLogger(__name__)

@router.get("/new-markets")
async def get_new_markets(request: Request, limit: int = 50) -> dict[str, Any]:
    # We no longer track markets in the 10-table schema for the frontend (they are in PM API).
    # Since markets table was dropped, we return empty list.
    return {"markets": []}

@router.get("/smart-money")
async def get_smart_money_trades(request: Request, limit: int = 50) -> dict[str, Any]:
    # Trades were dropped. Rely on alpha_calls_v2.py for smart money.
    return {"trades": []}

@router.get("/whales")
async def get_whale_trades(request: Request, limit: int = 50) -> dict[str, Any]:
    # Trades were dropped.
    return {"trades": []}

# ---------------------------------------------------------------------------
# USER TRACKER LISTS (named wallet lists with notes)
# ---------------------------------------------------------------------------

@router.get("/lists")
async def get_tracker_lists(request: Request, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
        SELECT tl.id, tl.name, tl.created_at,
               COUNT(tlw.wallet_address) as wallet_count
        FROM tracker_lists tl
        LEFT JOIN tracker_list_wallets tlw ON tl.id = tlw.list_id
        WHERE tl.user_id = $1
        GROUP BY tl.id, tl.name, tl.created_at
        ORDER BY tl.created_at DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id)

    return {"lists": [dict(r) for r in rows]}


@router.post("/lists")
async def create_tracker_list(request: Request, name: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO tracker_lists (user_id, name) VALUES ($1, $2)
               ON CONFLICT (user_id, name) DO NOTHING
               RETURNING id, name, created_at""",
            user_id, name,
        )
    if not row:
        raise HTTPException(status_code=409, detail="List with this name already exists")

    return {"list": dict(row)}


@router.delete("/lists/{list_id}")
async def delete_tracker_list(request: Request, list_id: int, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM tracker_lists WHERE id = $1 AND user_id = $2",
            list_id, user_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="List not found")

    return {"ok": True}


@router.patch("/lists/{list_id}")
async def rename_tracker_list(request: Request, list_id: int, name: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE tracker_lists
               SET name = $3
               WHERE id = $1 AND user_id = $2
               RETURNING id, name, created_at""",
            list_id, user_id, name,
        )
    if not row:
        raise HTTPException(status_code=404, detail="List not found")

    return {"list": dict(row)}



@router.get("/lists/{list_id}/wallets")
async def get_tracker_list_wallets(request: Request, list_id: int, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    query = """
        SELECT tlw.wallet_address, tlw.note, tlw.added_at,
               tw.username, m.pm_pnl as website_pnl,
               tw.is_dormant, tw.last_trade_at,
               NULL as category, NULL as subcategory
        FROM tracker_list_wallets tlw
        LEFT JOIN wallets_v2 tw ON tlw.wallet_address = tw.address
        LEFT JOIN wallet_metrics_v2 m ON tw.address = m.address
        WHERE tlw.list_id = $1
        ORDER BY tlw.added_at DESC
    """
    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT user_id FROM tracker_lists WHERE id = $1", list_id)
        if not owner:
            raise HTTPException(status_code=404, detail="List not found")
        if str(owner) != str(user_id):
            raise HTTPException(status_code=403, detail="Not your list")

        rows = await conn.fetch(query, list_id)

    return {"wallets": [dict(r) for r in rows]}


@router.post("/lists/{list_id}/wallets")
async def add_wallet_to_tracker_list(request: Request, list_id: int, wallet_address: str, note: str = "", user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT user_id FROM tracker_lists WHERE id = $1", list_id)
        if not owner:
            raise HTTPException(status_code=404, detail="List not found")
        if str(owner) != str(user_id):
            raise HTTPException(status_code=403, detail="Not your list")

        row = await conn.fetchrow(
            """INSERT INTO tracker_list_wallets (list_id, wallet_address, note)
               VALUES ($1, $2, $3)
               ON CONFLICT (list_id, wallet_address) DO UPDATE SET note = $3
               RETURNING wallet_address, note, added_at""",
            list_id, wallet_address.lower(), note,
        )

    return {"wallet": dict(row)}


@router.delete("/lists/{list_id}/wallets/{wallet_address}")
async def remove_wallet_from_tracker_list(request: Request, list_id: int, wallet_address: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    user_id = user["sub"]

    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT user_id FROM tracker_lists WHERE id = $1", list_id)
        if not owner:
            raise HTTPException(status_code=404, detail="List not found")
        if str(owner) != str(user_id):
            raise HTTPException(status_code=403, detail="Not your list")

        await conn.execute(
            "DELETE FROM tracker_list_wallets WHERE list_id = $1 AND wallet_address = $2",
            list_id, wallet_address.lower(),
        )

    return {"ok": True}
