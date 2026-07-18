"""Notifications feed API."""
from fastapi import APIRouter, Request, Depends, HTTPException
from src.api.routers.auth import get_current_user

router = APIRouter(prefix="/v2/notifications", tags=["notifications"])


def _uid(user: dict) -> str:
    return str(user["sub"])  # users.user_id is UUID


@router.get("")
async def list_notifications(request: Request, unread_only: bool = False, limit: int = 50, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    clause = "AND is_read = FALSE" if unread_only else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT notification_id, agent_id, title, body, is_read, created_at
                FROM notifications WHERE user_id = $1::uuid {clause}
                ORDER BY created_at DESC LIMIT $2""",
            _uid(user), min(limit, 200))
    return {"notifications": [dict(r) for r in rows]}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE notifications SET is_read = TRUE WHERE notification_id=$1 AND user_id=$2::uuid",
            notification_id, _uid(user))
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="notification not found")
    return {"marked_read": notification_id}
