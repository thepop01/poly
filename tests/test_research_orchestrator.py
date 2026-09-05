"""Provider adapter tests (no network) and orchestration loop tests."""

import asyncio
import uuid

import pytest
import pytest_asyncio

from src.research.analytics import ResearchAnalytics
from src.research.context import ResearchContext
from src.research.llm import (
    FakeLLMProvider,
    ModelAction,
    OpenAIResponsesProvider,
    ProviderResponseError,
    ProviderTimeoutError,
)
from src.research.orchestrator import ResearchOrchestrator, panel_key
from src.research.contracts import FindWalletsArgs
from src.research.repository import ResearchRepository


def _context() -> ResearchContext:
    return ResearchContext(messages=[{"role": "user", "content": "hi"}], result_refs=[])


def _tools() -> list:
    return [{"name": "find_wallets", "description": "d", "parameters": {"type": "object"}}]


@pytest.mark.asyncio
async def test_provider_returns_assistant_text():
    provider = FakeLLMProvider([ModelAction(kind="answer", text="hello there")])
    action = await provider.next_action(_context(), _tools())
    assert action.kind == "answer" and action.text == "hello there"


@pytest.mark.asyncio
async def test_provider_returns_function_call_with_json_arguments():
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"category": "Sports", "limit": 10}),
    ])
    action = await provider.next_action(_context(), _tools())
    assert action.kind == "tool_call"
    assert action.tool_name == "find_wallets"
    assert action.arguments == {"category": "Sports", "limit": 10}


class _TimeoutClient:
    class responses:
        @staticmethod
        async def create(**kwargs):
            raise TimeoutError("timed out")


@pytest.mark.asyncio
async def test_provider_timeout_is_mapped():
    provider = OpenAIResponsesProvider(model="test-model", client=_TimeoutClient())
    with pytest.raises(ProviderTimeoutError):
        await provider.next_action(_context(), _tools())


@pytest.mark.asyncio
async def test_malformed_tool_arguments_raise_provider_error():
    provider = OpenAIResponsesProvider(model="test-model", client=object())
    with pytest.raises(ProviderResponseError):
        provider.parse_response({
            "output": [{
                "type": "function_call", "name": "find_wallets",
                "arguments": "{not valid json",
            }],
        })


@pytest.mark.asyncio
async def test_adapter_parses_function_call_and_text_responses():
    provider = OpenAIResponsesProvider(model="test-model", client=object())
    call = provider.parse_response({
        "output": [{
            "type": "function_call", "name": "open_position_overlap",
            "arguments": '{"wallet_result_set_id": "123"}',
        }],
    })
    assert call.kind == "tool_call" and call.tool_name == "open_position_overlap"
    answer = provider.parse_response({
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "three wallets share this market."}],
        }],
    })
    assert answer.kind == "answer" and "three wallets" in answer.text


def test_missing_api_key_raises_config_error(monkeypatch):
    from src.research.llm import ProviderConfigError

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIResponsesProvider(model="test-model", client=None)
    with pytest.raises(ProviderConfigError) as exc_info:
        provider._client()
    assert exc_info.value.code == "PROVIDER_NOT_CONFIGURED"
    assert "OPENAI_API_KEY" in str(exc_info.value)


def test_adapter_forwards_base_url_to_compatible_gateway(monkeypatch):
    import sys
    import types

    seen: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    module = types.ModuleType("openai")
    module.AsyncOpenAI = FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = OpenAIResponsesProvider(model="m", base_url="https://gateway.example/v1")
    provider._client()
    assert seen["api_key"] == "test-key"
    assert seen["base_url"] == "https://gateway.example/v1"


def test_chat_completions_provider_parses_tool_call_and_answer():
    from src.research.llm import OpenAIChatCompletionsProvider

    provider = OpenAIChatCompletionsProvider(model="m", client=object())
    call = provider.parse_completion({
        "choices": [{"message": {
            "content": "",
            "tool_calls": [{"id": "call_1",
                            "function": {"name": "find_wallets",
                                         "arguments": '{"category": "Sports"}'}}],
        }}],
    })
    assert call.kind == "tool_call" and call.tool_name == "find_wallets"
    assert call.arguments == {"category": "Sports"}
    answer = provider.parse_completion({
        "choices": [{"message": {"content": "done.", "tool_calls": []}}],
    })
    assert answer.kind == "answer" and answer.text == "done."


def test_chat_completions_provider_skips_nameless_calls():
    from src.research.llm import OpenAIChatCompletionsProvider

    provider = OpenAIChatCompletionsProvider(model="m", client=object())
    with pytest.raises(ProviderResponseError):
        provider.parse_completion({
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "call_1",
                                "function": {"name": None, "arguments": "{}"}}],
            }}],
        })


def test_build_provider_from_env_selects_adapter(monkeypatch):
    from src.research.llm import (
        OpenAIChatCompletionsProvider,
        OpenAIResponsesProvider,
        build_provider_from_env,
    )

    monkeypatch.setenv("RESEARCH_PROVIDER", "chat-completions")
    monkeypatch.setenv("RESEARCH_MODEL", "x-model")
    provider = build_provider_from_env()
    assert isinstance(provider, OpenAIChatCompletionsProvider)
    assert provider.model == "x-model"
    monkeypatch.setenv("RESEARCH_PROVIDER", "responses")
    assert isinstance(build_provider_from_env(), OpenAIResponsesProvider)


@pytest.mark.asyncio
async def test_unconfigured_provider_yields_actionable_failure(test_pool, orch_owner):
    from src.research.llm import ProviderConfigError

    class UnconfiguredProvider:
        async def next_action(self, context, tools):
            raise ProviderConfigError("no LLM API key configured: set OPENAI_API_KEY")

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "No key")
    orch = ResearchOrchestrator(repo, StubAnalytics(), UnconfiguredProvider())
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed"
    assert terminal.data["error_code"] == "PROVIDER_NOT_CONFIGURED"
    assert "OPENAI_API_KEY" in terminal.data["error_message"]


# -- orchestration loop -------------------------------------------------

WALLET_ROWS = [
    {"address": f"0x{'f'*34}{i:04d}", "username": f"w{i}", "win_rate": 80.0,
     "pnl": 100.0, "volume": 500.0, "resolved_count": 40, "winning_count": 32,
     "balance": 1000.0, "position_value": 50.0, "last_trade_at": None,
     "scope": {"category": "Sports", "subcategory": None, "league": None, "window_size": 0}}
    for i in range(3)
]

MARKET_ROWS = [
    {"condition_id": "0xmarket1", "title": "M1", "category": "Sports",
     "subcategory": "Cricket", "league": "T20", "status": "ACTIVE",
     "wallet_count": 3, "open_wallets": 3, "closed_wallets": 0,
     "coverage_pct": 100.0, "outcomes": ["YES"], "total_value": 100.0},
]


class StubAnalytics:
    def __init__(self, wallets=None, markets=None, fail_with=None):
        self.calls: list = []
        self.wallets = wallets if wallets is not None else WALLET_ROWS
        self.markets = markets if markets is not None else MARKET_ROWS
        self.fail_with = fail_with

    async def find_wallets(self, args):
        self.calls.append(("find_wallets", args))
        if self.fail_with:
            raise self.fail_with
        return list(self.wallets)

    async def markets_traded(self, owner_id, args):
        self.calls.append(("markets_traded", args))
        return list(self.markets)

    async def open_position_overlap(self, owner_id, args):
        self.calls.append(("open_position_overlap", args))
        return []

    async def market_participants(self, args):
        self.calls.append(("market_participants", args))
        return []

    async def outcome_consensus(self, owner_id, args):
        self.calls.append(("outcome_consensus", args))
        return []

    async def same_outcome_history(self, owner_id, args):
        self.calls.append(("same_outcome_history", args))
        return []


class DisconnectedRequest:
    async def is_disconnected(self):
        return True


class SleepyProvider:
    def __init__(self):
        self.calls = 0

    async def next_action(self, context, tools):
        self.calls += 1
        await asyncio.sleep(5)
        return ModelAction(kind="answer", text="too late")


@pytest_asyncio.fixture
async def orch_owner(test_pool):
    email = f"research-orch-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    yield owner_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


def _terminal(events):
    terminals = [e for e in events if e.type in ("run.completed", "run.failed")]
    assert len(terminals) == 1
    return terminals[0]


@pytest.mark.asyncio
async def test_find_wallets_then_answer_streams_expected_events(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Loop")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"category": "Sports", "limit": 10}),
        ModelAction(kind="answer", text="Found three wallets. All above the floor."),
    ])
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    assert [e.type for e in events] == [
        "run.started", "tool.started", "result.created", "panel.upserted",
        "assistant.delta", "assistant.delta", "run.completed",
    ]
    assert _terminal(events).type == "run.completed"
    messages = await repo.list_messages(orch_owner, chat.chat_id)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "find wallets"), ("assistant", "Found three wallets. All above the floor.")]
    panels = await repo.list_panels(orch_owner, chat.chat_id)
    assert len(panels) == 1 and panels[0].panel_type == "wallet_table"


@pytest.mark.asyncio
async def test_follow_up_overlap_receives_saved_wallet_result_id(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    analytics = StubAnalytics()
    chat = await repo.create_chat(orch_owner, "Follow-up")
    first = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 5}),
        ModelAction(kind="answer", text="done."),
    ])
    orch = ResearchOrchestrator(repo, analytics, first)
    first_events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    saved_id = next(e for e in first_events if e.type == "result.created").data["result_set_id"]

    second = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="open_position_overlap", arguments={}),
        ModelAction(kind="answer", text="no shared markets."),
    ])
    orch2 = ResearchOrchestrator(repo, analytics, second)
    events2 = [e async for e in orch2.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id,
        prompt="show markets where all of those wallets hold a position")]
    assert _terminal(events2).type == "run.completed"
    overlap_calls = [c for c in analytics.calls if c[0] == "open_position_overlap"]
    assert overlap_calls
    # The follow-up resolved "those wallets" to the first run's saved wallet set.
    assert str(overlap_calls[0][1].wallet_result_set_id) == saved_id


@pytest.mark.asyncio
async def test_same_scope_updates_panel_new_tool_creates_panel(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Panels")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"category": "Sports", "limit": 10}),
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"category": "Sports", "limit": 50}),
        ModelAction(kind="answer", text="refined."),
    ])
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider, max_tool_calls=6)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    assert _terminal(events).type == "run.completed"
    panels = await repo.list_panels(orch_owner, chat.chat_id)
    assert len(panels) == 1  # same semantic scope reuses the panel
    assert panel_key("find_wallets", FindWalletsArgs(category="Sports", limit=10)) == \
        panel_key("find_wallets", FindWalletsArgs(category="Sports", limit=50))

    provider2 = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="markets_traded", arguments={}),
        ModelAction(kind="answer", text="markets listed."),
    ])
    orch2 = ResearchOrchestrator(repo, StubAnalytics(), provider2)
    events2 = [e async for e in orch2.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id,
        prompt="show markets those wallets traded")]
    assert _terminal(events2).type == "run.completed"
    assert len(await repo.list_panels(orch_owner, chat.chat_id)) == 2


@pytest.mark.asyncio
async def test_tool_call_ceiling_enforced(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Ceiling")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 5}),
    ] * 8)
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="go")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "MAX_TOOL_CALLS"


@pytest.mark.asyncio
async def test_run_timeout_yields_failed_event(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Timeout")
    orch = ResearchOrchestrator(repo, StubAnalytics(), SleepyProvider(), timeout_seconds=0.05)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="go")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_disconnect_cancels_run(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Cancel")
    provider = FakeLLMProvider([ModelAction(kind="answer", text="never")])
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="go",
        request=DisconnectedRequest())]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "CANCELLED"


@pytest.mark.asyncio
async def test_invalid_tool_yields_stable_failure(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Bad tool")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="run_sql", arguments={}),
    ])
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="go")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_tool_exception_hides_internal_details(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Tool boom")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={}),
    ])
    orch = ResearchOrchestrator(
        repo, StubAnalytics(fail_with=RuntimeError("secret db boom")), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="go")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "TOOL_ERROR"
    assert "boom" not in terminal.data["error_message"]


@pytest.mark.asyncio
async def test_real_analytics_orchestration_smoke(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Smoke")
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets",
                    arguments={"limit": 3}),
        ModelAction(kind="answer", text="Here are leading wallets."),
    ])
    orch = ResearchOrchestrator(repo, ResearchAnalytics(test_pool), provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    assert _terminal(events).type == "run.completed"
    assert any(e.type == "panel.upserted" for e in events)


@pytest.mark.asyncio
async def test_row_ceiling_rejects_oversized_output(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Row ceiling")
    big = [{**WALLET_ROWS[0], "address": f"0x{'d'*34}{i:04d}"} for i in range(1500)]
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 1000}),
    ])
    orch = ResearchOrchestrator(repo, StubAnalytics(wallets=big), provider, max_rows=1000)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    terminal = _terminal(events)
    assert terminal.type == "run.failed" and terminal.data["error_code"] == "ROW_LIMIT"


@pytest.mark.asyncio
async def test_observability_logs_ids_but_never_prompts(test_pool, orch_owner, caplog):
    import logging

    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Observable")
    secret_prompt = f"secret-prompt-{uuid.uuid4().hex}"
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 2}),
        ModelAction(kind="answer", text="done."),
    ])
    orch = ResearchOrchestrator(repo, StubAnalytics(), provider)
    with caplog.at_level(logging.INFO, logger="src.research.orchestrator"):
        events = [e async for e in orch.run_stream(
            owner_id=orch_owner, chat_id=chat.chat_id, prompt=secret_prompt)]
    assert _terminal(events).type == "run.completed"
    records = [r for r in caplog.records if r.name == "src.research.orchestrator"]
    assert records
    logged = " ".join(r.getMessage() for r in records)
    assert secret_prompt not in logged
    assert all(getattr(r, "owner_hash", None) for r in records)


@pytest.mark.asyncio
async def test_identical_repeat_call_is_short_circuited(test_pool, orch_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(orch_owner, "Duplicates")
    analytics = StubAnalytics()
    provider = FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 5}),
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={"limit": 5}),
        ModelAction(kind="answer", text="No wallets match that scope."),
    ])
    orch = ResearchOrchestrator(repo, analytics, provider)
    events = [e async for e in orch.run_stream(
        owner_id=orch_owner, chat_id=chat.chat_id, prompt="find wallets")]
    assert _terminal(events).type == "run.completed"
    assert [c for c in analytics.calls if c[0] == "find_wallets"].__len__() == 1
    assert [e.type for e in events].count("tool.started") == 1
    assert [e.type for e in events].count("result.created") == 1
