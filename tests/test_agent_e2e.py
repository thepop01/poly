import pytest
from src.workers.agent_evaluator import run_once


@pytest.mark.asyncio
async def test_active_agent_fires_and_notifies(test_pool):
    async with test_pool.acquire() as conn:
        uid = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ('e2e_agent@example.com','h') "
            "ON CONFLICT (email) DO UPDATE SET password_hash='h' RETURNING user_id")
        # seed an event + a cheap active order-book market
        await conn.execute(
            "INSERT INTO events (event_id, slug, title, status, created_at) "
            "VALUES ('e2e_ev','e2e','E2E Event','active',NOW()) ON CONFLICT (event_id) DO NOTHING")
        await conn.execute("""
            INSERT INTO markets (market_id, event_id, token_id, title, status,
                                 enable_order_book, current_price, total_volume, liquidity, created_at)
            VALUES ('e2e_m','e2e_ev','e2e_tok','E2E cheap market','active',TRUE,0.05,5000,50,NOW())
            ON CONFLICT (market_id) DO UPDATE SET current_price=0.05, status='active', enable_order_book=TRUE
        """)
        agent_id = await conn.fetchval("""
            INSERT INTO agents (owner_id, name, rule_tree, is_active)
            VALUES ($1,'e2e watcher','{"field":"current_price","cmp":"lt","value":0.15}'::jsonb, TRUE)
            RETURNING agent_id""", uid)
        await conn.execute(
            "INSERT INTO agent_actions (agent_id, action_type, params) "
            "VALUES ($1,'notify','{\"message\":\"cheap market!\"}'::jsonb)", agent_id)

        await run_once(conn)

        fired = await conn.fetchval("SELECT COUNT(*) FROM agent_events WHERE agent_id=$1 AND fired", agent_id)
        notifs = await conn.fetchval("SELECT COUNT(*) FROM notifications WHERE agent_id=$1", agent_id)
        assert fired >= 1
        assert notifs >= 1

        # cleanup
        await conn.execute("DELETE FROM agents WHERE agent_id=$1", agent_id)
        await conn.execute("DELETE FROM markets WHERE market_id='e2e_m'")
        await conn.execute("DELETE FROM events WHERE event_id='e2e_ev'")
