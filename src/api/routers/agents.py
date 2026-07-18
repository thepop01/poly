"""Agent CRUD API. Agents are rule trees + actions owned by a user."""
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.routers.auth import get_current_user
from src.agents.conditions import validate_rule_tree, RuleError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/agents", tags=["agents"])


class ActionIn(BaseModel):
    action_type: str = Field(pattern="^(notify|trade)$")
    params: dict[str, Any] = {}
    sort_order: int = 0


class AgentIn(BaseModel):
    name: str
    description: Optional[str] = None
    rule_tree: dict[str, Any]
    actions: list[ActionIn] = []
    cooldown_seconds: int = 3600


class AgentPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_tree: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    trading_armed: Optional[bool] = None
    cooldown_seconds: Optional[int] = None


def _uid(user: dict) -> str:
    return str(user["sub"])  # users.user_id is UUID; keep as string, asyncpg casts


@router.post("")
async def create_agent(request: Request, body: AgentIn, user: dict = Depends(get_current_user)):
    try:
        validate_rule_tree(body.rule_tree)
    except RuleError as e:
        raise HTTPException(status_code=422, detail=f"invalid rule_tree: {e}")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        async with conn.transaction():
            agent_id = await conn.fetchval(
                """INSERT INTO agents (owner_id, name, description, rule_tree, cooldown_seconds)
                   VALUES ($1::uuid, $2, $3, $4::jsonb, $5) RETURNING agent_id""",
                _uid(user), body.name, body.description,
                json.dumps(body.rule_tree), body.cooldown_seconds,
            )
            for a in body.actions:
                await conn.execute(
                    """INSERT INTO agent_actions (agent_id, action_type, params, sort_order)
                       VALUES ($1, $2, $3::jsonb, $4)""",
                    agent_id, a.action_type, json.dumps(a.params), a.sort_order,
                )
    return {"agent_id": agent_id}


@router.get("")
async def list_agents(request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT agent_id, name, description, is_active, trading_armed,
                      cooldown_seconds, last_evaluated_at, last_fired_at, created_at
               FROM agents WHERE owner_id = $1::uuid ORDER BY created_at DESC""",
            _uid(user),
        )
    return {"agents": [dict(r) for r in rows]}


@router.get("/{agent_id}")
async def get_agent(agent_id: int, request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        agent = await conn.fetchrow(
            "SELECT * FROM agents WHERE agent_id=$1 AND owner_id=$2::uuid", agent_id, _uid(user))
        if not agent:
            raise HTTPException(status_code=404, detail="agent not found")
        actions = await conn.fetch(
            "SELECT action_id, action_type, params, sort_order FROM agent_actions WHERE agent_id=$1 ORDER BY sort_order",
            agent_id)
    out = dict(agent)
    out["actions"] = [dict(a) for a in actions]
    return out


@router.patch("/{agent_id}")
async def patch_agent(agent_id: int, body: AgentPatch, request: Request, user: dict = Depends(get_current_user)):
    if body.rule_tree is not None:
        try:
            validate_rule_tree(body.rule_tree)
        except RuleError as e:
            raise HTTPException(status_code=422, detail=f"invalid rule_tree: {e}")
    fields, values = [], []
    for i, (col, val) in enumerate(
        [("name", body.name), ("description", body.description),
         ("is_active", body.is_active), ("trading_armed", body.trading_armed),
         ("cooldown_seconds", body.cooldown_seconds)], start=1):
        if val is not None:
            fields.append(f"{col} = ${len(values)+1}")
            values.append(val)
    if body.rule_tree is not None:
        fields.append(f"rule_tree = ${len(values)+1}::jsonb")
        values.append(json.dumps(body.rule_tree))
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    fields.append("updated_at = NOW()")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        values.extend([agent_id, _uid(user)])
        row = await conn.fetchrow(
            f"""UPDATE agents SET {', '.join(fields)}
                WHERE agent_id = ${len(values)-1} AND owner_id = ${len(values)}::uuid
                RETURNING agent_id, name, is_active, trading_armed""",
            *values)
        if not row:
            raise HTTPException(status_code=404, detail="agent not found")
    return dict(row)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int, request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM agents WHERE agent_id=$1 AND owner_id=$2::uuid", agent_id, _uid(user))
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="agent not found")
    return {"deleted": agent_id}


@router.get("/{agent_id}/events")
async def agent_events(agent_id: int, request: Request, limit: int = 50, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        owns = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_id=$1 AND owner_id=$2::uuid", agent_id, _uid(user))
        if not owns:
            raise HTTPException(status_code=404, detail="agent not found")
        rows = await conn.fetch(
            """SELECT event_id, fired, matched_summary, created_at
               FROM agent_events WHERE agent_id=$1 ORDER BY created_at DESC LIMIT $2""",
            agent_id, min(limit, 200))
    return {"events": [dict(r) for r in rows]}
