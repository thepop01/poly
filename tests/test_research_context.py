import uuid

import pytest
import pytest_asyncio

from src.research.context import (
    build_context,
    resolve_market_set_id,
    resolve_wallet_set_id,
)
from src.research.repository import ResearchRepository


@pytest_asyncio.fixture
async def context_owner(test_pool):
    email = f"research-context-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    yield owner_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


async def _seed_chat(repo, owner_id, title="Ctx"):
    chat = await repo.create_chat(owner_id, title)
    first = await repo.save_result_set(
        owner_id, chat.chat_id, "wallet_set", "T20 wallets",
        {"tool": "find_wallets"},
        [{"entity_type": "wallet", "entity_key": "0xabc", "payload": {}}],
    )
    second = await repo.save_result_set(
        owner_id, chat.chat_id, "market_set", "T20 markets",
        {"tool": "markets_traded"},
        [{"entity_type": "market", "entity_key": "0xmarket", "payload": {}}],
    )
    await repo.add_message(owner_id, chat.chat_id, "user", "find wallets")
    await repo.add_message(owner_id, chat.chat_id, "assistant", "found some")
    return chat, first, second


@pytest.mark.asyncio
async def test_those_wallets_resolves_latest_wallet_set(test_pool, context_owner):
    repo = ResearchRepository(test_pool)
    chat, first, _ = await _seed_chat(repo, context_owner)
    ctx = await build_context(repo, context_owner, chat.chat_id)
    assert resolve_wallet_set_id("for those wallets show overlap", ctx.result_refs) == str(first.result_set_id)


@pytest.mark.asyncio
async def test_them_resolves_latest_wallet_set(test_pool, context_owner):
    repo = ResearchRepository(test_pool)
    chat, first, _ = await _seed_chat(repo, context_owner)
    ctx = await build_context(repo, context_owner, chat.chat_id)
    assert resolve_wallet_set_id("rank them by win rate", ctx.result_refs) == str(first.result_set_id)


@pytest.mark.asyncio
async def test_previous_markets_resolves_market_set(test_pool, context_owner):
    repo = ResearchRepository(test_pool)
    chat, _, second = await _seed_chat(repo, context_owner)
    ctx = await build_context(repo, context_owner, chat.chat_id)
    assert resolve_market_set_id("for the previous markets show consensus", ctx.result_refs) == str(
        second.result_set_id)


@pytest.mark.asyncio
async def test_explicit_label_beats_recency(test_pool, context_owner):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(context_owner, "Labels")
    older = await repo.save_result_set(
        context_owner, chat.chat_id, "wallet_set", "Cricket veterans",
        {"tool": "find_wallets"},
        [{"entity_type": "wallet", "entity_key": "0x1", "payload": {}}],
    )
    await repo.save_result_set(
        context_owner, chat.chat_id, "wallet_set", "T20 newcomers",
        {"tool": "find_wallets"},
        [{"entity_type": "wallet", "entity_key": "0x2", "payload": {}}],
    )
    ctx = await build_context(repo, context_owner, chat.chat_id)
    assert resolve_wallet_set_id("show overlap for Cricket veterans", ctx.result_refs) == str(
        older.result_set_id)


@pytest.mark.asyncio
async def test_other_chat_results_never_resolve(test_pool, context_owner):
    repo = ResearchRepository(test_pool)
    chat_a, first_a, _ = await _seed_chat(repo, context_owner, title="A")
    chat_b = await repo.create_chat(context_owner, "B")
    ctx_b = await build_context(repo, context_owner, chat_b.chat_id)
    assert ctx_b.result_refs == []
    assert resolve_wallet_set_id("those wallets", ctx_b.result_refs) is None
    ctx_a = await build_context(repo, context_owner, chat_a.chat_id)
    assert str(first_a.result_set_id) in {r["result_set_id"] for r in ctx_a.result_refs}
    assert {m["content"] for m in ctx_a.messages} == {"find wallets", "found some"}
