# tests/test_agent_migration.py
import pytest


@pytest.mark.asyncio
async def test_agent_tables_exist(test_pool):
    """Migration creates agents, agent_actions, agent_events, notifications."""
    async with test_pool.acquire() as conn:
        for table in ("agents", "agent_actions", "agent_events", "notifications"):
            exists = await conn.fetchval(
                "SELECT to_regclass($1)", f"public.{table}"
            )
            assert exists is not None, f"table {table} missing"


@pytest.mark.asyncio
async def test_agents_defaults(test_pool):
    """trading_armed defaults FALSE; is_active defaults FALSE."""
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (email, password_hash)
            VALUES ('agent_mig_test@example.com', 'h')
            ON CONFLICT (email) DO UPDATE SET password_hash = 'h'
            RETURNING user_id
        """)
        uid = row["user_id"]
        aid = await conn.fetchval("""
            INSERT INTO agents (owner_id, name, rule_tree)
            VALUES ($1, 'mig test', '{"op":"and","children":[]}'::jsonb)
            RETURNING agent_id
        """, uid)
        armed = await conn.fetchval("SELECT trading_armed FROM agents WHERE agent_id=$1", aid)
        active = await conn.fetchval("SELECT is_active FROM agents WHERE agent_id=$1", aid)
        assert armed is False
        assert active is False
        await conn.execute("DELETE FROM agents WHERE agent_id=$1", aid)
