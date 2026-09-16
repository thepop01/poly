# Phase 1: Strategy & Agent Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create **agents** — a saved rule tree of market conditions plus a set of actions — that a background worker evaluates against live Polymarket data each cycle, firing notifications now and (via a dormant, disarmed-by-default broker) trades later.

**Architecture:** New Alembic tables (`agents`, `agent_actions`, `agent_events`, `notifications`) owned by `users`. A pure, `eval`-free **condition DSL** (`src/agents/conditions.py`) evaluates JSON rule trees against a whitelisted market-metric snapshot. A supervised worker (`src/workers/agent_evaluator.py`) polls active agents, evaluates them, writes audit events, and dispatches actions through an `ExecutionBroker` ABC whose only live implementation is `DryRunBroker` (never sends orders). A `/api/v2/agents` router (CRUD + events) and `/api/v2/notifications` router expose it; a `/agents` frontend page builds and lists agents.

**Tech Stack:** FastAPI + asyncpg + Alembic (raw SQL, matching repo convention), Next.js App Router + Tailwind, pytest + pytest-asyncio.

---

## Context (from exploration, 2026-07-18)

- **Alembic head** is `a829c714e8cd`. New migration's `down_revision` must be `'a829c714e8cd'`. Migrations use **raw `op.execute()` SQL**, not the SQLAlchemy op DSL (see `f5a6b7c8d9e0_add_per_category_window_tables.py`).
- **`markets` table** (from `19c895f4fbbb_initial_schema.py`) has: `market_id PK`, `event_id`, `token_id`, `slug`, `title`, `outcome_label`, `status` (`active|resolved|cancelled|pending`), `enable_order_book`, `current_price NUMERIC(10,6)` (0–1), `total_volume NUMERIC(18,2)`, `liquidity NUMERIC(18,2)`, `resolution_date TIMESTAMPTZ`, `created_at`, `last_updated`. This is the metric source for conditions.
- **`users` table** exists (`user_id`, `email`, `password_hash`). `auth.get_current_user` (`src/api/routers/auth.py:109`) is the FastAPI dependency returning a dict with `sub` = user_id; used by `tracked_wallets_v2.py`, `watchlist.py`, `tracker.py`.
- **Router convention:** `router = APIRouter(prefix="/v2/...", tags=[...])`, registered in `src/api/main.py` (imported in the `from src.api.routers import ...` lines + `app.include_router(...)`). The app mounts routers under `/api` (verify the `include_router` prefix — v2 routers already carry `/v2/...`, and are reached at `/api/v2/...`).
- **Worker convention:** module under `src/workers/` exposing an async entrypoint; registered in `src/orchestrator.py`'s `internal_workers` list as `(func, "name")` and supervised with auto-restart. Workers get their own asyncpg connection via `DATABASE_URL` (see `stats_refresher.py`), they do **not** import the API pool.
- **Test harness:** `tests/conftest.py` provides `async_client` and `auth_client` (pre-authenticated JWT for a seeded user) fixtures against a real local `poly_db`. Tests are `@pytest.mark.asyncio`.
- **No LLM anywhere** — Phase 1 must not need one. All conditions are deterministic numeric/time comparisons.

## Data model (target state)

- **`agents`**: `agent_id BIGSERIAL PK`, `owner_id` → `users(user_id)`, `name`, `description`, `rule_tree JSONB` (the condition DSL), `is_active BOOLEAN` (evaluation on/off), `trading_armed BOOLEAN DEFAULT FALSE` (must be TRUE *and* a real broker configured before any live order — always dry-run in Phase 1), `cooldown_seconds INT DEFAULT 3600` (min gap between fires), `last_evaluated_at`, `last_fired_at`, `created_at`, `updated_at`.
- **`agent_actions`**: `action_id BIGSERIAL PK`, `agent_id` → `agents` ON DELETE CASCADE, `action_type` (`notify` | `trade`), `params JSONB` (notify: `{message?}`; trade: `{market_id, token_id, side: 'BUY'|'SELL', outcome: 'YES'|'NO', size_usdc, limit_price?}`), `sort_order INT`.
- **`agent_events`**: `event_id BIGSERIAL PK`, `agent_id` → `agents` ON DELETE CASCADE, `fired BOOLEAN`, `snapshot JSONB` (the metric snapshot evaluated), `matched_summary TEXT`, `created_at`. Audit log of every evaluation that fired (and optionally near-misses — Phase 1 logs only fires).
- **`notifications`**: `notification_id BIGSERIAL PK`, `user_id` → `users`, `agent_id` (nullable), `title`, `body`, `is_read BOOLEAN DEFAULT FALSE`, `created_at`.

## Condition DSL (the core abstraction)

A rule tree is JSON, evaluated by pure Python — **never `eval`/`exec`**:

```json
{"op": "and", "children": [
  {"field": "current_price", "cmp": "lt", "value": 0.15},
  {"op": "or", "children": [
    {"field": "total_volume", "cmp": "gte", "value": 100000},
    {"field": "price_change_1h_pct", "cmp": "gte", "value": 20}
  ]}
]}
```

- **Group node:** `{"op": "and"|"or", "children": [...]}`.
- **Leaf node:** `{"field": <whitelisted>, "cmp": "lt"|"lte"|"gt"|"gte"|"eq"|"ne", "value": <number>}`.
- **Whitelisted fields** (Phase 1, all derivable from `markets` + a cheap price-history lookup): `current_price`, `total_volume`, `liquidity`, `price_change_1h_pct`, `price_change_24h_pct`, `hours_to_resolution`. Any other field name is a validation error.
- A snapshot is a flat `dict[str, float]`. Evaluation returns `(bool, matched_summary: str)`.

---

## Task 1: Alembic migration for agent tables

**Files:**
- Create: `alembic/versions/b1a2g3e4n5t6_add_agent_engine_tables.py`
- Test: `tests/test_agent_migration.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_migration.py -v`
Expected: FAIL — `to_regclass` returns None (tables don't exist yet).

- [ ] **Step 3: Write the migration**

```python
# alembic/versions/b1a2g3e4n5t6_add_agent_engine_tables.py
"""add agent engine tables (agents, actions, events, notifications)

Revision ID: b1a2g3e4n5t6
Revises: a829c714e8cd
Create Date: 2026-07-18 12:00:00
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b1a2g3e4n5t6'
down_revision: Union[str, Sequence[str], None] = 'a829c714e8cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id        BIGSERIAL PRIMARY KEY,
            owner_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            name            VARCHAR(200) NOT NULL,
            description     TEXT,
            rule_tree       JSONB NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT FALSE,
            trading_armed   BOOLEAN NOT NULL DEFAULT FALSE,
            cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
            last_evaluated_at TIMESTAMPTZ,
            last_fired_at   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active) WHERE is_active = TRUE;")
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            action_id   BIGSERIAL PRIMARY KEY,
            agent_id    BIGINT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            action_type VARCHAR(16) NOT NULL CHECK (action_type IN ('notify','trade')),
            params      JSONB NOT NULL DEFAULT '{}'::jsonb,
            sort_order  INTEGER NOT NULL DEFAULT 0
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_actions_agent ON agent_actions(agent_id);")
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            event_id        BIGSERIAL PRIMARY KEY,
            agent_id        BIGINT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            fired           BOOLEAN NOT NULL DEFAULT FALSE,
            snapshot        JSONB,
            matched_summary TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id, created_at DESC);")
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id BIGSERIAL PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            agent_id        BIGINT REFERENCES agents(agent_id) ON DELETE SET NULL,
            title           VARCHAR(300) NOT NULL,
            body            TEXT,
            is_read         BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
    op.execute("DROP TABLE IF EXISTS agent_events;")
    op.execute("DROP TABLE IF EXISTS agent_actions;")
    op.execute("DROP TABLE IF EXISTS agents;")
```

- [ ] **Step 4: Apply the migration and run the test**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m alembic upgrade head && python -m pytest tests/test_agent_migration.py -v`
Expected: migration applies cleanly; both tests PASS.

- [ ] **Step 5: Verify downgrade/upgrade round-trips**

Run: `python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: no errors (idempotent DROP/CREATE).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/b1a2g3e4n5t6_add_agent_engine_tables.py tests/test_agent_migration.py
git commit -m "feat(agents): add agent engine tables migration"
```

---

## Task 2: Condition DSL evaluator (pure, no eval)

**Files:**
- Create: `src/agents/__init__.py` (empty)
- Create: `src/agents/conditions.py`
- Test: `tests/test_agent_conditions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_conditions.py
import pytest
from src.agents.conditions import evaluate, validate_rule_tree, ALLOWED_FIELDS, RuleError


def test_leaf_true():
    tree = {"field": "current_price", "cmp": "lt", "value": 0.15}
    fired, summary = evaluate(tree, {"current_price": 0.10})
    assert fired is True
    assert "current_price" in summary


def test_leaf_false():
    tree = {"field": "current_price", "cmp": "lt", "value": 0.15}
    fired, _ = evaluate(tree, {"current_price": 0.20})
    assert fired is False


def test_and_requires_all():
    tree = {"op": "and", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"field": "total_volume", "cmp": "gte", "value": 100000},
    ]}
    assert evaluate(tree, {"current_price": 0.1, "total_volume": 100000})[0] is True
    assert evaluate(tree, {"current_price": 0.1, "total_volume": 50000})[0] is False


def test_or_requires_any():
    tree = {"op": "or", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"field": "total_volume", "cmp": "gte", "value": 100000},
    ]}
    assert evaluate(tree, {"current_price": 0.9, "total_volume": 100000})[0] is True
    assert evaluate(tree, {"current_price": 0.9, "total_volume": 1})[0] is False


def test_missing_field_is_false_not_crash():
    tree = {"field": "price_change_1h_pct", "cmp": "gte", "value": 20}
    fired, _ = evaluate(tree, {"current_price": 0.5})
    assert fired is False


def test_validate_rejects_unknown_field():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "wallet_balance", "cmp": "gt", "value": 1})


def test_validate_rejects_unknown_cmp():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "current_price", "cmp": "matches", "value": 1})


def test_validate_rejects_non_numeric_value():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "current_price", "cmp": "lt", "value": "cheap"})


def test_validate_accepts_nested_tree():
    tree = {"op": "and", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"op": "or", "children": [
            {"field": "total_volume", "cmp": "gte", "value": 100000},
            {"field": "hours_to_resolution", "cmp": "lte", "value": 24},
        ]},
    ]}
    validate_rule_tree(tree)  # should not raise
    assert "hours_to_resolution" in ALLOWED_FIELDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_conditions.py -v`
Expected: FAIL — `ModuleNotFoundError: src.agents.conditions`.

- [ ] **Step 3: Implement the DSL**

```python
# src/agents/__init__.py
```

```python
# src/agents/conditions.py
"""Pure, eval-free evaluator for agent condition rule trees.

A rule tree is JSON: group nodes {"op": "and"|"or", "children": [...]} and
leaf nodes {"field": <whitelisted>, "cmp": <op>, "value": <number>}.
Evaluation is deterministic and never executes arbitrary code.
"""
from typing import Any

ALLOWED_FIELDS: set[str] = {
    "current_price",
    "total_volume",
    "liquidity",
    "price_change_1h_pct",
    "price_change_24h_pct",
    "hours_to_resolution",
}

_CMP = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


class RuleError(ValueError):
    """Raised when a rule tree is structurally invalid."""


def validate_rule_tree(node: Any) -> None:
    """Raise RuleError if the tree is malformed. No return value."""
    if not isinstance(node, dict):
        raise RuleError("node must be an object")
    if "op" in node:
        if node["op"] not in ("and", "or"):
            raise RuleError(f"unknown op: {node['op']!r}")
        children = node.get("children")
        if not isinstance(children, list):
            raise RuleError("group node needs a 'children' list")
        for child in children:
            validate_rule_tree(child)
        return
    # leaf
    field = node.get("field")
    if field not in ALLOWED_FIELDS:
        raise RuleError(f"unknown field: {field!r}")
    if node.get("cmp") not in _CMP:
        raise RuleError(f"unknown cmp: {node.get('cmp')!r}")
    if not isinstance(node.get("value"), (int, float)) or isinstance(node.get("value"), bool):
        raise RuleError("value must be a number")


def evaluate(node: dict, snapshot: dict[str, float]) -> tuple[bool, str]:
    """Return (fired, human_summary). Missing snapshot fields evaluate False."""
    if "op" in node:
        results = [evaluate(c, snapshot) for c in node.get("children", [])]
        if not results:
            return False, "(empty group)"
        if node["op"] == "and":
            fired = all(r[0] for r in results)
            joiner = " AND "
        else:
            fired = any(r[0] for r in results)
            joiner = " OR "
        summary = joiner.join(r[1] for r in results)
        return fired, f"({summary})"
    field = node["field"]
    cmp = node["cmp"]
    value = node["value"]
    actual = snapshot.get(field)
    if actual is None:
        return False, f"{field}(missing){cmp}{value}=False"
    fired = _CMP[cmp](actual, value)
    return fired, f"{field}({actual}){cmp}{value}={fired}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_conditions.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/__init__.py src/agents/conditions.py tests/test_agent_conditions.py
git commit -m "feat(agents): pure eval-free condition DSL evaluator"
```

---

## Task 3: Execution broker seam (dormant by default)

**Files:**
- Create: `src/agents/execution.py`
- Test: `tests/test_agent_execution.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_execution.py
import pytest
from src.agents.execution import (
    ExecutionBroker, DryRunBroker, PolymarketBroker,
    NotConfiguredError, OrderIntent, get_broker,
)


def test_dry_run_broker_records_but_does_not_send():
    broker = DryRunBroker()
    intent = OrderIntent(market_id="m1", token_id="t1", side="BUY",
                         outcome="YES", size_usdc=10.0, limit_price=0.5)
    receipt = broker.place_order(intent)
    assert receipt["status"] == "dry_run"
    assert receipt["sent"] is False
    assert broker.placed == [intent]


def test_polymarket_broker_refuses_without_keys():
    broker = PolymarketBroker()
    intent = OrderIntent(market_id="m1", token_id="t1", side="BUY",
                         outcome="YES", size_usdc=10.0, limit_price=0.5)
    with pytest.raises(NotConfiguredError):
        broker.place_order(intent)


def test_get_broker_defaults_to_dry_run(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    assert isinstance(get_broker("polymarket"), DryRunBroker)


def test_dry_run_broker_is_execution_broker():
    assert isinstance(DryRunBroker(), ExecutionBroker)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_execution.py -v`
Expected: FAIL — `ModuleNotFoundError: src.agents.execution`.

- [ ] **Step 3: Implement the broker seam**

```python
# src/agents/execution.py
"""Execution seam. Phase 1 ships only DryRunBroker — no real orders are ever
sent. Real venue brokers exist as stubs that refuse until keys + an explicit
EXECUTION_MODE flip are provided (a later phase)."""
import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class NotConfiguredError(RuntimeError):
    """Raised when a live broker is used without credentials/arming."""


@dataclass
class OrderIntent:
    market_id: str
    token_id: str
    side: str            # 'BUY' | 'SELL'
    outcome: str         # 'YES' | 'NO'
    size_usdc: float
    limit_price: float | None = None


class ExecutionBroker(ABC):
    @abstractmethod
    def place_order(self, intent: OrderIntent) -> dict:
        ...


class DryRunBroker(ExecutionBroker):
    """Records intents, sends nothing. The only broker live in Phase 1."""
    def __init__(self) -> None:
        self.placed: list[OrderIntent] = []

    def place_order(self, intent: OrderIntent) -> dict:
        self.placed.append(intent)
        logger.info("DRY-RUN order (not sent): %s", intent)
        return {"status": "dry_run", "sent": False, "intent": intent.__dict__}


class PolymarketBroker(ExecutionBroker):
    """Stub. Refuses until CLOB creds + EXECUTION_MODE=live wired in a later phase."""
    def place_order(self, intent: OrderIntent) -> dict:
        raise NotConfiguredError("Polymarket live execution is not configured")


class KalshiBroker(ExecutionBroker):
    """Stub. Refuses until Kalshi trading keys + EXECUTION_MODE=live (later phase)."""
    def place_order(self, intent: OrderIntent) -> dict:
        raise NotConfiguredError("Kalshi live execution is not configured")


def get_broker(venue: str) -> ExecutionBroker:
    """Return the broker for a venue. Defaults to DryRunBroker unless
    EXECUTION_MODE=live (which is intentionally not honored in Phase 1)."""
    mode = os.getenv("EXECUTION_MODE", "dry_run")
    if mode != "live":
        return DryRunBroker()
    # EXECUTION_MODE=live is reserved for a later phase; still return the
    # venue stub so the refusal is explicit rather than a silent live order.
    if venue == "polymarket":
        return PolymarketBroker()
    if venue == "kalshi":
        return KalshiBroker()
    return DryRunBroker()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_execution.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/execution.py tests/test_agent_execution.py
git commit -m "feat(agents): dormant execution broker seam (dry-run only)"
```

---

## Task 4: Market snapshot builder

**Files:**
- Create: `src/agents/snapshot.py`
- Test: `tests/test_agent_snapshot.py`

**What it does:** turns a `markets` row into the flat `dict[str, float]` snapshot the DSL consumes, computing derived fields (`hours_to_resolution`; price-change fields default to 0.0 in Phase 1 when no history is available — a later task can wire real price history).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_snapshot.py
from datetime import datetime, timezone, timedelta
from src.agents.snapshot import build_snapshot


def _row(**over):
    base = {
        "market_id": "m1",
        "current_price": 0.42,
        "total_volume": 123456.0,
        "liquidity": 5000.0,
        "resolution_date": datetime.now(timezone.utc) + timedelta(hours=48),
    }
    base.update(over)
    return base


def test_snapshot_maps_direct_fields():
    snap = build_snapshot(_row())
    assert snap["current_price"] == 0.42
    assert snap["total_volume"] == 123456.0
    assert snap["liquidity"] == 5000.0


def test_hours_to_resolution_positive():
    snap = build_snapshot(_row())
    assert 47 < snap["hours_to_resolution"] < 49


def test_missing_resolution_date_yields_large_number():
    snap = build_snapshot(_row(resolution_date=None))
    assert snap["hours_to_resolution"] > 10**6


def test_price_change_defaults_zero():
    snap = build_snapshot(_row())
    assert snap["price_change_1h_pct"] == 0.0
    assert snap["price_change_24h_pct"] == 0.0


def test_none_price_coerced():
    snap = build_snapshot(_row(current_price=None))
    assert snap["current_price"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: src.agents.snapshot`.

- [ ] **Step 3: Implement the snapshot builder**

```python
# src/agents/snapshot.py
"""Build a flat metric snapshot (dict[str, float]) from a markets row for the
condition DSL. Price-change fields are placeholders (0.0) in Phase 1."""
from datetime import datetime, timezone
from typing import Any, Mapping

_FAR_FUTURE_HOURS = 10.0 ** 9


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    return float(v)


def build_snapshot(row: Mapping[str, Any]) -> dict[str, float]:
    resolution = row.get("resolution_date")
    if resolution is None:
        hours = _FAR_FUTURE_HOURS
    else:
        if resolution.tzinfo is None:
            resolution = resolution.replace(tzinfo=timezone.utc)
        delta = resolution - datetime.now(timezone.utc)
        hours = delta.total_seconds() / 3600.0
    return {
        "current_price": _f(row.get("current_price")),
        "total_volume": _f(row.get("total_volume")),
        "liquidity": _f(row.get("liquidity")),
        "price_change_1h_pct": 0.0,   # Phase 1 placeholder; wire history later
        "price_change_24h_pct": 0.0,  # Phase 1 placeholder
        "hours_to_resolution": hours,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_snapshot.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/snapshot.py tests/test_agent_snapshot.py
git commit -m "feat(agents): market snapshot builder for condition evaluation"
```

---

## Task 5: Action dispatcher (notify + dry-run trade)

**Files:**
- Create: `src/agents/dispatch.py`
- Test: `tests/test_agent_dispatch.py`

**What it does:** given a fired agent, its actions, and a matched market, executes each action: `notify` → insert a `notifications` row; `trade` → build an `OrderIntent` and route through `get_broker` (dry-run in Phase 1). Trade actions are **skipped with a logged warning unless `agent.trading_armed` is TRUE** — and even when armed, Phase 1's broker only dry-runs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_dispatch.py
import pytest
from src.agents.dispatch import dispatch_actions


class FakeConn:
    def __init__(self):
        self.inserts = []
    async def execute(self, sql, *args):
        self.inserts.append((sql, args))


@pytest.mark.asyncio
async def test_notify_inserts_notification():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "Cheap YES", "trading_armed": False}
    actions = [{"action_type": "notify", "params": {"message": "fired!"}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "Test"},
                                      summary="current_price(0.1)lt0.15=True")
    assert any("notifications" in ins[0] for ins in conn.inserts)
    assert receipts[0]["action_type"] == "notify"


@pytest.mark.asyncio
async def test_trade_skipped_when_not_armed():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "T", "trading_armed": False}
    actions = [{"action_type": "trade", "params": {
        "market_id": "m1", "token_id": "t1", "side": "BUY",
        "outcome": "YES", "size_usdc": 10}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "T"},
                                      summary="x")
    assert receipts[0]["status"] == "skipped_disarmed"


@pytest.mark.asyncio
async def test_trade_dry_run_when_armed():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "T", "trading_armed": True}
    actions = [{"action_type": "trade", "params": {
        "market_id": "m1", "token_id": "t1", "side": "BUY",
        "outcome": "YES", "size_usdc": 10}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "T"},
                                      summary="x")
    assert receipts[0]["status"] == "dry_run"
    assert receipts[0]["sent"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: src.agents.dispatch`.

- [ ] **Step 3: Implement the dispatcher**

```python
# src/agents/dispatch.py
"""Execute an agent's actions after its rule tree fires."""
import logging
from typing import Any, Mapping, Sequence

from src.agents.execution import OrderIntent, get_broker

logger = logging.getLogger(__name__)


async def dispatch_actions(
    conn: Any,
    agent: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    market: Mapping[str, Any],
    summary: str,
) -> list[dict]:
    receipts: list[dict] = []
    for action in actions:
        atype = action["action_type"]
        params = action.get("params") or {}
        if atype == "notify":
            msg = params.get("message") or f"{agent['name']}: {market.get('title')}"
            await conn.execute(
                """INSERT INTO notifications (user_id, agent_id, title, body)
                   VALUES ($1, $2, $3, $4)""",
                agent["owner_id"], agent["agent_id"],
                f"Agent fired: {agent['name']}", f"{msg}\n[{summary}]",
            )
            receipts.append({"action_type": "notify", "status": "sent"})
        elif atype == "trade":
            if not agent.get("trading_armed"):
                logger.warning("Agent %s trade skipped: not armed", agent["agent_id"])
                receipts.append({"action_type": "trade", "status": "skipped_disarmed"})
                continue
            intent = OrderIntent(
                market_id=params["market_id"],
                token_id=params["token_id"],
                side=params["side"],
                outcome=params["outcome"],
                size_usdc=float(params["size_usdc"]),
                limit_price=params.get("limit_price"),
            )
            broker = get_broker(params.get("venue", "polymarket"))
            receipt = broker.place_order(intent)
            receipt["action_type"] = "trade"
            receipts.append(receipt)
        else:
            logger.warning("Unknown action_type %r on agent %s", atype, agent["agent_id"])
            receipts.append({"action_type": atype, "status": "unknown"})
    return receipts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_dispatch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/dispatch.py tests/test_agent_dispatch.py
git commit -m "feat(agents): action dispatcher (notify + disarmed-safe trade)"
```

---

## Task 6: Agents CRUD API router

**Files:**
- Create: `src/api/routers/agents.py`
- Modify: `src/api/main.py` (register router — add to the `from src.api.routers import ...` block and add `app.include_router(agents.router, prefix="/api")`)
- Test: `tests/test_agents_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_agent_requires_auth(async_client: AsyncClient):
    resp = await async_client.post("/api/v2/agents", json={
        "name": "x", "rule_tree": {"op": "and", "children": []}, "actions": []})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_agent(auth_client: AsyncClient):
    payload = {
        "name": "Cheap YES watcher",
        "description": "notify on <15c",
        "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15},
        "actions": [{"action_type": "notify", "params": {"message": "cheap!"}}],
    }
    resp = await auth_client.post("/api/v2/agents", json=payload)
    assert resp.status_code == 200, resp.text
    agent_id = resp.json()["agent_id"]

    resp = await auth_client.get("/api/v2/agents")
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()["agents"]]
    assert "Cheap YES watcher" in names

    # cleanup
    await auth_client.delete(f"/api/v2/agents/{agent_id}")


@pytest.mark.asyncio
async def test_create_agent_rejects_bad_rule_tree(auth_client: AsyncClient):
    payload = {
        "name": "bad",
        "rule_tree": {"field": "not_a_field", "cmp": "lt", "value": 1},
        "actions": [],
    }
    resp = await auth_client.post("/api/v2/agents", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_toggle_active(auth_client: AsyncClient):
    payload = {"name": "toggle me",
               "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15},
               "actions": []}
    agent_id = (await auth_client.post("/api/v2/agents", json=payload)).json()["agent_id"]
    resp = await auth_client.patch(f"/api/v2/agents/{agent_id}", json={"is_active": True})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    await auth_client.delete(f"/api/v2/agents/{agent_id}")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agents_api.py -v`
Expected: FAIL — 404 (router not registered) / import error.

- [ ] **Step 3: Implement the router**

```python
# src/api/routers/agents.py
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
```

- [ ] **Step 4: Register the router in `src/api/main.py`**

Add `agents` to the routers import line and include it. After the existing `app.include_router(...)` calls for v2 routers, add:

```python
from src.api.routers import agents as agents_router
app.include_router(agents_router.router, prefix="/api")
```

(Match the existing include pattern — confirm whether v2 routers are included with `prefix="/api"` and mirror it exactly.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agents_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/agents.py src/api/main.py tests/test_agents_api.py
git commit -m "feat(agents): CRUD API router for agents"
```

---

## Task 7: Notifications API router

**Files:**
- Create: `src/api/routers/notifications.py`
- Modify: `src/api/main.py` (register)
- Test: `tests/test_notifications_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notifications_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_notifications_requires_auth(async_client: AsyncClient):
    resp = await async_client.get("/api/v2/notifications")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_and_mark_read(auth_client: AsyncClient, test_pool):
    # seed a notification for the auth user
    async with test_pool.acquire() as conn:
        uid = await conn.fetchval("SELECT user_id FROM users WHERE email='integration_test@example.com'")
        nid = await conn.fetchval(
            "INSERT INTO notifications (user_id, title, body) VALUES ($1,$2,$3) RETURNING notification_id",
            uid, "hi", "body")
    resp = await auth_client.get("/api/v2/notifications")
    assert resp.status_code == 200
    assert any(n["notification_id"] == nid for n in resp.json()["notifications"])

    resp = await auth_client.post(f"/api/v2/notifications/{nid}/read")
    assert resp.status_code == 200

    async with test_pool.acquire() as conn:
        is_read = await conn.fetchval("SELECT is_read FROM notifications WHERE notification_id=$1", nid)
        assert is_read is True
        await conn.execute("DELETE FROM notifications WHERE notification_id=$1", nid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_notifications_api.py -v`
Expected: FAIL — 404 (router not registered).

- [ ] **Step 3: Implement the router**

```python
# src/api/routers/notifications.py
"""Notifications feed API."""
from fastapi import APIRouter, Request, Depends, HTTPException
from src.api.routers.auth import get_current_user

router = APIRouter(prefix="/v2/notifications", tags=["notifications"])


def _uid(user: dict) -> str:
    return str(user["sub"])  # users.user_id is UUID


@router.get("")
async def list_notifications(request: Request, unread_only: bool = False, limit: int = 50, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    clause = "AND is_read = FALSE" if unread_only else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT notification_id, agent_id, title, body, is_read, created_at
                FROM notifications WHERE user_id = $1::uuid {clause}
                ORDER BY created_at DESC LIMIT $2""",
            _uid(user), min(limit, 200))
    return {"notifications": [dict(r) for r in rows]}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE notifications SET is_read = TRUE WHERE notification_id=$1 AND user_id=$2::uuid",
            notification_id, _uid(user))
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="notification not found")
    return {"marked_read": notification_id}
```

- [ ] **Step 4: Register in `src/api/main.py`**

```python
from src.api.routers import notifications as notifications_router
app.include_router(notifications_router.router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_notifications_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/notifications.py src/api/main.py tests/test_notifications_api.py
git commit -m "feat(agents): notifications feed API"
```

---

## Task 8: Agent evaluator worker

**Files:**
- Create: `src/workers/agent_evaluator.py`
- Modify: `src/orchestrator.py` (register in `internal_workers`)
- Test: `tests/test_agent_evaluator.py`

**What it does:** every `POLL_INTERVAL` seconds, load active agents; for each, evaluate its rule tree against every candidate market snapshot (Phase 1: active order-book markets); on the first market that fires, respecting `cooldown_seconds`, write an `agent_events` row, dispatch actions, and stamp `last_fired_at`. Always stamps `last_evaluated_at`.

- [ ] **Step 1: Write the failing test** (unit-tests the pure evaluation core, not the loop)

```python
# tests/test_agent_evaluator.py
import pytest
from datetime import datetime, timezone, timedelta
from src.workers.agent_evaluator import evaluate_agent_against_markets


def _market(mid, price):
    return {
        "market_id": mid, "token_id": f"t{mid}", "title": f"Market {mid}",
        "current_price": price, "total_volume": 1000.0, "liquidity": 10.0,
        "resolution_date": datetime.now(timezone.utc) + timedelta(hours=10),
    }


def test_returns_first_matching_market():
    agent = {"agent_id": 1, "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15}}
    markets = [_market("a", 0.5), _market("b", 0.10), _market("c", 0.05)]
    hit = evaluate_agent_against_markets(agent, markets)
    assert hit is not None
    market, fired, summary = hit
    assert market["market_id"] == "b"
    assert fired is True


def test_returns_none_when_no_match():
    agent = {"agent_id": 1, "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.01}}
    markets = [_market("a", 0.5), _market("b", 0.10)]
    assert evaluate_agent_against_markets(agent, markets) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError: src.workers.agent_evaluator`.

- [ ] **Step 3: Implement the worker**

```python
# src/workers/agent_evaluator.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_evaluator.py -v`
Expected: PASS.

- [ ] **Step 5: Register in orchestrator**

In `src/orchestrator.py`: add `from src.workers.agent_evaluator import main as agent_evaluator_main` with the other worker imports, and add `(agent_evaluator_main, "agent_evaluator")` to the `internal_workers` list.

- [ ] **Step 6: Smoke-test the worker boots**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && timeout 8 python -m src.workers.agent_evaluator || true`
Expected: logs a cycle (or "no active agents") without traceback, then the timeout kills it.

- [ ] **Step 7: Commit**

```bash
git add src/workers/agent_evaluator.py src/orchestrator.py tests/test_agent_evaluator.py
git commit -m "feat(agents): agent evaluator worker + orchestrator registration"
```

---

## Task 9: Frontend — Agents page (list + builder + notifications)

**Files:**
- Create: `frontend/src/app/agents/page.tsx`
- Create: `frontend/src/app/agents/AgentBuilder.tsx`
- Modify: `frontend/src/lib/Sidebar.tsx` (add an "Agents" nav link)
- Modify: `frontend/src/lib/api.ts` (add agent + notification fetchers)

**Note:** match the existing App Router page conventions (client components, the repo's fetch wrapper in `frontend/src/lib/api.ts`, Tailwind classes used elsewhere). Read an existing page (e.g. `frontend/src/app/wallets/page.tsx`) first and mirror its data-fetching + layout patterns rather than inventing new ones.

- [ ] **Step 1: Add API helpers in `frontend/src/lib/api.ts`**

Add (adapting to the file's existing `API_BASE`/fetch-wrapper style):

```typescript
export async function listAgents() {
  return apiFetch(`/api/v2/agents`);
}
export async function createAgent(body: {
  name: string; description?: string; rule_tree: any;
  actions: { action_type: string; params: any }[]; cooldown_seconds?: number;
}) {
  return apiFetch(`/api/v2/agents`, { method: "POST", body: JSON.stringify(body) });
}
export async function toggleAgentActive(agentId: number, is_active: boolean) {
  return apiFetch(`/api/v2/agents/${agentId}`, { method: "PATCH", body: JSON.stringify({ is_active }) });
}
export async function deleteAgent(agentId: number) {
  return apiFetch(`/api/v2/agents/${agentId}`, { method: "DELETE" });
}
export async function listNotifications() {
  return apiFetch(`/api/v2/notifications`);
}
```

- [ ] **Step 2: Build the agents list page**

`frontend/src/app/agents/page.tsx` — a client component that:
- fetches `listAgents()` on mount, renders a table (name, active toggle, trading_armed badge showing "DRY-RUN" always in Phase 1, last fired, delete button);
- renders `<AgentBuilder onCreated={refresh} />` above the table;
- renders a notifications panel from `listNotifications()`.

- [ ] **Step 3: Build the AgentBuilder form**

`frontend/src/app/agents/AgentBuilder.tsx` — a form that collects: name, description, one or more condition rows (field dropdown from the six whitelisted fields, cmp dropdown, numeric value), combined via a top-level AND/OR selector, and an actions section (notify with a message; trade fields hidden behind a disabled "arm trading (coming soon)" note in Phase 1). On submit, assembles the `rule_tree` JSON and calls `createAgent`.

- [ ] **Step 4: Add the sidebar link**

In `frontend/src/lib/Sidebar.tsx`, add an "Agents" entry pointing to `/agents`, matching the existing nav-item markup.

- [ ] **Step 5: Verify the build**

Run: `cd "C:\Users\shubh\Downloads\project\poly\frontend" && npm run build`
Expected: build succeeds with no type errors on the new files.

- [ ] **Step 6: Manual smoke test**

Start the API (`python -m uvicorn src.api.main:app --port 8000`) and frontend (`npm run dev`), sign in, create a notify-only agent with `current_price < 0.15`, toggle it active, and confirm (after the worker runs, or by invoking `run_once`) a notification appears.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/agents frontend/src/lib/Sidebar.tsx frontend/src/lib/api.ts
git commit -m "feat(agents): agents page, builder form, notifications panel"
```

---

## Task 10: End-to-end integration test

**Files:**
- Test: `tests/test_agent_e2e.py`

- [ ] **Step 1: Write the E2E test**

```python
# tests/test_agent_e2e.py
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
```

- [ ] **Step 2: Run the full agent test suite**

Run: `cd "C:\Users\shubh\Downloads\project\poly" && python -m pytest tests/test_agent_migration.py tests/test_agent_conditions.py tests/test_agent_execution.py tests/test_agent_snapshot.py tests/test_agent_dispatch.py tests/test_agents_api.py tests/test_notifications_api.py tests/test_agent_evaluator.py tests/test_agent_e2e.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_e2e.py
git commit -m "test(agents): end-to-end fire-and-notify integration test"
```

---

## Self-review checklist (completed during authoring)

- **Spec coverage:** create agents with conditions+commands (Tasks 1,2,6) ✅; notifications (Tasks 5,7,9) ✅; autonomous trading as a *dormant, disarmed-by-default* seam (Tasks 3,5) ✅; background evaluation (Task 8) ✅; UI (Task 9) ✅. Strategy backtesting and AI-authored strategies are explicitly **Phase 2**, not here.
- **Type consistency:** `rule_tree` JSONB everywhere; `evaluate()`/`validate_rule_tree()`/`RuleError` names consistent across conditions.py, agents.py, agent_evaluator.py; `OrderIntent`/`get_broker`/`NotConfiguredError` consistent across execution.py and dispatch.py; `evaluate_agent_against_markets` returns `(market, fired, summary)` used identically in worker + test.
- **Placeholder scan:** price-change fields are documented Phase-1 placeholders (0.0) with a named follow-up, not silent TODOs; all code steps contain full code.
- **Assumptions to verify at execution time (not blocking):** (1) exact `app.include_router` prefix for v2 routers in `main.py` — mirror it; (2) `users.user_id` integer type (migration FK assumes INTEGER — confirm against the users migration and adjust if BIGINT); (3) frontend `apiFetch` wrapper name in `api.ts` — adapt helper calls to the real wrapper.
