"""Evaluate active agents against live market snapshots. Fires actions
(notify now; dry-run trade) respecting per-agent cooldown."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import asyncpg

from src.agents.conditions import evaluate
from src.agents.snapshot import build_snapshot
from src.agents.dispatch import dispatch_actions

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = int(os.getenv("AGENT_POLL_INTERVAL", "60"))
MARKET_LIMIT = int(os.getenv("AGENT_MARKET_LIMIT", "2000"))


def evaluate_agent_against_markets(agent, markets):
    """Return (market, fired, summary) for the first firing market, else None."""
    rule_tree = agent["rule_tree"]
    if isinstance(rule_tree, str):
        rule_tree = json.loads(rule_tree)
    for m in markets:
        snap = build_snapshot(m)
        fired, summary = evaluate(rule_tree, snap)
        if fired:
            return m, fired, summary
    return None


async def _load_active_agents(conn):
    rows = await conn.fetch("""
        SELECT agent_id, owner_id, name, rule_tree, trading_armed,
               cooldown_seconds, last_fired_at
        FROM agents WHERE is_active = TRUE
    """)
    return [dict(r) for r in rows]


async def _load_candidate_markets(conn):
    rows = await conn.fetch("""
        SELECT market_id, token_id, title, current_price, total_volume,
               liquidity, resolution_date
        FROM markets
        WHERE status = 'active' AND enable_order_book = TRUE
        ORDER BY total_volume DESC NULLS LAST
        LIMIT $1
    """, MARKET_LIMIT)
    return [dict(r) for r in rows]


async def _load_actions(conn, agent_id):
    rows = await conn.fetch(
        "SELECT action_type, params, sort_order FROM agent_actions WHERE agent_id=$1 ORDER BY sort_order",
        agent_id)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("params"), str):
            d["params"] = json.loads(d["params"])
        out.append(d)
    return out


def _in_cooldown(agent, now):
    last = agent.get("last_fired_at")
    if last is None:
        return False
    return now - last < timedelta(seconds=agent.get("cooldown_seconds", 3600))


async def run_once(conn):
    now = datetime.now(timezone.utc)
    agents = await _load_active_agents(conn)
    if not agents:
        return
    markets = await _load_candidate_markets(conn)
    for agent in agents:
        await conn.execute("UPDATE agents SET last_evaluated_at=$1 WHERE agent_id=$2", now, agent["agent_id"])
        if _in_cooldown(agent, now):
            continue
        hit = evaluate_agent_against_markets(agent, markets)
        if hit is None:
            continue
        market, fired, summary = hit
        await conn.execute(
            """INSERT INTO agent_events (agent_id, fired, snapshot, matched_summary)
               VALUES ($1, TRUE, $2::jsonb, $3)""",
            agent["agent_id"], json.dumps(build_snapshot(market)), summary)
        actions = await _load_actions(conn, agent["agent_id"])
        await dispatch_actions(conn, agent, actions, market, summary)
        await conn.execute("UPDATE agents SET last_fired_at=$1 WHERE agent_id=$2", now, agent["agent_id"])
        logger.info("Agent %s fired on market %s", agent["agent_id"], market["market_id"])


async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        while True:
            try:
                await run_once(conn)
            except Exception:
                logger.exception("agent_evaluator cycle failed")
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
