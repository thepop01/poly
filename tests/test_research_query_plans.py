"""Query-plan guardrails for the cross-wallet analytical engine.

For a representative 100-wallet result set, the open-overlap and historical
same-outcome queries must stay set-based: the wallet collection is resolved
once through ``research_result_members`` and joined to position tables, never
evaluated as one subplan per wallet, and position access must be
index-assisted rather than sequential.
"""

import uuid

import pytest
import pytest_asyncio

from src.research.analytics import ResearchAnalytics, ResultSetAccessError
from src.research.repository import ResearchRepository


def _iter_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _iter_nodes(child)


def _plan_text(plan) -> str:
    return str(plan)


@pytest_asyncio.fixture
async def hundred_wallet_set(test_pool):
    email = f"research-plans-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(owner_id, "Plan guard")
    addresses = [f"0x{'b'*34}{i:04d}" for i in range(100)]
    saved = await repo.save_result_set(
        owner_id, chat.chat_id, "wallet_set", "100 wallets",
        {"tool": "find_wallets"},
        [{"entity_type": "wallet", "entity_key": a, "payload": {}} for a in addresses],
    )
    yield owner_id, saved.result_set_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


@pytest.mark.asyncio
async def test_overlap_plan_is_set_based_and_indexed(test_pool, hundred_wallet_set):
    owner_id, result_set_id = hundred_wallet_set
    plan = await ResearchAnalytics(test_pool).explain_query(
        owner_id, result_set_id, "open_overlap")
    text = _plan_text(plan)
    assert "CTE input" in text
    non_cte_subplans = [
        n.get("Subplan Name") for n in _iter_nodes(plan[0]["Plan"])
        if n.get("Subplan Name") and not str(n["Subplan Name"]).startswith("CTE ")
    ]
    assert non_cte_subplans == []
    nodes = list(_iter_nodes(plan[0]["Plan"]))
    position_scans = [n for n in nodes if n.get("Relation Name") == "wallet_positions_v2"]
    assert position_scans
    assert all(n["Node Type"] != "Seq Scan" for n in position_scans)
    assert any("Index" in n["Node Type"] for n in nodes)


@pytest.mark.asyncio
async def test_history_plan_is_set_based_and_indexed(test_pool, hundred_wallet_set):
    owner_id, result_set_id = hundred_wallet_set
    plan = await ResearchAnalytics(test_pool).explain_query(
        owner_id, result_set_id, "same_outcome_history")
    text = _plan_text(plan)
    assert "CTE input" in text
    non_cte_subplans = [
        n.get("Subplan Name") for n in _iter_nodes(plan[0]["Plan"])
        if n.get("Subplan Name") and not str(n["Subplan Name"]).startswith("CTE ")
    ]
    assert non_cte_subplans == []
    nodes = list(_iter_nodes(plan[0]["Plan"]))
    closed_scans = [n for n in nodes if n.get("Relation Name") == "wallet_closed_positions_v2"]
    assert closed_scans
    assert all(n["Node Type"] != "Seq Scan" for n in closed_scans)


@pytest.mark.asyncio
async def test_explain_rejects_foreign_result_sets(test_pool, hundred_wallet_set):
    _, result_set_id = hundred_wallet_set
    with pytest.raises(ResultSetAccessError):
        await ResearchAnalytics(test_pool).explain_query(
            str(uuid.uuid4()), result_set_id, "open_overlap")
