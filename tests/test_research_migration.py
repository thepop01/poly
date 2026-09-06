from pathlib import Path

import pytest


MIGRATION_SOURCE = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "a0b1c2d3e4f5_add_research_workspaces.py"
).read_text()


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


@pytest.mark.asyncio
async def test_workspace_schema_and_panel_ownership_exist(test_pool):
    async with test_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT to_regclass($1)", "public.research_workspaces"
        )
        assert await conn.fetchval(
            "SELECT to_regclass($1)", "public.research_workspace_tabs"
        )
        assert await conn.fetchval(
            "SELECT to_regclass($1)", "public.idx_research_workspaces_owner_updated"
        )
        assert await conn.fetchval(
            "SELECT to_regclass($1)", "public.idx_research_panels_workspace"
        )
        columns = await conn.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'research_panels'"""
        )
        names = {row["column_name"] for row in columns}
        assert {"workspace_id", "source_chat_id"} <= names
        assert "chat_id" not in names

        chat_workspace = await conn.fetchval(
            """SELECT COUNT(*) = COUNT(workspace_id)
               FROM research_chats"""
        )
        assert chat_workspace
        panel_workspace = await conn.fetchval(
            """SELECT COUNT(*) = COUNT(workspace_id)
               FROM research_panels"""
        )
        assert panel_workspace


@pytest.mark.asyncio
async def test_workspace_tabs_use_fixed_allow_list_and_are_complete(test_pool):
    async with test_pool.acquire() as conn:
        constraint = await conn.fetchval(
            """SELECT pg_get_constraintdef(c.oid)
               FROM pg_constraint c
               JOIN pg_class t ON t.oid = c.conrelid
               JOIN pg_namespace n ON n.oid = t.relnamespace
               WHERE n.nspname = 'public'
                 AND t.relname = 'research_workspace_tabs'
                 AND c.contype = 'c'
                 AND pg_get_constraintdef(c.oid) LIKE '%wallet_groups%'"""
        )
        assert constraint is not None
        assert "wallet_groups" in constraint
        assert "market_groups" in constraint
        assert "agents" in constraint

        rows = await conn.fetch(
            """SELECT w.workspace_id,
                       COUNT(t.workspace_tab_id) AS tab_count,
                       COUNT(DISTINCT t.tab_type) AS distinct_tab_count,
                       array_agg(t.tab_type ORDER BY t.tab_type)
                           FILTER (WHERE t.tab_type IS NOT NULL) AS tab_types
               FROM research_workspaces w
               LEFT JOIN research_workspace_tabs t ON t.workspace_id = w.workspace_id
               GROUP BY w.workspace_id"""
        )
        expected = ["agents", "market_groups", "wallet_groups"]
        for row in rows:
            assert row["tab_count"] == 3
            assert row["distinct_tab_count"] == 3
            assert row["tab_types"] == expected


def test_workspace_backfill_does_not_reassign_or_skip_workspaces():
    assert "WHERE c.workspace_id IS NULL" in MIGRATION_SOURCE
    assert "WHERE workspace_id IS DISTINCT FROM" not in MIGRATION_SOURCE
    assert "FROM research_workspaces w\nCROSS JOIN" in MIGRATION_SOURCE
    assert "every workspace must have all three fixed tabs" in MIGRATION_SOURCE


def test_same_name_constraint_definition_drift_is_rejected():
    assert "actual_definition <>" in MIGRATION_SOURCE
    assert "unexpected definition" in MIGRATION_SOURCE
    assert "ON DELETE SET NULL" in MIGRATION_SOURCE


@pytest.mark.asyncio
async def test_legacy_chat_backfill_preserves_panel_provenance(test_pool):
    async with test_pool.acquire() as conn:
        chat_rows = await conn.fetch(
            """SELECT chat_id, workspace_id,
                       md5('research-workspace:' || chat_id::text)::uuid AS expected_workspace
               FROM research_chats"""
        )
        for row in chat_rows:
            assert row["workspace_id"] == row["expected_workspace"]

        orphaned_panels = await conn.fetchval(
            """SELECT COUNT(*)
               FROM research_panels p
               LEFT JOIN research_chats c ON c.chat_id = p.source_chat_id
               WHERE p.source_chat_id IS NOT NULL
                 AND (c.chat_id IS NULL OR p.workspace_id <> c.workspace_id)"""
        )
        assert orphaned_panels == 0

        panel_fkey = await conn.fetchval(
            """SELECT pg_get_constraintdef(c.oid)
               FROM pg_constraint c
               WHERE c.conrelid = 'research_panels'::regclass
                 AND c.conname = 'research_panels_source_chat_id_fkey'"""
        )
        assert panel_fkey == (
            "FOREIGN KEY (source_chat_id) REFERENCES research_chats(chat_id) ON DELETE SET NULL"
        )
        workspace_unique = await conn.fetchval(
            """SELECT pg_get_constraintdef(c.oid)
               FROM pg_constraint c
               WHERE c.conrelid = 'research_panels'::regclass
                 AND c.conname = 'research_panels_workspace_panel_key_key'"""
        )
        assert workspace_unique == "UNIQUE (workspace_id, panel_key)"
