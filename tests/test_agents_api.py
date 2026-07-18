import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_agent_requires_auth(async_client: AsyncClient):
    resp = await async_client.post("/api/v2/agents", json={
        "name": "x", "rule_tree": {"op": "and", "children": []}, "actions": []})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_agent(auth_client: AsyncClient):
    payload = {
        "name": "Cheap YES watcher",
        "description": "notify on <15c",
        "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15},
        "actions": [{"action_type": "notify", "params": {"message": "cheap!"}}],
    }
    resp = await auth_client.post("/api/v2/agents", json=payload)
    assert resp.status_code == 200, resp.text
    agent_id = resp.json()["agent_id"]

    resp = await auth_client.get("/api/v2/agents")
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()["agents"]]
    assert "Cheap YES watcher" in names

    # cleanup
    await auth_client.delete(f"/api/v2/agents/{agent_id}")


@pytest.mark.asyncio
async def test_create_agent_rejects_bad_rule_tree(auth_client: AsyncClient):
    payload = {
        "name": "bad",
        "rule_tree": {"field": "not_a_field", "cmp": "lt", "value": 1},
        "actions": [],
    }
    resp = await auth_client.post("/api/v2/agents", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_toggle_active(auth_client: AsyncClient):
    payload = {"name": "toggle me",
        "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15},
        "actions": []}
    agent_id = (await auth_client.post("/api/v2/agents", json=payload)).json()["agent_id"]
    resp = await auth_client.patch(f"/api/v2/agents/{agent_id}", json={"is_active": True})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    await auth_client.delete(f"/api/v2/agents/{agent_id}")
