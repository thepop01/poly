import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.api.routers.auth import create_access_token
from src.research.llm import FakeLLMProvider, ModelAction


@pytest_asyncio.fixture
async def api_pool(test_pool):
    app.state.pool = test_pool
    yield test_pool
    app.state.research_provider_factory = None


async def _make_user(pool, email: str) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    return str(row["user_id"])


def _client(token: str | None = None) -> AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    )


@pytest_asyncio.fixture
async def user_a(api_pool):
    owner_id = await _make_user(api_pool, f"research-a-{uuid.uuid4().hex[:8]}@example.com")
    token = create_access_token(owner_id, "a@example.com")
    yield {"owner_id": owner_id, "token": token}
    async with api_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


@pytest_asyncio.fixture
async def user_b(api_pool):
    owner_id = await _make_user(api_pool, f"research-b-{uuid.uuid4().hex[:8]}@example.com")
    token = create_access_token(owner_id, "b@example.com")
    yield {"owner_id": owner_id, "token": token}
    async with api_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


def _script(actions: list) -> None:
    app.state.research_provider_factory = lambda: FakeLLMProvider(actions)


def _events(response) -> list:
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in response.text.strip().split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


def _terminal(events: list) -> dict:
    terminals = [e for e in events if e["type"] in ("run.completed", "run.failed")]
    assert len(terminals) == 1
    return terminals[0]


@pytest.mark.asyncio
async def test_unauthenticated_requests_are_rejected(api_pool):
    # FastAPI's HTTPBearer challenge is 401; matches every other endpoint here.
    async with _client() as client:
        response = await client.get("/api/v2/research/chats")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_crud_roundtrip(api_pool, user_a):
    async with _client(user_a["token"]) as client:
        created = await client.post("/api/v2/research/chats", json={"title": "Cricket"})
        assert created.status_code == 200
        chat_id = created.json()["chat_id"]

        listed = await client.get("/api/v2/research/chats")
        assert [c["chat_id"] for c in listed.json()["chats"]] == [chat_id]

        fetched = await client.get(f"/api/v2/research/chats/{chat_id}")
        assert fetched.json()["title"] == "Cricket"

        renamed = await client.patch(
            f"/api/v2/research/chats/{chat_id}", json={"title": "T20"})
        assert renamed.json()["title"] == "T20"

        messages = await client.get(f"/api/v2/research/chats/{chat_id}/messages")
        assert messages.json() == {"messages": []}
        panels = await client.get(f"/api/v2/research/chats/{chat_id}/panels")
        assert panels.json() == {"panels": []}

        deleted = await client.delete(f"/api/v2/research/chats/{chat_id}")
        assert deleted.json() == {"deleted": chat_id}
        assert (await client.get(f"/api/v2/research/chats/{chat_id}")).status_code == 404


@pytest.mark.asyncio
async def test_cross_owner_ids_return_404(api_pool, user_a, user_b):
    async with _client(user_a["token"]) as client_a:
        created = await client_a.post("/api/v2/research/chats", json={"title": "Private"})
        chat_id = created.json()["chat_id"]
    async with _client(user_b["token"]) as client_b:
        assert (await client_b.get(f"/api/v2/research/chats/{chat_id}")).status_code == 404
        assert (await client_b.patch(
            f"/api/v2/research/chats/{chat_id}", json={"title": "Hijack"})).status_code == 404
        assert (await client_b.delete(
            f"/api/v2/research/chats/{chat_id}")).status_code == 404
        assert (await client_b.get(
            f"/api/v2/research/chats/{chat_id}/messages")).status_code == 404
        assert (await client_b.get(
            f"/api/v2/research/chats/{chat_id}/panels")).status_code == 404
        assert (await client_b.post(
            f"/api/v2/research/chats/{chat_id}/runs",
            json={"prompt": "hello"})).status_code == 404


@pytest.mark.asyncio
async def test_run_streams_answer_only_events(api_pool, user_a):
    _script([ModelAction(kind="answer", text="Hello. Ready to research.")])
    async with _client(user_a["token"]) as client:
        chat_id = (await client.post(
            "/api/v2/research/chats", json={"title": "Stream"})).json()["chat_id"]
        response = await client.post(
            f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "hello"})
        assert response.status_code == 200
        events = _events(response)
    assert [e["type"] for e in events] == [
        "run.started", "assistant.delta", "assistant.delta", "run.completed"]
    assert _terminal(events)["type"] == "run.completed"


@pytest.mark.asyncio
async def test_run_with_tool_creates_panel_and_pages(api_pool, user_a):
    _script([
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"limit": 3}),
        ModelAction(kind="answer", text="Here are some wallets."),
    ])
    async with _client(user_a["token"]) as client:
        chat_id = (await client.post(
            "/api/v2/research/chats", json={"title": "Panels"})).json()["chat_id"]
        response = await client.post(
            f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "find wallets"})
        events = _events(response)
        assert _terminal(events)["type"] == "run.completed"
        created = next(e for e in events if e["type"] == "result.created")
        assert created["data"]["kind"] == "wallet_set"
        upserted = next(e for e in events if e["type"] == "panel.upserted")

        panels = (await client.get(
            f"/api/v2/research/chats/{chat_id}/panels")).json()["panels"]
        assert len(panels) == 1
        panel_id = panels[0]["panel_id"]
        assert panels[0]["panel_key"] == upserted["data"]["panel"]["panel_key"]

        page = (await client.get(
            f"/api/v2/research/results/{created['data']['result_set_id']}"
            "?offset=0&limit=2")).json()
        assert page["summary"]["result_set_id"] == created["data"]["result_set_id"]
        assert len(page["members"]) <= 2

        minimized = (await client.patch(
            f"/api/v2/research/panels/{panel_id}", json={"state": "minimized"})).json()
        assert minimized["state"] == "minimized"


@pytest.mark.asyncio
async def test_run_failure_is_single_terminal_event(api_pool, user_a):
    _script([ModelAction(kind="tool_call", tool_name="nope", arguments={})])
    async with _client(user_a["token"]) as client:
        chat_id = (await client.post(
            "/api/v2/research/chats", json={"title": "Failure"})).json()["chat_id"]
        response = await client.post(
            f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "go"})
        events = _events(response)
    terminal = _terminal(events)
    assert terminal["type"] == "run.failed"
    assert terminal["data"]["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_second_run_conflicts_while_one_is_active(api_pool, user_a):
    async with _client(user_a["token"]) as client:
        chat_id = (await client.post(
            "/api/v2/research/chats", json={"title": "Busy"})).json()["chat_id"]
        async with api_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO research_runs (chat_id, status, prompt)
                   VALUES ($1::uuid, 'running', 'stuck')""", chat_id)
        conflict = await client.post(
            f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "again"})
        assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_oversized_prompt_is_rejected(api_pool, user_a):
    async with _client(user_a["token"]) as client:
        chat_id = (await client.post(
            "/api/v2/research/chats", json={"title": "Limits"})).json()["chat_id"]
        response = await client.post(
            f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "x" * 4001})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_starts_are_rate_limited_per_user(api_pool):
    # A fresh user gets an isolated 10/minute budget; the 11th start is refused.
    owner_id = await _make_user(api_pool, f"research-rl-{uuid.uuid4().hex[:8]}@example.com")
    try:
        from src.api.routers.auth import create_access_token as _token
        token = _token(owner_id, "rl@example.com")
        _script([ModelAction(kind="answer", text="ok.") for _ in range(10)])
        async with _client(token) as client:
            chat_id = (await client.post(
                "/api/v2/research/chats", json={"title": "Rate"})).json()["chat_id"]
            statuses = []
            for _ in range(11):
                response = await client.post(
                    f"/api/v2/research/chats/{chat_id}/runs", json={"prompt": "hello"})
                statuses.append(response.status_code)
        assert statuses[:10] == [200] * 10
        assert statuses[10] == 429
    finally:
        async with api_pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)
