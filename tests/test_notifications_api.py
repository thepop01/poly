import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_notifications_requires_auth(async_client: AsyncClient):
    resp = await async_client.get("/api/v2/notifications")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_and_mark_read(auth_client: AsyncClient, test_pool):
    # seed a notification for the auth user
    async with test_pool.acquire() as conn:
        uid = await conn.fetchval("SELECT user_id FROM users WHERE email='integration_test@example.com'")
        nid = await conn.fetchval(
            "INSERT INTO notifications (user_id, title, body) VALUES ($1,$2,$3) RETURNING notification_id",
            uid, "hi", "body")
    resp = await auth_client.get("/api/v2/notifications")
    assert resp.status_code == 200
    assert any(n["notification_id"] == nid for n in resp.json()["notifications"])

    resp = await auth_client.post(f"/api/v2/notifications/{nid}/read")
    assert resp.status_code == 200

    async with test_pool.acquire() as conn:
        is_read = await conn.fetchval("SELECT is_read FROM notifications WHERE notification_id=$1", nid)
        assert is_read is True
        await conn.execute("DELETE FROM notifications WHERE notification_id=$1", nid)
