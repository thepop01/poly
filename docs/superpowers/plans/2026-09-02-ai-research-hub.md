# AI Research Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, white-theme AI research workspace at `/hub` where each top-level tab is an independent chat and each chat creates auto-arranged, evidence-backed panels for wallet discovery, market activity, open-position overlap, and outcome consensus.

**Architecture:** The FastAPI backend owns chat persistence, typed analytical tools, result-set snapshots, and a provider-independent orchestration loop. The language model may select only registered tools with validated arguments; it never receives database credentials or executes generated SQL. The Next.js 16 client streams newline-delimited events into a two-column workspace: conversation on the left and a typed panel canvas on the right.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL, Pydantic 2, httpx, pytest/pytest-asyncio, Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Vitest, Testing Library.

---

## 1. Product contract and locked decisions

### 1.1 Workspace behavior

- `/hub` is a new Research Hub. Keep `/agents` for deterministic background automations.
- Each top tab is one persisted chat. Closing a tab removes it from the open tab strip but does not delete it; deletion is a separate confirmed action.
- A chat owns its messages, named result sets, panels, and panel layout.
- The default desktop split is a 360 px conversation rail and a flexible canvas. The split is resizable from 300–560 px and stored per browser.
- The canvas uses a 12-column grid. Panels are placed automatically from a fixed registry; users can minimize, maximize, close, and restore panels. Drag-and-drop and arbitrary resizing are outside the first release.
- Hybrid panel updates are the default: refining the same analysis updates the relevant panel; changing result type creates a new panel.
- The UI is light only and reuses the existing `background`, `surface`, `border`, `primary`, `success`, and `danger` tokens.

### 1.2 Analytical meaning

- “More than 70% win rate” means `win_rate > 70`, not `>= 70`.
- Category, subcategory, and league filters use `category_stats_v2` with `window_size = 0` unless the user explicitly requests a historical position window.
- The default evidence floor is 20 resolved positions. The response must display the floor and each wallet's `resolved_count`. If the user explicitly requests a different floor, use it.
- A wallet is in an open position only when `wallet_positions_v2.current_value > 0` and the stored row is not resolved.
- “All of them” means `distinct_wallet_count = input_result_set.row_count`. “Most” is never silently substituted for “all.”
- Consensus is grouped by the market's stored outcome label. Binary markets may be summarized as YES/NO; multi-outcome markets must retain their actual labels.
- Historical same-market/same-outcome analysis is descriptive. It must not label wallets as coordinated, copied, or collusive without separate temporal evidence.
- All monetary and win-rate values come from database fields. The model may explain values but may not invent, rescale, or repair them.

### 1.3 First-release analytical tools

| Tool | Input | Output/result kind | Default panel |
|---|---|---|---|
| `find_wallets` | category scope, strict win-rate threshold, evidence floor, limit, sort | `wallet_set` | Wallet table |
| `markets_traded` | wallet result-set ID, state (`open`, `closed`, `all`), category scope | `market_set` | Market table |
| `open_position_overlap` | wallet result-set ID, minimum coverage | `position_overlap` | Overlap table |
| `market_participants` | market ID/slug plus wallet filters | `market_participants` | Wallet table + outcome summary |
| `outcome_consensus` | wallet result-set ID and optional market result-set ID | `outcome_consensus` | Consensus table/cards |
| `same_outcome_history` | wallet result-set ID, category scope, minimum coverage | `same_outcome_history` | Historical overlap table |
| `page_result_set` | result-set ID, offset, limit | unchanged | Updates existing panel |

### 1.4 Non-goals for this plan

- No order placement, wallet signing, strategy arming, or autonomous trading.
- No unrestricted SQL generation or direct database access from the model.
- No web search or external market research inside the terminal.
- No collaborative/shared chats, public links, mobile multi-panel canvas, drag-and-drop grid, or chart builder.
- No replacement of existing wallet, feed, tracker, or agent pages.

## 2. Request and data flow

```text
User prompt
  -> POST /api/v2/research/chats/{chat_id}/runs
  -> persist user message + queued run
  -> orchestrator loads compact chat context and result-set references
  -> model selects a registered tool with JSON arguments
  -> Pydantic validates arguments and ownership
  -> analytical service executes parameterized SQL
  -> immutable result-set snapshot + members are persisted
  -> panel is created or updated by deterministic panel policy
  -> assistant answer is persisted
  -> NDJSON events stream: run.started, tool.started, result.created,
     panel.upserted, assistant.delta, run.completed
  -> React query state applies events and renders the panel registry
```

The model receives compact summaries and opaque result-set IDs, never hundreds of raw rows in conversation history. Follow-ups such as “those wallets” resolve through the current chat's result references.

## 3. File structure

### Backend files to create

- `alembic/versions/w6x7y8z9a0b1_add_research_hub.py` — workspace tables and analytical indexes.
- `src/research/contracts.py` — enums, tool input models, result and stream-event contracts.
- `src/research/repository.py` — owner-scoped chat, message, run, result-set, member, and panel persistence.
- `src/research/analytics.py` — parameterized SQL for the six analytical tools.
- `src/research/tools.py` — tool registry, schema export, validation, and dispatch.
- `src/research/context.py` — compact context construction and reference resolution.
- `src/research/llm.py` — provider interface, OpenAI adapter, and deterministic fake used by tests.
- `src/research/orchestrator.py` — bounded tool loop and panel upsert policy.
- `src/research/__init__.py` — package exports.
- `src/api/routers/research.py` — authenticated CRUD, pagination, and streamed-run endpoints.
- `tests/test_research_migration.py` — schema and ownership constraints.
- `tests/test_research_repository.py` — persistence behavior.
- `tests/test_research_analytics.py` — query semantics using seeded wallets/markets.
- `tests/test_research_tools.py` — registry validation and dispatch.
- `tests/test_research_context.py` — “those wallets” reference behavior.
- `tests/test_research_orchestrator.py` — tool loop, panel reuse, and safety limits.
- `tests/test_research_api.py` — auth, CRUD, streaming, isolation, and error events.

### Backend files to modify

- `pyproject.toml` — add the OpenAI SDK dependency used only by the adapter.
- `.env.example` — document `OPENAI_API_KEY`, `RESEARCH_MODEL`, and run limits.
- `src/api/main.py` — register the research router.

### Frontend files to create

- `frontend/src/app/hub/page.tsx` — route entry and client workspace boundary.
- `frontend/src/app/hub/ResearchHub.tsx` — workspace composition and event reducer.
- `frontend/src/components/research/ChatTabs.tsx` — open chats, create, rename, close, reopen.
- `frontend/src/components/research/ChatRail.tsx` — messages, run status, composer.
- `frontend/src/components/research/PanelCanvas.tsx` — deterministic 12-column placement.
- `frontend/src/components/research/PanelFrame.tsx` — panel chrome and controls.
- `frontend/src/components/research/PanelRenderer.tsx` — exhaustive panel-type switch.
- `frontend/src/components/research/panels/WalletTablePanel.tsx` — wallet results.
- `frontend/src/components/research/panels/MarketTablePanel.tsx` — market results.
- `frontend/src/components/research/panels/OverlapPanel.tsx` — coverage and shared positions.
- `frontend/src/components/research/panels/ConsensusPanel.tsx` — outcome counts, percentages, and capital.
- `frontend/src/components/research/EmptyResearchState.tsx` — example prompts and first-run guidance.
- `frontend/src/hooks/useResearchHub.ts` — query/mutation state and stream cancellation.
- `frontend/src/utils/researchApi.ts` — typed CRUD and NDJSON streaming client.
- `frontend/src/types/research.ts` — shared UI types matching backend JSON.
- `frontend/src/components/ContentFrame.tsx` — removes ordinary page padding only for `/hub`.
- `frontend/src/test/setup.ts` — DOM test setup.
- `frontend/src/components/research/__tests__/ChatTabs.test.tsx` — tab behavior.
- `frontend/src/components/research/__tests__/PanelCanvas.test.tsx` — panel reuse and layout.
- `frontend/src/components/research/__tests__/ChatRail.test.tsx` — submit and busy behavior.

### Frontend files to modify

- `frontend/src/app/layout.tsx` — wrap page content with `ContentFrame`.
- `frontend/src/components/Sidebar.tsx` — add Research Hub navigation.
- `frontend/src/app/globals.css` — workspace grid, splitter, and panel utilities.
- `frontend/package.json` and `frontend/package-lock.json` — test dependencies and `test` script.

### Documentation files to modify after implementation

- `docs/API_REFERENCE.md` — research endpoints and stream events.
- `docs/CORE_LOGIC.md` — analytical definitions and evidence boundaries.
- `docs/learner.md` — result-set references, NDJSON behavior, and query/index gotchas.
- `docs/CHANGELOG.md` — one newest-first release entry.

---

## Milestone A — Persistent workspace foundation

### Task 1: Add research workspace schema and indexes

**Files:**
- Create: `alembic/versions/w6x7y8z9a0b1_add_research_hub.py`
- Test: `tests/test_research_migration.py`

- [ ] **Step 1: Write the failing schema test**

```python
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
```

- [ ] **Step 2: Run the test and verify the pre-migration failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_migration.py -v`

Expected: failure naming `research_chats` as missing.

- [ ] **Step 3: Create the migration**

Use revision `w6x7y8z9a0b1` with `down_revision = "v5w6x7y8z9"`. Create:

```sql
CREATE TABLE research_chats (
    chat_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL DEFAULT 'New research',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_research_chats_owner_updated
    ON research_chats(owner_id, is_archived, updated_at DESC);

CREATE TABLE research_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
    prompt TEXT NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE research_messages (
    message_id BIGSERIAL PRIMARY KEY,
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_runs(run_id) ON DELETE SET NULL,
    role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','tool')),
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_research_messages_chat_created
    ON research_messages(chat_id, message_id);

CREATE TABLE research_result_sets (
    result_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_runs(run_id) ON DELETE SET NULL,
    kind VARCHAR(40) NOT NULL,
    label VARCHAR(160) NOT NULL,
    definition JSONB NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE research_result_members (
    result_set_id UUID NOT NULL REFERENCES research_result_sets(result_set_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    entity_type VARCHAR(24) NOT NULL,
    entity_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (result_set_id, ordinal)
);
CREATE INDEX idx_research_members_entity
    ON research_result_members(result_set_id, entity_type, entity_key);

CREATE TABLE research_panels (
    panel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    result_set_id UUID REFERENCES research_result_sets(result_set_id) ON DELETE SET NULL,
    panel_type VARCHAR(40) NOT NULL,
    panel_key VARCHAR(120) NOT NULL,
    title VARCHAR(160) NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'normal' CHECK (state IN ('normal','minimized','maximized','closed')),
    layout JSONB NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(chat_id, panel_key)
);

CREATE INDEX idx_wallet_positions_market_wallet
    ON wallet_positions_v2(condition_id, address, outcome)
    WHERE COALESCE(current_value, 0) > 0 AND COALESCE(is_resolved, FALSE) = FALSE;
CREATE INDEX idx_closed_positions_market_wallet
    ON wallet_closed_positions_v2(condition_id, address, outcome)
    WHERE COALESCE(metrics_eligible, TRUE);
CREATE INDEX idx_category_stats_scope_winrate
    ON category_stats_v2(category, subcategory, league, window_size, win_rate DESC, resolved_count DESC);
```

Implement `downgrade()` by dropping the six research tables in reverse dependency order and only the three indexes introduced here.

- [ ] **Step 4: Apply and verify the migration**

Run: `.\.venv\Scripts\python.exe -m alembic upgrade head`

Expected: database advances from `v5w6x7y8z9` to `w6x7y8z9a0b1`.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_migration.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add alembic/versions/w6x7y8z9a0b1_add_research_hub.py tests/test_research_migration.py
git commit -m "feat(research): add persistent workspace schema"
```

### Task 2: Define typed research contracts

**Files:**
- Create: `src/research/__init__.py`
- Create: `src/research/contracts.py`
- Test: `tests/test_research_tools.py`

- [ ] **Step 1: Write failing validation tests**

```python
import pytest
from pydantic import ValidationError
from src.research.contracts import FindWalletsArgs, PositionOverlapArgs


def test_find_wallets_defaults_are_safe_and_bounded():
    args = FindWalletsArgs(category="Sports", subcategory="Cricket", league="T20")
    assert args.min_win_rate == 70
    assert args.comparison == "gt"
    assert args.min_resolved_count == 20
    assert args.limit == 100


def test_tool_limits_reject_oversized_requests():
    with pytest.raises(ValidationError):
        FindWalletsArgs(category="Sports", limit=1001)


def test_overlap_requires_owned_wallet_result_reference():
    with pytest.raises(ValidationError):
        PositionOverlapArgs(wallet_result_set_id="not-a-uuid")
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_tools.py -v`

Expected: `ModuleNotFoundError: src.research`.

- [ ] **Step 3: Implement the contracts**

Define `ResultKind`, `PanelType`, `RunStatus`, `StreamEventType`, `Scope`, and one Pydantic model per tool. Use constrained fields:

```python
from enum import StrEnum
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class ResultKind(StrEnum):
    WALLET_SET = "wallet_set"
    MARKET_SET = "market_set"
    POSITION_OVERLAP = "position_overlap"
    MARKET_PARTICIPANTS = "market_participants"
    OUTCOME_CONSENSUS = "outcome_consensus"
    SAME_OUTCOME_HISTORY = "same_outcome_history"


class Scope(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    league: str | None = None
    window_size: int = Field(default=0, ge=0, le=5000)


class FindWalletsArgs(Scope):
    min_win_rate: float = Field(default=70, ge=0, le=100)
    comparison: Literal["gt", "gte"] = "gt"
    min_resolved_count: int = Field(default=20, ge=1, le=100_000)
    sort_by: Literal["win_rate", "pnl", "volume", "resolved_count"] = "win_rate"
    limit: int = Field(default=100, ge=1, le=1000)


class PositionOverlapArgs(BaseModel):
    wallet_result_set_id: UUID
    min_wallet_count: int = Field(default=2, ge=2, le=1000)
    limit: int = Field(default=100, ge=1, le=500)


class MarketsTradedArgs(Scope):
    wallet_result_set_id: UUID
    state: Literal["open", "closed", "all"] = "all"
    limit: int = Field(default=100, ge=1, le=500)


class MarketParticipantsArgs(BaseModel):
    condition_id: str = Field(min_length=3, max_length=255)
    min_win_rate: float | None = Field(default=None, ge=0, le=100)
    min_resolved_count: int = Field(default=20, ge=1, le=100_000)
    scope: Scope = Field(default_factory=Scope)
    limit: int = Field(default=100, ge=1, le=500)


class OutcomeConsensusArgs(BaseModel):
    wallet_result_set_id: UUID
    market_result_set_id: UUID | None = None
    condition_id: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=100, ge=1, le=500)


class SameOutcomeHistoryArgs(Scope):
    wallet_result_set_id: UUID
    min_wallet_count: int = Field(default=2, ge=2, le=1000)
    include_open: bool = False
    limit: int = Field(default=100, ge=1, le=500)
```

Also define serializable `ResearchChat`, `ResearchMessage`, `ResearchPanel`, `ResultSetSummary`, and `StreamEvent` response models. All UUIDs serialize as strings and all timestamps are timezone-aware.

- [ ] **Step 4: Run the contract tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_tools.py -v`

Expected: all validation tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/research tests/test_research_tools.py
git commit -m "feat(research): define typed tool and panel contracts"
```

### Task 3: Implement owner-scoped workspace persistence

**Files:**
- Create: `src/research/repository.py`
- Test: `tests/test_research_repository.py`

- [ ] **Step 1: Write failing repository tests**

Test creation, title update, archive, message ordering, result member ordering, panel upsert by `(chat_id, panel_key)`, and cross-owner denial. The ownership assertion must be explicit:

```python
@pytest.mark.asyncio
async def test_owner_cannot_read_another_users_chat(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    chat = await repo.create_chat(two_users.first, "Cricket research")
    assert await repo.get_chat(two_users.second, chat.chat_id) is None
```

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_repository.py -v`

Expected: import failure for `ResearchRepository`.

- [ ] **Step 3: Implement `ResearchRepository`**

Every public method accepts `owner_id`; child-row operations join through `research_chats` rather than trusting only a child UUID. Provide these exact public methods: `create_chat`, `list_chats`, `get_chat`, `rename_chat`, `archive_chat`, `add_message`, `list_messages`, `create_run`, `set_run_status`, `save_result_set`, `list_result_summaries`, `page_result_members`, `upsert_panel`, and `update_panel_state`. Preserve the argument and return types established by `contracts.py`.

Use this complete owner-scoped pattern for every single-row mutation:

```python
async def rename_chat(self, owner_id: str, chat_id: UUID, title: str) -> ResearchChat | None:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE research_chats
               SET title = $3, updated_at = NOW()
               WHERE chat_id = $1 AND owner_id = $2::uuid
               RETURNING chat_id, title, is_archived, created_at, updated_at""",
            chat_id, owner_id, title,
        )
    return ResearchChat.model_validate(dict(row)) if row else None
```

For child resources, enforce ownership inside the statement with `FROM research_chats c WHERE child.chat_id = c.chat_id AND c.owner_id = $owner`; never authorize in one query and mutate in a later query. `list_messages` orders by `message_id ASC`, filters `message_id > after_id`, and caps the caller-supplied limit at 200. `list_result_summaries` orders by `created_at DESC` and returns no member payloads.

`save_result_set` must use one transaction, insert the header, batch `executemany` the members with stable ordinals, and set `row_count = len(members)`. Never interpolate owner IDs, entity keys, titles, or filters into SQL.

- [ ] **Step 4: Run the repository tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_repository.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/research/repository.py tests/test_research_repository.py
git commit -m "feat(research): persist chats results and panels"
```

---

## Milestone B — Deterministic analytical engine

### Task 4: Implement wallet discovery and market-participant queries

**Files:**
- Create: `src/research/analytics.py`
- Test: `tests/test_research_analytics.py`

- [ ] **Step 1: Seed exact analytical fixtures in the failing tests**

Create three wallets, category rows for `SPORTS / Cricket / T20`, one market, and open positions. Verify strict threshold and evidence floor:

```python
rows = await analytics.find_wallets(
    FindWalletsArgs(category="SPORTS", subcategory="Cricket", league="T20",
                    min_win_rate=70, comparison="gt", min_resolved_count=20, limit=100)
)
assert [row["address"] for row in rows] == [wallet_80_percent]
assert rows[0]["scope"] == {"category": "SPORTS", "subcategory": "Cricket", "league": "T20", "window_size": 0}
```

The 70.0% wallet must be excluded; the 90% wallet with only 10 resolved positions must also be excluded.

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_analytics.py -v`

Expected: import failure for `ResearchAnalytics`.

- [ ] **Step 3: Implement `find_wallets` with parameterized clauses**

Build clauses and parameters in Python, but select only from the known identifier map:

```python
SORT_COLUMNS = {
    "win_rate": "c.win_rate",
    "pnl": "c.pnl",
    "volume": "c.volume",
    "resolved_count": "c.resolved_count",
}
comparison_sql = ">" if args.comparison == "gt" else ">="
```

The query must join `wallets_v2`, `wallet_metrics_v2`, and `category_stats_v2`; filter exact category/subcategory/league scope and `window_size`; return category-scoped `win_rate`, `pnl`, `volume`, `resolved_count`, and `winning_count`, plus overall `balance`, `position_value`, `last_trade_at`, and username. Order deterministically by the requested column, then `resolved_count DESC`, then address.

- [ ] **Step 4: Implement `market_participants`**

Join `wallet_positions_v2` to `markets_v2`, `wallets_v2`, the requested `category_stats_v2` scope, and `wallet_metrics_v2`. Return one row per wallet/outcome with size, average price, current value, outcome, scoped win rate, resolved count, category PnL, and last activity. Require positive current value and unresolved position state.

- [ ] **Step 5: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_analytics.py -k "wallet or participant" -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/research/analytics.py tests/test_research_analytics.py
git commit -m "feat(research): query qualified wallets and market participants"
```

### Task 5: Implement market history, overlap, and consensus queries

**Files:**
- Modify: `src/research/analytics.py`
- Modify: `tests/test_research_analytics.py`

- [ ] **Step 1: Add failing overlap tests**

Seed a saved wallet result set containing three wallets. Seed market A held by all three with two YES and one NO, market B held by two, and market C held by one. Assert:

```python
overlap = await analytics.open_position_overlap(owner_id, args)
assert overlap[0]["condition_id"] == market_a
assert overlap[0]["wallet_count"] == 3
assert overlap[0]["coverage_pct"] == 100.0
assert overlap[0]["outcomes"] == {"NO": 1, "YES": 2}
```

Also assert that referencing a result set owned by another user raises `ResultSetAccessError` before analytical SQL runs.

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_analytics.py -k "overlap or consensus or history" -v`

Expected: failures for the new unimplemented methods.

- [ ] **Step 3: Implement set-based SQL methods**

Add four async methods with the exact names `markets_traded`, `open_position_overlap`, `outcome_consensus`, and `same_outcome_history`. Each accepts `owner_id: str` followed by its matching Pydantic argument model and returns `list[dict]`.

All four methods must start from `research_result_members` joined through `research_result_sets` and `research_chats`, with `c.owner_id = $1` and `entity_type = 'wallet'`. Do not fetch 100 addresses into Python and issue one query per wallet.

For overlap and consensus, aggregate by `condition_id` and normalized stored outcome; calculate:

```sql
COUNT(DISTINCT p.address) AS wallet_count,
ROUND(100.0 * COUNT(DISTINCT p.address) / NULLIF(input.input_count, 0), 2) AS coverage_pct,
SUM(p.current_value) AS current_value,
SUM(p.size) AS shares
```

Return an `outcomes` object assembled from grouped rows in Python using real labels. For historical analysis, use only `wallet_closed_positions_v2.metrics_eligible = TRUE`; union open rows only when `include_open` is true and mark each row's source.

- [ ] **Step 4: Run the complete analytical test module**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_analytics.py -v`

Expected: all tests pass and no test permits cross-owner references.

- [ ] **Step 5: Commit**

```powershell
git add src/research/analytics.py tests/test_research_analytics.py
git commit -m "feat(research): add cross-wallet overlap and consensus analytics"
```

### Task 6: Register tools and persist immutable result sets

**Files:**
- Create: `src/research/tools.py`
- Modify: `tests/test_research_tools.py`

- [ ] **Step 1: Write failing registry tests**

Assert every public tool has a unique name, a Pydantic argument model, an explicit result kind, and a handler. Assert unknown tools and invalid arguments fail without calling analytics.

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_tools.py -k registry -v`

Expected: import or missing-registry failure.

- [ ] **Step 3: Implement the registry**

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    result_kind: ResultKind
    panel_type: PanelType
    handler_name: str


TOOL_DEFINITIONS = (
    ToolDefinition("find_wallets", "Find wallets by scoped evidence-backed performance.", FindWalletsArgs, ResultKind.WALLET_SET, PanelType.WALLET_TABLE, "find_wallets"),
    ToolDefinition("markets_traded", "Aggregate markets traded by a saved wallet set.", MarketsTradedArgs, ResultKind.MARKET_SET, PanelType.MARKET_TABLE, "markets_traded"),
    ToolDefinition("open_position_overlap", "Find open markets shared by a saved wallet set.", PositionOverlapArgs, ResultKind.POSITION_OVERLAP, PanelType.OVERLAP_TABLE, "open_position_overlap"),
    ToolDefinition("market_participants", "Find and rank qualified wallets in a market.", MarketParticipantsArgs, ResultKind.MARKET_PARTICIPANTS, PanelType.WALLET_TABLE, "market_participants"),
    ToolDefinition("outcome_consensus", "Measure outcome choice and capital by market.", OutcomeConsensusArgs, ResultKind.OUTCOME_CONSENSUS, PanelType.CONSENSUS, "outcome_consensus"),
    ToolDefinition("same_outcome_history", "Measure repeated historical market/outcome overlap.", SameOutcomeHistoryArgs, ResultKind.SAME_OUTCOME_HISTORY, PanelType.OVERLAP_TABLE, "same_outcome_history"),
)
```

`execute_tool` must validate arguments, call the mapped analytics method, derive a factual summary, persist the result header and members, and return `ToolExecution(result_set, panel_type)`. Tool descriptions must state defaults and definitions so the model does not guess them.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_tools.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/research/tools.py tests/test_research_tools.py
git commit -m "feat(research): add validated analytical tool registry"
```

---

## Milestone C — Conversational orchestration and streaming

### Task 7: Build compact chat context and reference resolution

**Files:**
- Create: `src/research/context.py`
- Test: `tests/test_research_context.py`

- [ ] **Step 1: Write failing reference tests**

Cover “those wallets,” “them,” “the previous markets,” and explicit result labels. The most recent compatible result in the same chat wins; another chat's result never resolves.

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_context.py -v`

Expected: import failure.

- [ ] **Step 3: Implement context construction**

```python
@dataclass(frozen=True)
class ResearchContext:
    messages: list[dict[str, str]]
    result_refs: list[dict[str, object]]


async def build_context(repo, owner_id: str, chat_id: UUID) -> ResearchContext:
    messages = await repo.list_messages(owner_id, chat_id, limit=30)
    result_refs = await repo.list_result_summaries(owner_id, chat_id, limit=20)
    return ResearchContext(
        messages=[{"role": m.role, "content": m.content} for m in messages if m.role != "tool"],
        result_refs=[{
            "result_set_id": str(r.result_set_id), "kind": r.kind,
            "label": r.label, "row_count": r.row_count,
            "definition": r.definition, "summary": r.summary,
        } for r in result_refs],
    )
```

Do not include `research_result_members.payload` in model context. Add a resolver that filters by expected `ResultKind`, ownership, and chat ID.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_context.py -v`

Expected: all tests pass.

```powershell
git add src/research/context.py tests/test_research_context.py
git commit -m "feat(research): resolve follow-up references within chats"
```

### Task 8: Add a provider boundary and OpenAI adapter

**Files:**
- Create: `src/research/llm.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/test_research_orchestrator.py`

- [ ] **Step 1: Add the dependency and configuration contract**

Run: `.\.venv\Scripts\python.exe -m pip install openai`

Then run: `.\.venv\Scripts\python.exe -m pip freeze | Select-String "^openai=="`

Add the printed compatible version as a lower bound in `pyproject.toml`, run `.\.venv\Scripts\python.exe -m pip install -e .`, and add:

```dotenv
OPENAI_API_KEY=
RESEARCH_MODEL=gpt-5-mini
RESEARCH_MAX_TOOL_CALLS=6
RESEARCH_MAX_ROWS=1000
RESEARCH_RUN_TIMEOUT_SECONDS=90
```

- [ ] **Step 2: Write failing adapter tests with a fake client**

Test one assistant text response, one function call with JSON arguments, provider timeout mapping, and malformed arguments. No test may contact the network.

- [ ] **Step 3: Implement the provider interface**

```python
@dataclass(frozen=True)
class ModelAction:
    kind: Literal["tool_call", "answer"]
    text: str = ""
    tool_name: str | None = None
    arguments: dict[str, object] | None = None


class FakeLLMProvider:
    def __init__(self, actions: list[ModelAction]):
        self.actions = deque(actions)

    async def next_action(self, context: ResearchContext, tools: list[dict]) -> ModelAction:
        return self.actions.popleft()
```

Implement `OpenAIResponsesProvider` behind the same interface. Its system instructions must require tool use for quantitative claims, preserve strict comparison words, cite result labels and snapshot times, state evidence floors, and avoid claims of coordination. API keys stay server-side.

- [ ] **Step 4: Run adapter tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_orchestrator.py -k provider -v`

Expected: all selected tests pass without network access.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml .env.example src/research/llm.py tests/test_research_orchestrator.py
git commit -m "feat(research): add bounded language-model provider interface"
```

### Task 9: Implement the bounded orchestration loop and panel policy

**Files:**
- Create: `src/research/orchestrator.py`
- Modify: `tests/test_research_orchestrator.py`

- [ ] **Step 1: Write failing orchestration tests**

Test: `find_wallets` followed by final answer; a follow-up overlap tool receiving the saved wallet result ID; same tool/same semantic scope updating one panel; different tool creating another panel; six-call ceiling; timeout; cancellation; invalid tool; and tool exception.

- [ ] **Step 2: Run and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_orchestrator.py -v`

Expected: missing `ResearchOrchestrator`.

- [ ] **Step 3: Implement deterministic panel keys**

```python
def panel_key(tool_name: str, args: BaseModel) -> str:
    stable = args.model_dump(mode="json", exclude={"limit"}, exclude_none=True)
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:12]
    family = {
        "find_wallets": "wallets",
        "market_participants": "wallets",
        "markets_traded": "markets",
        "open_position_overlap": "open-overlap",
        "outcome_consensus": "consensus",
        "same_outcome_history": "history-overlap",
    }[tool_name]
    return f"{family}:{digest}"
```

This makes pagination update the existing panel while a materially different scope creates a new panel.

- [ ] **Step 4: Implement the run loop**

The loop must:

1. Persist the user message and mark the run `running`.
2. Yield `run.started`.
3. Build compact context.
4. Ask the provider for the next action.
5. For a tool call, yield `tool.started`, validate and execute it, upsert its panel, then yield `result.created` and `panel.upserted`.
6. Continue with the new result summary in context.
7. For an answer, persist it, stream sentence-sized `assistant.delta` events, mark completed, and yield `run.completed`.
8. On known errors, persist a stable code and yield one `run.failed` event.

Enforce `RESEARCH_MAX_TOOL_CALLS`, `RESEARCH_MAX_ROWS`, and `RESEARCH_RUN_TIMEOUT_SECONDS` in code, not only in the prompt.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_orchestrator.py -v`

Expected: all tests pass.

```powershell
git add src/research/orchestrator.py tests/test_research_orchestrator.py
git commit -m "feat(research): orchestrate tools answers and panel updates"
```

### Task 10: Add authenticated research APIs and NDJSON streaming

**Files:**
- Create: `src/api/routers/research.py`
- Modify: `src/api/main.py`
- Test: `tests/test_research_api.py`

- [ ] **Step 1: Write failing API tests**

Cover:

- `GET/POST /api/v2/research/chats`
- `GET/PATCH/DELETE /api/v2/research/chats/{chat_id}`
- `GET /api/v2/research/chats/{chat_id}/messages`
- `GET /api/v2/research/chats/{chat_id}/panels`
- `PATCH /api/v2/research/panels/{panel_id}`
- `GET /api/v2/research/results/{result_set_id}?offset=0&limit=100`
- `POST /api/v2/research/chats/{chat_id}/runs`

Unauthenticated requests must return 403. Cross-owner IDs must return 404 to avoid revealing existence. The run response must have `application/x-ndjson` and end in exactly one terminal event.

- [ ] **Step 2: Run and verify 404 failures**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_api.py -v`

Expected: endpoint-not-found failures.

- [ ] **Step 3: Implement the router**

Use `APIRouter(prefix="/v2/research", tags=["research"])`, `Depends(get_current_user)` on every endpoint, UUID path types, title length 1–120, prompt length 1–4000, and member page limit 1–200.

Return the stream with:

```python
return StreamingResponse(
    (json.dumps(event.model_dump(mode="json")) + "\n" async for event in events),
    media_type="application/x-ndjson",
    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
)
```

Reject a second running/queued run for the same chat with HTTP 409 before streaming starts. Once streaming begins, encode all failures as `run.failed` because the status code can no longer change.

- [ ] **Step 4: Register and test**

Import `research` in `src/api/main.py` and add:

```python
app.include_router(research.router, prefix="/api")
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_api.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/api/routers/research.py src/api/main.py tests/test_research_api.py
git commit -m "feat(research): expose persistent streamed chat API"
```

---

## Milestone D — White IDE-style Research Hub UI

### Task 11: Add frontend test harness and shared types

**Files:**
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/types/research.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Install test dependencies**

Run from `frontend`:

```powershell
npm install --save-dev vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Add scripts `"test": "vitest run"` and `"test:watch": "vitest"`, plus Vitest configuration with `environment: "jsdom"` and setup file `src/test/setup.ts`.

- [ ] **Step 2: Define exact TypeScript contracts**

Mirror backend values with string unions:

```typescript
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type PanelState = "normal" | "minimized" | "maximized" | "closed";
export type PanelType = "wallet_table" | "market_table" | "overlap_table" | "consensus";

export interface ResearchChat { chat_id: string; title: string; is_archived: boolean; created_at: string; updated_at: string; }
export interface ResearchMessage { message_id: number; chat_id: string; run_id: string | null; role: "user" | "assistant" | "tool"; content: string; metadata: Record<string, unknown>; created_at: string; }
export interface PanelLayout { col_span: 4 | 6 | 8 | 12; min_height: number; order: number; }
export interface ResearchPanel { panel_id: string; chat_id: string; result_set_id: string | null; panel_type: PanelType; panel_key: string; title: string; state: PanelState; layout: PanelLayout; config: Record<string, unknown>; }
export interface StreamEvent { type: "run.started" | "tool.started" | "result.created" | "panel.upserted" | "assistant.delta" | "run.completed" | "run.failed"; run_id: string; data: Record<string, unknown>; }
```

- [ ] **Step 3: Run TypeScript validation and commit**

Run: `npm run build`

Expected: Next.js build succeeds.

```powershell
git add package.json package-lock.json src/test src/types/research.ts
git commit -m "test(research-ui): add UI harness and shared contracts"
```

### Task 12: Implement typed API and streaming client

**Files:**
- Create: `frontend/src/utils/researchApi.ts`
- Test: `frontend/src/utils/researchApi.test.ts`

- [ ] **Step 1: Write failing NDJSON parser tests**

Test events split across byte chunks, multiple events in one chunk, final lines without a trailing newline, malformed JSON, HTTP 401, and `AbortController` cancellation.

- [ ] **Step 2: Run and verify failure**

Run from `frontend`: `npm test -- src/utils/researchApi.test.ts`

Expected: module-not-found failure.

- [ ] **Step 3: Implement the API client**

Reuse `getAuthToken()` and the same `NEXT_PUBLIC_API_URL` default as `utils/api.ts`. Export CRUD functions plus:

```typescript
export async function streamResearchRun(
  chatId: string,
  prompt: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v2/research/chats/${chatId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getAuthToken()}` },
    body: JSON.stringify({ prompt }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`Research run failed: ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}
```

Do not retry a run POST automatically because a retry can duplicate a user message and result snapshot.

- [ ] **Step 4: Run tests and commit**

Run: `npm test -- src/utils/researchApi.test.ts`

Expected: all tests pass.

```powershell
git add src/utils/researchApi.ts src/utils/researchApi.test.ts
git commit -m "feat(research-ui): add typed streaming API client"
```

### Task 13: Build route shell, full-bleed content frame, and chat tabs

**Files:**
- Create: `frontend/src/components/ContentFrame.tsx`
- Create: `frontend/src/app/hub/page.tsx`
- Create: `frontend/src/app/hub/ResearchHub.tsx`
- Create: `frontend/src/components/research/ChatTabs.tsx`
- Create: `frontend/src/components/research/EmptyResearchState.tsx`
- Create: `frontend/src/components/research/__tests__/ChatTabs.test.tsx`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: Write failing tab tests**

Verify loading chats, selecting a tab, creating `New research`, inline rename, closing without deletion, reopening an archived chat, and horizontal overflow. One chat must always be selected when any open chats exist.

- [ ] **Step 2: Run and verify failure**

Run from `frontend`: `npm test -- src/components/research/__tests__/ChatTabs.test.tsx`

Expected: component-not-found failure.

- [ ] **Step 3: Implement route-aware content framing**

`ContentFrame.tsx` is a client component using `usePathname()`:

```tsx
export default function ContentFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const fullBleed = pathname.startsWith("/hub");
  return <main className={`flex-1 min-h-0 bg-background ${fullBleed ? "overflow-hidden p-0" : "overflow-auto p-5"}`}>{children}</main>;
}
```

Replace the current `<main>` wrapper in `layout.tsx` with `<ContentFrame>`. This preserves padding on every existing route.

- [ ] **Step 4: Implement tabs and empty state**

The tab bar sits inside `/hub`, directly above the chat/canvas split. Use semantic buttons, visible focus rings, a `+` button, and an overflow menu for archived chats. Examples in the empty state:

- “Find up to 100 wallets with more than 70% win rate in Sports → Cricket → T20, minimum 20 resolved positions.”
- “For those wallets, show markets where at least 25% currently hold a position.”
- “For this market, rank participating wallets by Cricket win rate and summarize their outcomes.”

- [ ] **Step 5: Add sidebar entry**

Add `Research Hub` with a terminal/panels icon under the main research navigation, path `/hub`. Do not rename or remove `/agents`.

- [ ] **Step 6: Run tests, build, and commit**

Run: `npm test -- src/components/research/__tests__/ChatTabs.test.tsx`

Run: `npm run build`

Expected: tests and build pass; existing routes retain padding.

```powershell
git add src/app/hub src/components/ContentFrame.tsx src/components/research/ChatTabs.tsx src/components/research/EmptyResearchState.tsx src/components/research/__tests__/ChatTabs.test.tsx src/app/layout.tsx src/components/Sidebar.tsx
git commit -m "feat(research-ui): add persistent chat workspace shell"
```

### Task 14: Build conversation rail and run-state reducer

**Files:**
- Create: `frontend/src/components/research/ChatRail.tsx`
- Create: `frontend/src/hooks/useResearchHub.ts`
- Create: `frontend/src/components/research/__tests__/ChatRail.test.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`

- [ ] **Step 1: Write failing interaction tests**

Verify Enter submits, Shift+Enter adds a newline, empty prompts are blocked, submit disables while a run is active, Stop aborts the stream, assistant deltas concatenate, tool status appears without becoming a permanent chat bubble, and failure restores the prompt for editing.

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/components/research/__tests__/ChatRail.test.tsx`

Expected: missing component/hook failure.

- [ ] **Step 3: Implement `useResearchHub`**

The hook owns chats, active chat ID, messages by chat, panels by chat, one active `AbortController`, and one reducer for stream events. On `panel.upserted`, replace by `panel_id` or append; on `assistant.delta`, append to one transient assistant message; on terminal events, clear busy state and refetch persisted messages/panels.

- [ ] **Step 4: Implement `ChatRail`**

Use a fixed header, independently scrollable message list, run-status row, and bottom composer. Show user prompts, concise assistant prose, tool progress, and result-set chips. Never render full result rows inside chat—the canvas owns tables.

- [ ] **Step 5: Run tests and commit**

Run: `npm test -- src/components/research/__tests__/ChatRail.test.tsx`

Expected: all tests pass.

```powershell
git add src/components/research/ChatRail.tsx src/hooks/useResearchHub.ts src/components/research/__tests__/ChatRail.test.tsx src/app/hub/ResearchHub.tsx
git commit -m "feat(research-ui): stream conversations into persistent chats"
```

### Task 15: Build the typed panel canvas

**Files:**
- Create: `frontend/src/components/research/PanelCanvas.tsx`
- Create: `frontend/src/components/research/PanelFrame.tsx`
- Create: `frontend/src/components/research/PanelRenderer.tsx`
- Create: `frontend/src/components/research/panels/WalletTablePanel.tsx`
- Create: `frontend/src/components/research/panels/MarketTablePanel.tsx`
- Create: `frontend/src/components/research/panels/OverlapPanel.tsx`
- Create: `frontend/src/components/research/panels/ConsensusPanel.tsx`
- Create: `frontend/src/components/research/__tests__/PanelCanvas.test.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`

- [ ] **Step 1: Write failing canvas tests**

Assert the exhaustive renderer maps every `PanelType`; same-key upserts do not duplicate; closed panels disappear but remain restorable; maximizing one hides other panel bodies; table panels request server pagination; and each panel displays snapshot time, row count, active scope, and evidence floor.

- [ ] **Step 2: Run and verify failure**

Run: `npm test -- src/components/research/__tests__/PanelCanvas.test.tsx`

Expected: missing component failure.

- [ ] **Step 3: Implement deterministic auto-layout**

Default sizes:

```typescript
export const PANEL_DEFAULTS: Record<PanelType, Pick<PanelLayout, "col_span" | "min_height">> = {
  wallet_table: { col_span: 12, min_height: 420 },
  market_table: { col_span: 12, min_height: 420 },
  overlap_table: { col_span: 8, min_height: 380 },
  consensus: { col_span: 4, min_height: 380 },
};
```

Render `grid-template-columns: repeat(12, minmax(0, 1fr))`; on widths below 1100 px, stack all panels to 12 columns. Order by `layout.order`, then creation time. The backend remains the source of truth for state and order.

- [ ] **Step 4: Implement panel contents**

- Wallet table: wallet/username, scoped win rate, W-L sample, scoped PnL, scoped volume, balance, open value, last active; click opens `/wallet/{address}` in a new browser tab.
- Market table: title, category path, distinct wallets, open/closed participation, outcomes, total value, coverage.
- Overlap: title, wallet count, exact coverage percentage, outcome breakdown, current value; visually mark 100% only when numerator equals the input result-set size.
- Consensus: outcome counts, wallet percentages, shares, and current value; never force non-binary outcomes into YES/NO.

Tables use server paging in 100-row pages and show an explicit empty state instead of an empty frame.

- [ ] **Step 5: Run tests and commit**

Run: `npm test -- src/components/research/__tests__/PanelCanvas.test.tsx`

Expected: all tests pass.

```powershell
git add src/components/research/PanelCanvas.tsx src/components/research/PanelFrame.tsx src/components/research/PanelRenderer.tsx src/components/research/panels src/components/research/__tests__/PanelCanvas.test.tsx src/app/hub/ResearchHub.tsx
git commit -m "feat(research-ui): render auto-arranged analytical panels"
```

### Task 16: Finish white-theme workspace styling and accessibility

**Files:**
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Modify: `frontend/src/components/research/ChatTabs.tsx`
- Modify: `frontend/src/components/research/ChatRail.tsx`
- Modify: `frontend/src/components/research/PanelFrame.tsx`

- [ ] **Step 1: Add the workspace CSS**

Use existing theme variables. Add `.research-workspace`, `.research-tabs`, `.research-split`, `.research-rail`, `.research-canvas`, `.research-panel-grid`, and `.research-panel`. The canvas uses `#F8FAFC` with a subtle 24 px dot grid; panels use white surfaces, slate borders, 8 px radius, and minimal shadow. Emerald is reserved for active tabs, successful values, and live status.

- [ ] **Step 2: Implement the splitter**

The separator has `role="separator"`, `aria-orientation="vertical"`, pointer drag, ArrowLeft/ArrowRight keyboard adjustment in 16 px increments, min 300 px, max 560 px, and local-storage key `pt-research-rail-width`.

- [ ] **Step 3: Complete accessibility states**

Use `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`, labelled panel regions, `aria-live="polite"` for tool/run status, visible focus styles, and icon-button labels. Respect the repository's reduced-motion rule.

- [ ] **Step 4: Verify UI quality**

Run: `npm test`

Run: `npm run lint`

Run: `npm run build`

Expected: all commands pass. Manually verify 1440×900, 1920×1080, and 1024×768. At 1024 px the chat/canvas remains split and panels stack; below 768 px the canvas becomes a second `Chat | Results` view switcher.

- [ ] **Step 5: Commit**

```powershell
git add src/app/globals.css src/app/hub/ResearchHub.tsx src/components/research
git commit -m "style(research-ui): finish white IDE workspace and accessibility"
```

---

## Milestone E — Reliability, security, and release verification

### Task 17: Add abuse limits, cancellation, and observability

**Files:**
- Modify: `src/api/routers/research.py`
- Modify: `src/research/orchestrator.py`
- Modify: `src/research/repository.py`
- Modify: `tests/test_research_api.py`

- [ ] **Step 1: Add failing limit tests**

Assert: 4000-character prompt maximum; one active run per chat; 10 run starts/minute/user; tool-call ceiling; 90-second timeout; output row ceiling; disconnect cancellation; stable error codes; and no provider exception or SQL text is returned to clients.

- [ ] **Step 2: Implement enforcement**

Use the existing SlowAPI limiter for run starts. Track status transitions transactionally. Wrap orchestration in `asyncio.timeout(90)`. Check `await request.is_disconnected()` between provider and tool steps. Log `run_id`, `chat_id`, hashed owner ID, tool name, duration, row count, and error code—never prompts, addresses in bulk, API keys, or raw provider payloads.

- [ ] **Step 3: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_api.py tests/test_research_orchestrator.py -v`

Expected: all tests pass.

```powershell
git add src/api/routers/research.py src/research/orchestrator.py src/research/repository.py tests/test_research_api.py
git commit -m "fix(research): enforce run limits isolation and safe failures"
```

### Task 18: Benchmark the key 100-wallet queries

**Files:**
- Create: `scripts/benchmark_research_queries.py`
- Create: `tests/test_research_query_plans.py`

- [ ] **Step 1: Add query-plan assertions**

For a representative 100-wallet result set, run `EXPLAIN (FORMAT JSON)` for open overlap and historical same-outcome queries. Assert plans do not perform one subplan per wallet and use the result-member and position indexes.

- [ ] **Step 2: Add the read-only benchmark command**

The script accepts `--result-set-id`, runs each query five times inside a read-only transaction, and reports median/p95 milliseconds and returned row count. It must not create chats or mutate result sets.

- [ ] **Step 3: Establish release budgets**

On the production-like database, require:

- wallet discovery p95 ≤ 750 ms;
- open overlap for 100 wallets p95 ≤ 1500 ms;
- market participants p95 ≤ 1000 ms;
- historical same-outcome for 100 wallets p95 ≤ 2500 ms.

If a budget fails, capture `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` in local scratch output, adjust only indexes or query shape used by this feature, and rerun until the budget passes.

- [ ] **Step 4: Run and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_research_query_plans.py -v`

Expected: all plan assertions pass.

```powershell
git add scripts/benchmark_research_queries.py tests/test_research_query_plans.py
git commit -m "perf(research): verify cross-wallet query plans and budgets"
```

### Task 19: Run end-to-end acceptance scenarios

**Files:**
- Create: `tests/test_research_e2e.py`
- Modify: `frontend/src/components/research/__tests__/PanelCanvas.test.tsx`

- [ ] **Step 1: Implement the backend acceptance test**

With `FakeLLMProvider`, execute this exact chain in one chat:

1. `Find wallets with more than 70% win rate in Sports, Cricket, T20.`
2. `Show the markets those wallets traded.`
3. `Show markets where all of them have an open position.`
4. `How many are on YES and how many are on NO?`

Assert each tool receives the prior owned result-set ID, four messages are persisted in order, expected result kinds exist, the overlap uses an exact 100% predicate, and the refinement updates the consensus panel without duplicating it.

- [ ] **Step 2: Implement the market-first acceptance test**

Execute: `For condition 0xabc, find wallets with more than 70% Cricket win rate, sort by win rate, and summarize their current outcomes.` Assert `market_participants` applies scoped category statistics—not global win rate—and creates wallet plus consensus views.

- [ ] **Step 3: Run all feature tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_research_migration.py tests/test_research_repository.py tests/test_research_analytics.py tests/test_research_tools.py tests/test_research_context.py tests/test_research_orchestrator.py tests/test_research_api.py tests/test_research_query_plans.py tests/test_research_e2e.py -v
```

Expected: all backend research tests pass.

Run from `frontend`:

```powershell
npm test
npm run lint
npm run build
```

Expected: all frontend tests, lint, and production build pass.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_research_e2e.py frontend/src/components/research/__tests__/PanelCanvas.test.tsx
git commit -m "test(research): cover complete conversational analysis workflows"
```

### Task 20: Update durable documentation and perform final smoke test

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/CORE_LOGIC.md`
- Modify: `docs/learner.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: Document the API**

Add every endpoint, request/response shape, pagination bound, auth requirement, NDJSON event type, terminal-event guarantee, and error code to `API_REFERENCE.md`.

- [ ] **Step 2: Document analytical definitions**

Add the strict win-rate comparison, default 20-resolved evidence floor, category scope, open-position definition, exact/all coverage rule, eligible-history rule, multi-outcome behavior, and no-fabrication boundary to `CORE_LOGIC.md`.

- [ ] **Step 3: Record implementation lessons**

In `learner.md`, capture why result sets are normalized instead of embedded in prompts, why tool SQL is set-based, why stream errors become events after headers are sent, and why result references are always scoped through chat ownership.

- [ ] **Step 4: Add the changelog entry**

Add a newest-first `2026-09-02` entry listing the Research Hub, persistence tables, analytical tools, streaming API, auto-arranged panels, safety boundaries, tests, and verified acceptance scenarios.

- [ ] **Step 5: Perform the manual smoke test**

Start API and UI in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm run dev
```

Verify: create two chat tabs; run different wallet searches; switch tabs without losing panels; refresh and restore state; follow up using “those wallets”; maximize/minimize/restore panels; cancel an active run; confirm another account cannot load the chat; and confirm no existing page layout changed.

- [ ] **Step 6: Commit documentation**

```powershell
git add docs/API_REFERENCE.md docs/CORE_LOGIC.md docs/learner.md docs/CHANGELOG.md
git commit -m "docs: document AI Research Hub behavior and APIs"
```

---

## 4. Release gates

The feature is ready only when all are true:

- Every quantitative assistant claim originates from a persisted result set.
- Every result panel shows scope, sample size/evidence floor, row count, and snapshot time.
- No model-produced SQL exists in logs, database calls, or persisted messages.
- Cross-user chat, result-set, run, and panel IDs return 404.
- A 100-wallet overlap query is set-based and meets the p95 budget.
- “All” is shown only for exact full-set coverage.
- Multi-outcome markets retain real labels.
- A refresh restores chats, messages, panels, and panel state.
- A failed or cancelled stream leaves the chat usable.
- Existing `/agents`, `/wallets`, `/feed`, `/tracker`, and wallet-detail routes build and render unchanged.
- Backend feature suite, frontend tests, lint, and production build all pass.

## 5. Recommended execution sequence

Execute Milestones A–E in order. Do not begin the language-model adapter until deterministic analytics can pass without a model. Do not begin panel polish until the persisted stream contract is stable. At the end of each milestone, deploy to a non-production environment and exercise its acceptance path before continuing.

Because the current worktree contains extensive unrelated user changes, create a dedicated worktree from the intended branch before Task 1. Do not reset, stash, delete, or reformat the existing worktree. Re-run `alembic heads` inside the new worktree before creating the migration; if the repository head has advanced beyond `v5w6x7y8z9`, rebase the new migration on that single current head before any database is upgraded.

## 6. Plan self-review

- **Coverage:** Persistent chat tabs, independent per-chat panels, split workspace, white theme, wallet discovery, traded markets, open-position intersection, outcome consensus, market-first queries, historical same-outcome analysis, streaming, follow-up references, security, performance, and documentation each map to explicit tasks.
- **Scope:** Trading, open-ended SQL, external research, collaboration, and arbitrary canvas editing are explicitly excluded.
- **Type consistency:** Backend result kinds, frontend panel types, run states, UUID identifiers, tool names, and stream event names remain consistent throughout.
- **Data integrity:** Category-scoped statistics come from `category_stats_v2`; current positions come from positive unresolved `wallet_positions_v2`; historical results honor `metrics_eligible`; the model cannot alter values.
- **Operational safety:** The plan uses a dedicated worktree and never modifies or discards the current dirty working tree.
