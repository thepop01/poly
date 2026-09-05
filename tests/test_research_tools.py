import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError
from src.research.contracts import FindWalletsArgs, PositionOverlapArgs
from src.research.repository import ResearchRepository
from src.research.tools import (
    TOOL_DEFINITIONS,
    ToolNotFoundError,
    ToolValidationError,
    execute_tool,
    get_tool,
    tool_schemas,
)


def test_find_wallets_defaults_are_safe_and_bounded():
    args = FindWalletsArgs(category="Sports", subcategory="Cricket", league="T20")
    assert args.min_win_rate == 70
    assert args.comparison == "gt"
    assert args.min_resolved_count == 20
    assert args.limit == 100


def test_tool_limits_reject_oversized_requests():
    with pytest.raises(ValidationError):
        FindWalletsArgs(category="Sports", limit=1001)


def test_overlap_requires_owned_wallet_result_reference():
    with pytest.raises(ValidationError):
        PositionOverlapArgs(wallet_result_set_id="not-a-uuid")


def test_registry_has_unique_names_models_kinds_and_handlers():
    names = [t.name for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names)) == 6
    for tool in TOOL_DEFINITIONS:
        assert issubclass(tool.args_model, __import__("pydantic").BaseModel)
        assert tool.result_kind.value
        assert tool.panel_type.value
        assert tool.handler_name
        assert get_tool(tool.name) is tool


def test_registry_schemas_state_defaults_and_definitions():
    schemas = {s["name"]: s for s in tool_schemas()}
    assert set(schemas) == {t.name for t in TOOL_DEFINITIONS}
    assert "min_resolved_count" in schemas["find_wallets"]["parameters"]["properties"]
    assert "strict" in schemas["find_wallets"]["description"]


@pytest.mark.asyncio
async def test_unknown_tool_fails_without_calling_analytics():
    class ExplodingAnalytics:
        def __getattr__(self, _name):
            raise AssertionError("analytics must not be called")

    with pytest.raises(ToolNotFoundError):
        await execute_tool(
            None, ExplodingAnalytics(), owner_id="x", chat_id=uuid.uuid4(),
            tool_name="run_sql", arguments={},
        )


@pytest.mark.asyncio
async def test_invalid_arguments_fail_without_calling_analytics():
    class ExplodingAnalytics:
        def __getattr__(self, _name):
            raise AssertionError("analytics must not be called")

    with pytest.raises(ToolValidationError):
        await execute_tool(
            None, ExplodingAnalytics(), owner_id="x", chat_id=uuid.uuid4(),
            tool_name="find_wallets", arguments={"limit": 5000},
        )


@pytest_asyncio.fixture
async def tool_owner(test_pool):
    email = f"research-tools-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    yield owner_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


@pytest.mark.asyncio
async def test_execute_tool_persists_wallet_result_set(test_pool, tool_owner):
    from src.research.analytics import ResearchAnalytics

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(tool_owner, "Tool dispatch")
    execution = await execute_tool(
        repo, ResearchAnalytics(test_pool), owner_id=tool_owner, chat_id=chat.chat_id,
        tool_name="find_wallets",
        arguments={"category": "Sports", "limit": 5},
    )
    assert execution.result_set.kind == "wallet_set"
    assert execution.panel_type.value == "wallet_table"
    assert execution.result_set.summary["evidence_floor"] == 20
    page = await repo.page_result_members(tool_owner, execution.result_set.result_set_id)
    assert page is not None and len(page) == execution.result_set.row_count


@pytest.mark.asyncio
async def test_empty_discovery_carries_scope_hint(test_pool, tool_owner):
    from src.research.analytics import ResearchAnalytics

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(tool_owner, "Empty hint")
    execution = await execute_tool(
        repo, ResearchAnalytics(test_pool), owner_id=tool_owner, chat_id=chat.chat_id,
        tool_name="find_wallets",
        arguments={"category": "SPORTS", "subcategory": "Cricket", "league": "T20-Nope",
                   "limit": 5},
    )
    assert execution.result_set.row_count == 0
    scopes = execution.result_set.summary.get("available_scopes", [])
    assert scopes
    assert any(s["subcategory"] == "Cricket" for s in scopes)
