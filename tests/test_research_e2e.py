"""End-to-end conversational analysis workflows with a scripted model."""

import uuid

import pytest
import pytest_asyncio

from src.research.analytics import ResearchAnalytics
from src.research.context import WALLET_KINDS
from src.research.llm import FakeLLMProvider, ModelAction
from src.research.orchestrator import ResearchOrchestrator
from src.research.repository import ResearchRepository


def _wallet(i: int) -> str:
    return f"0x{'c'*34}{i:04d}"


class SpyAnalytics(ResearchAnalytics):
    def __init__(self, pool):
        super().__init__(pool)
        self.seen: list[tuple[str, object]] = []

    async def find_wallets(self, args):
        self.seen.append(("find_wallets", args))
        return await super().find_wallets(args)

    async def markets_traded(self, owner_id, args):
        self.seen.append(("markets_traded", args))
        return await super().markets_traded(owner_id, args)

    async def open_position_overlap(self, owner_id, args):
        self.seen.append(("open_position_overlap", args))
        return await super().open_position_overlap(owner_id, args)

    async def outcome_consensus(self, owner_id, args):
        self.seen.append(("outcome_consensus", args))
        return await super().outcome_consensus(owner_id, args)

    async def market_participants(self, args):
        self.seen.append(("market_participants", args))
        return await super().market_participants(args)


@pytest_asyncio.fixture
async def e2e_owner(test_pool):
    email = f"research-e2e-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    yield owner_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


@pytest_asyncio.fixture
async def e2e_seed(test_pool):
    """Three high-win-rate T20 wallets sharing one market (2 YES / 1 NO)."""
    wallets = [_wallet(21), _wallet(22), _wallet(23)]
    market = f"research-e2e-{uuid.uuid4().hex[:8]}"
    async with test_pool.acquire() as conn:
        for addr in wallets:
            await conn.execute(
                "INSERT INTO wallets_v2 (address, username) VALUES ($1, $2)"
                " ON CONFLICT (address) DO NOTHING", addr, f"e2e-{addr[-4:]}")
            await conn.execute(
                """INSERT INTO wallet_metrics_v2 (address, win_rate, resolved_count, winning_count)
                   VALUES ($1, 85, 40, 34)
                   ON CONFLICT (address) DO UPDATE SET win_rate = 85,
                     resolved_count = 40, winning_count = 34""", addr)
            await conn.execute(
                """INSERT INTO category_stats_v2
                       (address, category, subcategory, league, window_size, pnl, volume,
                        win_rate, roi_pct, resolved_count, winning_count)
                   VALUES ($1, 'Sports', 'Cricket', 'T20', 0, 1500, 7000, 82, 22, 40, 33)
                   ON CONFLICT (address, category, subcategory, league, window_size)
                   DO UPDATE SET win_rate = 82, resolved_count = 40, winning_count = 33""",
                addr)
        await conn.execute(
            "INSERT INTO markets_v2 (condition_id, title, category, subcategory, league)"
            " VALUES ($1, 'E2E Final', 'Sports', 'Cricket', 'T20')"
            " ON CONFLICT (condition_id) DO NOTHING", market)
        for addr, outcome in ((wallets[0], "YES"), (wallets[1], "YES"), (wallets[2], "NO")):
            await conn.execute(
                """INSERT INTO wallet_positions_v2
                       (address, condition_id, outcome, size, avg_price, current_value)
                   VALUES ($1, $2, $3, 10, 0.5, 100)
                   ON CONFLICT (address, condition_id, outcome)
                   DO UPDATE SET size = 10, current_value = 100""",
                addr, market, outcome)
    yield {"wallets": wallets, "market": market}
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM wallet_positions_v2 WHERE condition_id = $1", market)
        await conn.execute("DELETE FROM markets_v2 WHERE condition_id = $1", market)
        await conn.execute(
            "DELETE FROM category_stats_v2 WHERE address = ANY($1)", wallets)
        await conn.execute("DELETE FROM wallet_metrics_v2 WHERE address = ANY($1)", wallets)
        await conn.execute("DELETE FROM wallets_v2 WHERE address = ANY($1)", wallets)


async def _run(orch, owner_id, chat_id, prompt):
    return [e async for e in orch.run_stream(
        owner_id=owner_id, chat_id=chat_id, prompt=prompt)]


@pytest.mark.asyncio
async def test_wallet_to_consensus_chain(test_pool, e2e_owner, e2e_seed):
    repo = ResearchRepository(test_pool)
    analytics = SpyAnalytics(test_pool)
    chat = await repo.create_chat(e2e_owner, "E2E chain")
    wallet_set_id: list[str] = []

    run1 = ResearchOrchestrator(repo, analytics, FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="find_wallets", arguments={
            "category": "Sports", "subcategory": "Cricket", "league": "T20",
            "min_win_rate": 70, "comparison": "gt", "min_resolved_count": 20, "limit": 100}),
        ModelAction(kind="tool_call", tool_name="markets_traded", arguments={}),
        ModelAction(kind="answer", text="Three wallets trade these markets."),
    ]))
    events1 = await _run(run1, e2e_owner, chat.chat_id,
                         "Find wallets with more than 70% win rate in Sports, Cricket, T20.")
    assert events1[-1].type == "run.completed"
    wallet_set_id.append(next(
        e.data["result_set_id"] for e in events1 if e.type == "result.created"))
    market_label = next(
        e.data["label"] for e in events1
        if e.type == "result.created" and e.data["kind"] == "market_set")

    run2 = ResearchOrchestrator(repo, analytics, FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="open_position_overlap",
                    arguments={"min_wallet_count": 3}),
        ModelAction(kind="tool_call", tool_name="outcome_consensus", arguments={}),
        ModelAction(kind="answer", text="Two are on YES and one is on NO."),
    ]))
    events2 = await _run(run2, e2e_owner, chat.chat_id,
                         "Show markets where all of them have an open position. "
                         f"How many are on YES and how many are on NO in {market_label}?")
    assert events2[-1].type == "run.completed"

    # Every follow-up tool received the prior owned wallet result-set ID.
    wallet_refs = [
        str(a.wallet_result_set_id) for name, a in analytics.seen
        if name in ("markets_traded", "open_position_overlap", "outcome_consensus")
    ]
    assert wallet_refs and all(ref == wallet_set_id[0] for ref in wallet_refs)

    messages = await repo.list_messages(e2e_owner, chat.chat_id)
    assert [(m.role) for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0].content.startswith("Find wallets with more than 70%")

    summaries = await repo.list_result_summaries(e2e_owner, chat.chat_id)
    assert {s.kind for s in summaries} == {
        "wallet_set", "market_set", "position_overlap", "outcome_consensus"}

    overlap = next(s for s in summaries if s.kind == "position_overlap")
    members = await repo.page_result_members(e2e_owner, overlap.result_set_id)
    market_row = next(m for m in members if m["entity_key"] == e2e_seed["market"])
    assert market_row["payload"]["wallet_count"] == 3
    assert market_row["payload"]["coverage_pct"] == 100.0

    consensus = next(s for s in summaries if s.kind == "outcome_consensus")
    consensus_members = await repo.page_result_members(e2e_owner, consensus.result_set_id)
    by_outcome = {m["payload"]["outcome"]: m["payload"] for m in consensus_members}
    assert by_outcome["YES"]["wallet_count"] == 2
    assert by_outcome["NO"]["wallet_count"] == 1

    # A same-scope consensus refinement updates the panel instead of duplicating it.
    panels_before = await repo.list_panels(e2e_owner, chat.chat_id)
    run3 = ResearchOrchestrator(repo, analytics, FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="outcome_consensus", arguments={}),
        ModelAction(kind="answer", text="Still two YES, one NO."),
    ]))
    events3 = await _run(run3, e2e_owner, chat.chat_id,
                         f"Refresh the YES versus NO summary for those wallets in {market_label}.")
    assert events3[-1].type == "run.completed"
    panels_after = await repo.list_panels(e2e_owner, chat.chat_id)
    assert len(panels_after) == len(panels_before)
    consensus_panels = [p for p in panels_after if p.panel_type == "consensus"]
    assert len(consensus_panels) == 1


@pytest.mark.asyncio
async def test_market_first_workflow_uses_scoped_statistics(test_pool, e2e_owner, e2e_seed):
    """market_participants ranks by category scope, not global win rate."""
    market, wallets = e2e_seed["market"], e2e_seed["wallets"]
    # Make globals disagree with the category scope: global 50% must not qualify.
    async with test_pool.acquire() as conn:
        await conn.execute(
            "UPDATE wallet_metrics_v2 SET win_rate = 50 WHERE address = ANY($1)", wallets)
    repo = ResearchRepository(test_pool)
    analytics = SpyAnalytics(test_pool)
    chat = await repo.create_chat(e2e_owner, "Market first")
    orch = ResearchOrchestrator(repo, analytics, FakeLLMProvider([
        ModelAction(kind="tool_call", tool_name="market_participants", arguments={
            "condition_id": market, "min_win_rate": 70, "min_resolved_count": 20,
            "scope": {"category": "Sports", "subcategory": "Cricket",
                      "league": "T20", "window_size": 0}}),
        ModelAction(kind="tool_call", tool_name="outcome_consensus",
                    arguments={"condition_id": market}),
        ModelAction(kind="answer", text="Ranked by Cricket win rate with outcome summary."),
    ]))
    events = await _run(
        orch, e2e_owner, chat.chat_id,
        f"For condition {market}, find wallets with more than 70% Cricket win rate, "
        "sort by win rate, and summarize their current outcomes.")
    assert events[-1].type == "run.completed"
    kinds = [e.data["kind"] for e in events if e.type == "result.created"]
    assert kinds == ["market_participants", "outcome_consensus"]
    summaries = await repo.list_result_summaries(e2e_owner, chat.chat_id)
    participants = next(s for s in summaries if s.kind == "market_participants")
    members = await repo.page_result_members(e2e_owner, participants.result_set_id)
    assert {m["entity_key"] for m in members} == set(wallets)
    panels = await repo.list_panels(e2e_owner, chat.chat_id)
    assert {p.panel_type for p in panels} == {"wallet_table", "consensus"}
    assert WALLET_KINDS  # reference-resolution kinds cover wallet-bearing results
