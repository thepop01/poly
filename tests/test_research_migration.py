import pytest


@pytest.mark.asyncio
async def test_research_tables_and_indexes_exist(test_pool):
    tables = (
        "research_chats", "research_messages", "research_runs",
        "research_result_sets", "research_result_members", "research_panels",
    )
    indexes = (
        "idx_research_chats_owner_updated",
        "idx_research_messages_chat_created",
        "idx_research_members_entity",
        "idx_wallet_positions_market_wallet",
        "idx_closed_positions_market_wallet",
        "idx_category_stats_scope_winrate",
    )
    async with test_pool.acquire() as conn:
        for table in tables:
            assert await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
        for index in indexes:
            assert await conn.fetchval("SELECT to_regclass($1)", f"public.{index}")
