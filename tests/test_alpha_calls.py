import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_submit_user_call_unauthenticated(async_client: AsyncClient):
    """Unauthenticated requests to user call submission should be rejected."""
    response = await async_client.post("/api/alpha-calls/users", json={
        "market_id": "market_123",
        "call_direction": "YES",
        "rationale": "High volume observed"
    })
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_user_call_success(auth_client: AsyncClient):
    """Authenticated user can submit an alpha call."""
    # First ensure a valid active market exists in the test DB
    pool = auth_client._transport.app.state.pool  # type: ignore[union-attr]
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO markets (market_id, event_id, token_id, title, status, created_at)
            VALUES ('test_market_999', 'test_event_999', 'token_999', 'Test Market', 'active', NOW())
            ON CONFLICT (market_id) DO NOTHING
        """)

    payload = {
        "market_id": "test_market_999",
        "call_direction": "NO",
        "rationale": "Integration test submission"
    }
    response = await auth_client.post("/api/alpha-calls/users", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "call_id" in data


@pytest.mark.asyncio
async def test_get_user_calls(auth_client: AsyncClient):
    """Authenticated user can fetch user alpha calls."""
    response = await auth_client.get("/api/alpha-calls/users?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "calls" in data


@pytest.mark.asyncio
async def test_get_smart_money_alerts(async_client: AsyncClient):
    """Smart money alerts endpoint is publicly accessible."""
    response = await async_client.get("/api/alpha-calls/smart-money?limit=5")
    assert response.status_code == 200
    assert "alerts" in response.json()
