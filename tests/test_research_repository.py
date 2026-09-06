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
    await repo.add_message(two_users.first, chat.chat_id, "user", "keep this chat")

    archived = await repo.archive_chat(two_users.first, chat.chat_id, True)
    assert archived is not None and archived.is_archived is True
    assert await repo.list_chats(two_users.first) == []
    reopened = await repo.list_chats(two_users.first, include_archived=True)
    assert [c.chat_id for c in reopened] == [chat.chat_id]


@pytest.mark.asyncio
async def test_archiving_empty_chat_deletes_it_and_archived_list_excludes_empty(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    empty = await repo.create_chat(two_users.first, "Empty")
    assert await repo.archive_chat(two_users.first, empty.chat_id, True) is None
    assert await repo.get_chat(two_users.first, empty.chat_id) is None

    with_message = await repo.create_chat(two_users.first, "With message")
    await repo.add_message(two_users.first, with_message.chat_id, "user", "hello")
    archived = await repo.archive_chat(two_users.first, with_message.chat_id, True)
    assert archived is not None and archived.is_archived

    unarchived_empty = await repo.create_chat(two_users.first, "Unarchived empty")
    listed = await repo.list_chats(two_users.first, include_archived=True)
    listed_ids = [chat.chat_id for chat in listed]
    assert with_message.chat_id in listed_ids
    assert unarchived_empty.chat_id in listed_ids
    assert empty.chat_id not in listed_ids


@pytest.mark.asyncio
async def test_concurrent_default_chats_share_one_workspace(test_pool, two_users):
    import asyncio

    repo = ResearchRepository(test_pool)
    chats = await asyncio.gather(
        repo.create_chat(two_users.first, "First"),
        repo.create_chat(two_users.first, "Second"),
    )
    assert chats[0].workspace_id == chats[1].workspace_id
    workspaces = await repo.list_workspaces(two_users.first)
    assert len(workspaces) == 1


@pytest.mark.asyncio
async def test_panel_result_set_must_belong_to_workspace_owner(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    first_workspace = await repo.create_workspace(two_users.first, "First")
    second_workspace = await repo.create_workspace(two_users.second, "Second")
    first_chat = await repo.create_chat(two_users.first, "First chat", first_workspace.workspace_id)
    second_chat = await repo.create_chat(two_users.second, "Second chat", second_workspace.workspace_id)
    result = await repo.save_result_set(
        two_users.second, second_chat.chat_id, "wallet_set", "Other", {}, [],
    )
    assert result is not None
    panel = await repo.upsert_panel(
        two_users.first, first_workspace.workspace_id, first_chat.chat_id, "foreign-result",
        "wallet_table", "Foreign", result.result_set_id,
        {"col_span": 12, "min_height": 420, "order": 0},
    )
    assert panel is None


@pytest.mark.asyncio
async def test_uuid_shaped_legacy_panel_key_is_preserved(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "UUID panel key")
    panel_key = str(uuid.uuid4())
    panel = await repo.upsert_panel(
        two_users.first, chat.chat_id, panel_key, "wallet_table", "Wallets", None,
        {"col_span": 12, "min_height": 420, "order": 0},
    )
    assert panel is not None
    assert panel.panel_key == panel_key
    assert panel.source_chat_id == chat.chat_id


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


def test_panel_contracts():
    from pydantic import ValidationError
    from src.research.contracts import FloatingRect, PanelLayout, PanelMutation, PanelState

    # Accept state-only mutation
    m1 = PanelMutation(state=PanelState.NORMAL)
    assert m1.state == PanelState.NORMAL
    assert m1.floating is None
    assert m1.bring_to_front is None

    # Accept valid floating + bring_to_front mutation
    m2 = PanelMutation(
        floating=FloatingRect(x=0, y=12, width=500, height=320),
        bring_to_front=True,
    )
    assert m2.floating.x == 0
    assert m2.floating.y == 12
    assert m2.floating.width == 500
    assert m2.floating.height == 320
    assert m2.bring_to_front is True

    # Reject empty mutation
    with pytest.raises(ValidationError):
        PanelMutation.model_validate({})

    # Reject unknown fields (extra="forbid")
    with pytest.raises(ValidationError):
        PanelMutation.model_validate({"unknown": 123, "state": "normal"})

    # Reject negative coordinates
    with pytest.raises(ValidationError):
        FloatingRect(x=-1, y=0, width=500, height=320)
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=-5, width=500, height=320)

    # Reject non-finite/fractional coordinates (strict integers)
    with pytest.raises(ValidationError):
        FloatingRect.model_validate({"x": 10.5, "y": 0, "width": 500, "height": 320})

    # Reject width below 320 or height below 240
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=0, width=319, height=320)
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=0, width=400, height=239)

    # Reject dimensions above 4096
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=0, width=4097, height=320)
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=0, width=500, height=4097)

    # Reject y + height > 100000
    with pytest.raises(ValidationError):
        FloatingRect(x=0, y=99800, width=500, height=300)

    # Old layout JSON without floating fields still parses
    old_layout = PanelLayout.model_validate({"col_span": 6, "min_height": 380, "order": 1})
    assert old_layout.floating is None
    assert old_layout.z_index == 0


@pytest.mark.asyncio
async def test_panel_geometry_persists_and_survives_analytical_upsert(test_pool, two_users):
    from src.research.contracts import FloatingRect, PanelMutation

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Geometry Chat")
    default_layout = {"col_span": 12, "min_height": 420, "order": 0}

    panel = await repo.upsert_panel(
        two_users.first, chat.chat_id, "wallets:geometry", "wallet_table",
        "Wallets", None, default_layout, {"scope": "Sports"},
    )
    assert panel is not None

    # Apply floating geometry and bring_to_front
    updated = await repo.update_panel(
        two_users.first,
        panel.panel_id,
        PanelMutation(
            floating=FloatingRect(x=100, y=150, width=640, height=480),
            bring_to_front=True,
        ),
    )
    assert updated is not None
    assert updated.layout.floating is not None
    assert updated.layout.floating.x == 100
    assert updated.layout.floating.y == 150
    assert updated.layout.floating.width == 640
    assert updated.layout.floating.height == 480
    assert updated.layout.z_index == 1

    # Analytical upsert happens with same panel_key, new result_set_id and title
    rs = await repo.save_result_set(
        two_users.first, chat.chat_id, "wallet_set", "Top wallets",
        {"tool": "find_wallets"}, [{"entity_type": "wallet", "entity_key": "0x123", "payload": {}}],
    )
    assert rs is not None
    new_result_id = rs.result_set_id
    upserted = await repo.upsert_panel(
        two_users.first, chat.chat_id, "wallets:geometry", "wallet_table",
        "Wallets Updated Results", new_result_id, default_layout, {"scope": "Updated Scope"},
    )
    assert upserted is not None
    assert upserted.panel_id == panel.panel_id
    assert upserted.title == "Wallets Updated Results"
    assert upserted.result_set_id == new_result_id
    assert upserted.config["scope"] == "Updated Scope"
    # CRITICAL: user floating geometry and z_index MUST survive analytical upsert!
    assert upserted.layout.floating is not None
    assert upserted.layout.floating.x == 100
    assert upserted.layout.floating.y == 150
    assert upserted.layout.floating.width == 640
    assert upserted.layout.floating.height == 480
    assert upserted.layout.z_index == 1

    # State-only update preserves geometry
    minimized = await repo.update_panel(
        two_users.first, panel.panel_id, PanelMutation(state="minimized")
    )
    assert minimized is not None
    assert minimized.state.value == "minimized"
    assert minimized.layout.floating.x == 100

    # Geometry-only update preserves state
    moved = await repo.update_panel(
        two_users.first,
        panel.panel_id,
        PanelMutation(floating=FloatingRect(x=120, y=180, width=600, height=450)),
    )
    assert moved is not None
    assert moved.state.value == "minimized"
    assert moved.layout.floating.x == 120
    assert moved.layout.floating.y == 180

    # Foreign user cannot update panel
    assert await repo.update_panel(
        two_users.second, panel.panel_id, PanelMutation(state="closed")
    ) is None


@pytest.mark.asyncio
async def test_panel_bring_to_front_stacking_and_compaction(test_pool, two_users):
    from src.research.contracts import PanelMutation

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Stacking Chat")
    default_layout = {"col_span": 12, "min_height": 420, "order": 0}

    panel_a = await repo.upsert_panel(
        two_users.first, chat.chat_id, "panel:a", "wallet_table", "A", None, default_layout
    )
    panel_b = await repo.upsert_panel(
        two_users.first, chat.chat_id, "panel:b", "wallet_table", "B", None, default_layout
    )
    assert panel_a is not None and panel_b is not None

    # Raise A -> rank 1
    up_a = await repo.update_panel(two_users.first, panel_a.panel_id, PanelMutation(bring_to_front=True))
    assert up_a is not None and up_a.layout.z_index == 1

    # Raise B -> rank 2
    up_b = await repo.update_panel(two_users.first, panel_b.panel_id, PanelMutation(bring_to_front=True))
    assert up_b is not None and up_b.layout.z_index == 2

    # Raise A again -> rank 3
    up_a2 = await repo.update_panel(two_users.first, panel_a.panel_id, PanelMutation(bring_to_front=True))
    assert up_a2 is not None and up_a2.layout.z_index == 3

    # Test compaction when max rank >= 1,000,000
    async with test_pool.acquire() as conn:
        await conn.execute(
            """UPDATE research_panels
               SET layout = jsonb_set(layout, '{z_index}', '1000000'::jsonb)
               WHERE panel_id = $1""",
            panel_a.panel_id,
        )
    # Now raising B should compact chat panels in order and assign next rank
    up_b2 = await repo.update_panel(two_users.first, panel_b.panel_id, PanelMutation(bring_to_front=True))
    assert up_b2 is not None
    # Prior to raising B, B had rank 2 and A had 1000000.
    # Compaction ordered by z_index ASC: B gets 1, A gets 2.
    # Then B is raised to max_rank + 1 = 3!
    assert up_b2.layout.z_index == 3
    panel_a_fresh = (await repo.list_panels(two_users.first, chat.chat_id))[0]
    # A was compacted down from 1000000 to 2
    assert panel_a_fresh.layout.z_index == 2


@pytest.mark.asyncio
async def test_workspace_creation_seeds_exactly_three_tabs(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    workspace = await repo.create_workspace(two_users.first, "Cricket")
    tabs = await repo.list_workspace_tabs(two_users.first, workspace.workspace_id)
    assert tabs is not None
    assert [tab.tab_type.value for tab in tabs] == ["wallet_groups", "market_groups", "agents"]
    assert len(tabs) == 3
    assert await repo.list_workspace_tabs(two_users.second, workspace.workspace_id) is None


@pytest.mark.asyncio
async def test_workspace_panel_upsert_is_shared_across_chats_and_preserves_geometry(test_pool, two_users):
    from src.research.contracts import FloatingRect, PanelMutation

    repo = ResearchRepository(test_pool)
    workspace = await repo.create_workspace(two_users.first, "Shared canvas")
    first_chat = await repo.create_chat(two_users.first, "First", workspace.workspace_id)
    second_chat = await repo.create_chat(two_users.first, "Second", workspace.workspace_id)
    layout = {"col_span": 12, "min_height": 420, "order": 0}
    first = await repo.upsert_panel(
        two_users.first, workspace.workspace_id, first_chat.chat_id, "same", "wallet_table",
        "First", None, layout,
    )
    assert first is not None
    moved = await repo.update_panel(
        two_users.first, first.panel_id,
        PanelMutation(floating=FloatingRect(x=10, y=20, width=500, height=320), bring_to_front=True),
    )
    assert moved is not None
    second = await repo.upsert_panel(
        two_users.first, workspace.workspace_id, second_chat.chat_id, "same", "wallet_table",
        "Second", None, layout,
    )
    assert second is not None
    assert second.panel_id == first.panel_id
    assert second.workspace_id == workspace.workspace_id
    assert second.source_chat_id == second_chat.chat_id
    assert second.layout.floating is not None
    assert second.layout.floating.x == 10
    assert second.layout.z_index == 1

    assert await repo.get_workspace(two_users.second, workspace.workspace_id) is None
    assert await repo.rename_workspace(two_users.second, workspace.workspace_id, "Nope") is None
    assert await repo.list_workspace_panels(two_users.second, workspace.workspace_id) is None
    assert await repo.update_panel(two_users.second, first.panel_id, PanelMutation(state="closed")) is None


@pytest.mark.asyncio
async def test_deleted_source_chat_keeps_workspace_panel(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    workspace = await repo.create_workspace(two_users.first, "Preserve")
    chat = await repo.create_chat(two_users.first, "Source", workspace.workspace_id)
    panel = await repo.upsert_panel(
        two_users.first, workspace.workspace_id, chat.chat_id, "orphan", "wallet_table",
        "Orphan", None, {"col_span": 12, "min_height": 420, "order": 0},
    )
    assert panel is not None
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM research_chats WHERE chat_id = $1", chat.chat_id)
    panels = await repo.list_workspace_panels(two_users.first, workspace.workspace_id)
    assert panels is not None and len(panels) == 1
    assert panels[0].source_chat_id is None
