import uuid

import pytest
import pytest_asyncio

from src.research.repository import ResearchRepository


@pytest_asyncio.fixture
async def two_users(test_pool):
    async with test_pool.acquire() as conn:
        first = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            f"research-first-{uuid.uuid4().hex[:8]}@example.com", "mock_hash",
        )
        second = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            f"research-second-{uuid.uuid4().hex[:8]}@example.com", "mock_hash",
        )
    first_id, second_id = str(first), str(second)
    yield type("Users", (), {"first": first_id, "second": second_id})
    async with test_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM users WHERE user_id IN ($1::uuid, $2::uuid)", first_id, second_id
        )


@pytest.mark.asyncio
async def test_owner_cannot_read_another_users_chat(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Cricket research")
    assert await repo.get_chat(two_users.second, chat.chat_id) is None


@pytest.mark.asyncio
async def test_chat_create_rename_archive_roundtrip(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Cricket research")
    assert chat.title == "Cricket research"

    chats = await repo.list_chats(two_users.first)
    assert [c.chat_id for c in chats] == [chat.chat_id]

    renamed = await repo.rename_chat(two_users.first, chat.chat_id, "T20 deep dive")
    assert renamed is not None and renamed.title == "T20 deep dive"
    assert await repo.rename_chat(two_users.second, chat.chat_id, "Hijacked") is None

    archived = await repo.archive_chat(two_users.first, chat.chat_id, True)
    assert archived is not None and archived.is_archived is True
    assert await repo.list_chats(two_users.first) == []
    reopened = await repo.list_chats(two_users.first, include_archived=True)
    assert [c.chat_id for c in reopened] == [chat.chat_id]


@pytest.mark.asyncio
async def test_messages_keep_order_and_after_id_filter(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Ordering")
    first = await repo.add_message(two_users.first, chat.chat_id, "user", "hello")
    second = await repo.add_message(two_users.first, chat.chat_id, "assistant", "hi there")
    assert first is not None and second is not None

    messages = await repo.list_messages(two_users.first, chat.chat_id)
    assert [m.content for m in messages] == ["hello", "hi there"]
    assert [m.message_id for m in messages] == sorted(m.message_id for m in messages)

    tail = await repo.list_messages(two_users.first, chat.chat_id, after_id=first.message_id)
    assert [m.content for m in tail] == ["hi there"]
    assert await repo.list_messages(two_users.second, chat.chat_id) == []
    assert await repo.add_message(two_users.second, chat.chat_id, "user", "intruder") is None


@pytest.mark.asyncio
async def test_result_members_keep_stable_ordinals(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Results")
    members = [
        {"entity_type": "wallet", "entity_key": f"0x{i:040d}", "payload": {"rank": i}}
        for i in range(3)
    ]
    saved = await repo.save_result_set(
        two_users.first, chat.chat_id, "wallet_set", "Top wallets",
        {"tool": "find_wallets"}, members, summary={"evidence_floor": 20},
    )
    assert saved is not None and saved.row_count == 3

    page = await repo.page_result_members(two_users.first, saved.result_set_id)
    assert page is not None
    assert [m["ordinal"] for m in page] == [0, 1, 2]
    assert [m["entity_key"] for m in page] == [m["entity_key"] for m in members]

    summaries = await repo.list_result_summaries(two_users.first, chat.chat_id)
    assert len(summaries) == 1 and summaries[0].row_count == 3
    assert await repo.page_result_members(two_users.second, saved.result_set_id) is None
    assert await repo.list_result_summaries(two_users.second, chat.chat_id) == []


@pytest.mark.asyncio
async def test_panel_upsert_reuses_chat_panel_key(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Panels")
    layout = {"col_span": 12, "min_height": 420, "order": 0}

    first = await repo.upsert_panel(
        two_users.first, chat.chat_id, "wallets:abc123", "wallet_table",
        "Wallets", None, layout, {"scope": "T20"},
    )
    second = await repo.upsert_panel(
        two_users.first, chat.chat_id, "wallets:abc123", "wallet_table",
        "Wallets v2", None, layout, {"scope": "T20"},
    )
    assert first is not None and second is not None
    assert first.panel_id == second.panel_id
    assert second.title == "Wallets v2"

    panels = await repo.list_panels(two_users.first, chat.chat_id)
    assert len(panels) == 1
    assert await repo.list_panels(two_users.second, chat.chat_id) == []

    minimized = await repo.update_panel_state(two_users.first, first.panel_id, "minimized")
    assert minimized is not None and minimized.state.value == "minimized"
    assert await repo.update_panel_state(two_users.second, first.panel_id, "closed") is None


@pytest.mark.asyncio
async def test_runs_are_owner_scoped(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Runs")
    run = await repo.create_run(two_users.first, chat.chat_id, "find wallets")
    assert run is not None and run.status.value == "queued"
    assert await repo.create_run(two_users.second, chat.chat_id, "hijack") is None

    running = await repo.set_run_status(two_users.first, run.run_id, "running")
    assert running is not None and running.status.value == "running"
    assert await repo.set_run_status(two_users.second, run.run_id, "cancelled") is None
