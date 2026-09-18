# Permanent Workspace Canvas Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Research Hub canvas a durable, workspace-owned surface that survives chat switching, while migrating existing chat-owned canvases without losing history, geometry, provenance, or owner isolation.

**Architecture:** Introduce an owner-scoped `research_workspaces` aggregate with exactly three transactionally seeded fixed tabs (`wallet_groups`, `market_groups`, `agents`). Chats become required workspace children and continue to own messages, runs, result snapshots, and assistant context. Panels move to workspace ownership while retaining nullable source-chat provenance and result-set references. The frontend keeps `activeWorkspaceId`/`panelsByWorkspace` separate from `activeChatId`/chat conversation state; changing chats therefore never remounts or reloads the canvas.

**Tech Stack:** PostgreSQL and Alembic, asyncpg, FastAPI, Pydantic 2, Next.js 16 App Router, React 19, TypeScript, Vitest, Testing Library, pytest, pytest-asyncio.

## Global Constraints

- This slice includes workspace persistence, fixed tabs, safe legacy migration, workspace-owned panels, and frontend workspace/chat state separation only.
- This slice does **not** implement groups, baskets, live terminal adapters, credential vaulting, wallet signing, typed chat workspace actions, or live execution.
- The workspace migration must use the verified current Alembic head `z9a0b1c2d3e4` as its `down_revision`.
- Existing chats, messages, runs, immutable result sets/members, panel state, floating geometry, z-index, and result provenance must survive migration.
- Every database read and mutation must be scoped through the authenticated owner; foreign IDs return the existing non-disclosing 404 behavior.
- Every workspace must have exactly one fixed tab of each allowed type: `wallet_groups`, `market_groups`, and `agents`. Tabs cannot be renamed or deleted through the API.
- Panels are unique by `(workspace_id, panel_key)` and analytical upserts must preserve the existing panel `layout` JSONB.
- A panel keeps `source_chat_id` as provenance but its ownership and lifecycle follow the workspace; deleting a chat must not delete the workspace canvas.
- The old chat panel endpoint remains as a compatibility read path and resolves the chat's workspace; new frontend reads use the workspace panel endpoint.
- Existing dry-run/refusal broker behavior remains unchanged; no credentials or signing material are added to this slice.
- Preserve the already-dirty worktree: touch only the files listed in each task and do not reset, stash, reformat, or commit unrelated user changes.
- Before editing frontend files, follow `frontend/AGENTS.md` and read the relevant Next.js 16 guide from `frontend/node_modules/next/dist/docs/`.
- Use the repository's existing style: asyncpg positional parameters, Pydantic `model_validate`, owner joins, optimistic frontend updates, and focused tests before broad verification.

## File Map

### Persistence and backend files

- **Create:** `alembic/versions/a0b1c2d3e4f5_add_research_workspaces.py` — create workspaces/tabs, backfill one workspace per legacy chat, migrate panel ownership, and add workspace indexes/constraints.
- **Modify:** `src/research/contracts.py` — add workspace and fixed-tab contracts; add workspace identity to chats and panels.
- **Modify:** `src/research/repository.py` — add transactional workspace CRUD/tab reads, workspace-scoped panel persistence, and compatibility chat-panel reads.
- **Modify:** `src/research/orchestrator.py` — resolve a run's workspace and upsert analytical panels into that workspace while retaining source-chat provenance.
- **Modify:** `src/api/routers/research.py` — add authenticated workspace CRUD/tabs/panels endpoints and workspace-aware chat creation.
- **Modify:** `tests/test_research_migration.py` — assert workspace schema, fixed-tab constraints, migrated panel columns, and required indexes.
- **Modify:** `tests/test_research_repository.py` — test workspace transactions, fixed tabs, owner isolation, panel persistence across chats, and chat deletion behavior.
- **Modify:** `tests/test_research_api.py` — test workspace routes, chat association, compatibility routes, panel ownership, and cross-owner 404s.

### Frontend files

- **Modify:** `frontend/src/types/research.ts` — mirror workspace, tab, chat, and panel JSON contracts.
- **Modify:** `frontend/src/utils/researchApi.ts` — add workspace requests and workspace-panel reads; keep chat-panel compatibility only where the hook needs it.
- **Modify:** `frontend/src/hooks/useResearchHub.ts` — split workspace state from chat state and route stream/panel mutations by workspace.
- **Modify:** `frontend/src/hooks/usePanelLayout.ts` — use workspace identity as the transient-layout reset key.
- **Modify:** `frontend/src/components/research/PanelCanvas.tsx` — accept `workspaceId`, never use chat identity as a persistence key.
- **Modify:** `frontend/src/app/hub/ResearchHub.tsx` — render the permanent canvas from the active workspace and keep the chat rail independent.
- **Create:** `frontend/src/components/research/WorkspaceSelector.tsx` — select/create/rename/delete the current named workspace through typed callbacks.
- **Create:** `frontend/src/components/research/CanvasTabs.tsx` — render the immutable three-tab canvas navigation.
- **Create:** `frontend/src/hooks/useResearchHub.test.tsx` — verify workspace/chat state separation and workspace-keyed panel mutations.
- **Modify:** `frontend/src/hooks/usePanelLayout.test.tsx` — rename the identity option and verify only workspace changes reset transient state.
- **Modify:** `frontend/src/components/research/__tests__/PanelCanvas.test.tsx` — update panel fixtures and assert workspace identity is used without chat remount behavior.
- **Create:** `frontend/src/components/research/__tests__/WorkspaceSelector.test.tsx` — test workspace selection and CRUD callback wiring.
- **Create:** `frontend/src/components/research/__tests__/CanvasTabs.test.tsx` — test exactly three fixed tabs and keyboard selection.

### Documentation files

- **Modify:** `docs/CORE_LOGIC.md` — replace chat-owned geometry language with workspace-owned canvas rules while preserving the mock-terminal boundary.
- **Modify:** `docs/ARCHITECTURE_AND_WORKERS.md` — document workspace/chat ownership and the permanent-canvas data flow.
- **Modify:** `docs/API_REFERENCE.md` — document workspace CRUD, fixed tabs, workspace panels, and `workspace_id` on chat creation/reads.

---

### Task 1: Add the workspace schema and idempotent legacy migration

**Files:**
- Create: `alembic/versions/a0b1c2d3e4f5_add_research_workspaces.py`
- Modify: `tests/test_research_migration.py`

**Interfaces:**
- Produces `research_workspaces(workspace_id, owner_id, name, created_at, updated_at)`.
- Produces `research_workspace_tabs(workspace_tab_id, workspace_id, tab_type, label, created_at)`.
- Adds non-null `research_chats.workspace_id` after backfill.
- Changes `research_panels` to `workspace_id` ownership plus nullable `source_chat_id` provenance.
- Later repository code relies on `UNIQUE(workspace_id, panel_key)` and the fixed-tab allow-list.

- [ ] **Step 1: Write migration assertions before changing the schema**

Extend `tests/test_research_migration.py` with explicit table/index and column checks:

```python
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
```

Add a fixed-tab constraint assertion by querying `pg_constraint`/`pg_get_constraintdef` and an integration invariant that a workspace row has the three allowed tab types exactly once. Run:

```bash
pytest tests/test_research_migration.py -q
```

Expected before the migration: failure because the new tables and columns do not exist.

- [ ] **Step 2: Create the migration from the verified Alembic head**

Create `a0b1c2d3e4f5_add_research_workspaces.py` with:

```python
revision = "a0b1c2d3e4f5"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None
```

Create the tables with these rules:

```sql
CREATE TABLE research_workspaces (
    workspace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_research_workspaces_owner_updated
    ON research_workspaces(owner_id, updated_at DESC);

CREATE TABLE research_workspace_tabs (
    workspace_tab_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES research_workspaces(workspace_id) ON DELETE CASCADE,
    tab_type VARCHAR(32) NOT NULL CHECK (
        tab_type IN ('wallet_groups', 'market_groups', 'agents')
    ),
    label VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, tab_type)
);
```

Add `workspace_id UUID` to `research_chats`, then backfill one deterministic workspace for every existing chat. Use `md5('research-workspace:' || chat_id::text)::uuid` as the workspace ID, copy the chat title into a bounded workspace name with a ` workspace` suffix, and use `INSERT ... ON CONFLICT (workspace_id) DO NOTHING` so a partially completed upgrade can be rerun. Seed the three tabs for every backfilled workspace with labels `Wallet Groups`, `Market Groups`, and `Agents`, also using `ON CONFLICT (workspace_id, tab_type) DO NOTHING`. Update each chat's `workspace_id`, then add the foreign key and `NOT NULL` constraint.

Do not add a unique constraint on `(owner_id, name)`; two legacy chats can have the same title and must still migrate independently.

- [ ] **Step 3: Migrate panel ownership without losing provenance**

In the same migration, add `research_panels.workspace_id`, rename `research_panels.chat_id` to `source_chat_id`, make `source_chat_id` nullable, and populate `workspace_id` by joining the source chat's `workspace_id`. Replace the source-chat foreign key with `ON DELETE SET NULL`, add `workspace_id REFERENCES research_workspaces(workspace_id) ON DELETE CASCADE`, and make `workspace_id NOT NULL` after the backfill.

Replace the old `(chat_id, panel_key)` uniqueness with:

```sql
ALTER TABLE research_panels
    ADD CONSTRAINT research_panels_workspace_panel_key_key
    UNIQUE (workspace_id, panel_key);

CREATE INDEX idx_research_panels_workspace
    ON research_panels(workspace_id, created_at ASC);

CREATE INDEX idx_research_panels_source_chat
    ON research_panels(source_chat_id)
    WHERE source_chat_id IS NOT NULL;
```

Leave `result_set_id` as `ON DELETE SET NULL`. This preserves a workspace panel shell and its geometry if its source chat/result snapshot is later removed. Do not rewrite `layout`, `state`, `config`, `created_at`, `updated_at`, or existing result IDs during the backfill.

- [ ] **Step 4: Make upgrade and downgrade behavior explicit and safe**

Use named constraints and guarded `DO $$ ... $$` blocks for `ADD CONSTRAINT` operations so a failed/retried migration does not create duplicate constraints. The upgrade must be safe when all backfill rows already exist. The downgrade must drop workspace panel indexes, restore the old chat-panel uniqueness and `chat_id` column only after copying `source_chat_id`, remove workspace foreign keys/tables, and raise `NotImplementedError` if restoring the old ownership would discard panels belonging to a workspace with multiple chats. The migration must never silently merge canvases.

Run:

```bash
alembic heads
alembic current
pytest tests/test_research_migration.py -q
```

Expected: one head `a0b1c2d3e4f5`, current database upgraded, migration assertions pass.

- [ ] **Step 5: Commit only the migration and migration tests**

```bash
git add alembic/versions/a0b1c2d3e4f5_add_research_workspaces.py tests/test_research_migration.py
git commit -m "feat(research): add permanent workspace schema"
```

---

### Task 2: Add workspace contracts and owner-scoped repository persistence

**Files:**
- Modify: `src/research/contracts.py`
- Modify: `src/research/repository.py`
- Modify: `tests/test_research_repository.py`

**Interfaces:**
- `ResearchWorkspace(workspace_id: UUID, name: str, created_at: datetime, updated_at: datetime)`.
- `WorkspaceTabType` values are exactly `wallet_groups`, `market_groups`, `agents`.
- `ResearchWorkspaceTab(workspace_tab_id, workspace_id, tab_type, label, created_at)`.
- `ResearchChat` gains required `workspace_id: UUID`.
- `ResearchPanel` replaces `chat_id` with `workspace_id` and `source_chat_id: UUID | None`.
- Repository methods:
  - `create_workspace(owner_id, name) -> ResearchWorkspace`
  - `list_workspaces(owner_id, limit=50) -> list[ResearchWorkspace]`
  - `get_workspace(owner_id, workspace_id) -> ResearchWorkspace | None`
  - `rename_workspace(owner_id, workspace_id, name) -> ResearchWorkspace | None`
  - `delete_workspace(owner_id, workspace_id) -> bool`
  - `list_workspace_tabs(owner_id, workspace_id) -> list[ResearchWorkspaceTab] | None`
  - `create_chat(owner_id, title="New research", workspace_id=None) -> ResearchChat`
  - `list_workspace_panels(owner_id, workspace_id) -> list[ResearchPanel] | None`
  - `list_panels(owner_id, chat_id) -> list[ResearchPanel]` as a compatibility resolver.
  - `upsert_panel(owner_id, workspace_id, source_chat_id, panel_key, panel_type, title, result_set_id, layout, config=None) -> ResearchPanel | None`.
  - `update_panel(owner_id, panel_id, mutation) -> ResearchPanel | None` remains the mutation seam.

- [ ] **Step 1: Add failing contract and repository tests**

Add tests with concrete expectations:

```python
@pytest.mark.asyncio
async def test_workspace_creation_seeds_exactly_three_tabs(test_pool, two_users):
    repo = ResearchRepository(test_pool)
    workspace = await repo.create_workspace(two_users.first, "Cricket")
    tabs = await repo.list_workspace_tabs(two_users.first, workspace.workspace_id)
    assert tabs is not None
    assert [tab.tab_type.value for tab in tabs] == [
        "wallet_groups", "market_groups", "agents",
    ]
    assert len(tabs) == 3
    assert await repo.list_workspace_tabs(two_users.second, workspace.workspace_id) is None
```

Add a same-workspace cross-chat panel test: create two chats in one workspace, upsert the same `panel_key` from both chats, assert one `panel_id`, `workspace_id` is stable, `source_chat_id` changes to the latest run, and a `floating` mutation survives the second analytical upsert. Add a cross-owner `get_workspace`, `list_workspace_tabs`, `list_workspace_panels`, `rename_workspace`, and `update_panel` assertion returning `None`/empty as appropriate.

Add a delete-chat preservation test: create a panel, delete the source chat through the owner-scoped SQL/API seam, then assert `list_workspace_panels` still returns the panel with `source_chat_id is None`.

Run:

```bash
pytest tests/test_research_repository.py -q
```

Expected: failures for missing contracts and methods.

- [ ] **Step 2: Add the Pydantic workspace and provenance models**

In `src/research/contracts.py`, add `WorkspaceTabType(StrEnum)` and the two workspace models near `ResearchChat`. Add `workspace_id` to `ResearchChat`. Define the panel contract as:

```python
class ResearchPanel(BaseModel):
    panel_id: UUID
    workspace_id: UUID
    source_chat_id: UUID | None = None
    result_set_id: UUID | None = None
    panel_type: str
    panel_key: str
    title: str
    state: PanelState = PanelState.NORMAL
    layout: PanelLayout
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
```

Keep `ResearchMessage`, `ResearchRun`, and `ResultSetSummary` chat-scoped. Update `_row_model` JSON decoding only as needed; workspace rows contain no JSON fields.

- [ ] **Step 3: Implement transactional workspace creation and owner checks**

Implement `create_workspace` using one acquired connection and one transaction. Insert the workspace, then insert all three fixed tabs from one constant ordered tuple. Return the inserted workspace only after all tab inserts succeed. Validate `name` with the same trimmed, length-bounded rules as `ChatCreate` and reject blank names with `ValueError` before SQL.

Implement `list_workspaces`, `get_workspace`, and `rename_workspace` with `owner_id` predicates. Implement `list_workspace_tabs` with a workspace-owner join and return `None` for a foreign workspace so the API can produce 404. Order tabs as `wallet_groups`, `market_groups`, `agents` using `ORDER BY CASE` rather than database insertion order.

Implement `delete_workspace` as an owner-scoped transaction that first checks for attached chats. Return `False` without deleting when chats exist; delete only an owned empty workspace. This preserves chat history and makes destructive deletion explicit.

- [ ] **Step 4: Refactor chat and panel repository methods to workspace ownership**

Make every chat `SELECT`/`RETURNING` include `workspace_id`. For `create_chat`, accept an optional workspace ID for old callers. If it is provided, require an owned workspace. If it is omitted, select the owner's oldest workspace; if none exists, create the default `New research` workspace transactionally and seed its tabs before inserting the chat. This keeps existing callers working while making every persisted chat workspace-scoped.

Change `upsert_panel` to accept `workspace_id` and `source_chat_id`. Its SQL must verify both IDs belong to the same owner and workspace, then use `ON CONFLICT (workspace_id, panel_key) DO UPDATE`. The update may change `source_chat_id`, `result_set_id`, `panel_type`, `title`, `config`, and reopen a closed panel, but must not assign `layout = EXCLUDED.layout`. Return `workspace_id` and `source_chat_id` in every panel row.

Change `update_panel` ownership resolution to join `research_panels.workspace_id` to `research_workspaces.owner_id`. All stacking queries, rank compaction, and `MAX(z_index)` queries must filter by `workspace_id`, not `source_chat_id`. Keep the transaction and `FOR UPDATE` lock so concurrent bring-to-front mutations remain serialized. `list_workspace_panels` joins workspace ownership and returns `None` for a foreign workspace; `list_panels(owner_id, chat_id)` resolves the chat's workspace and delegates to it, preserving the old route without making chat the owner.

- [ ] **Step 5: Run repository tests and inspect the SQL contract**

Run:

```bash
pytest tests/test_research_repository.py -q
python -m compileall src/research/contracts.py src/research/repository.py
```

Expected: all repository tests, including existing geometry/z-index tests, pass. If a test still constructs a chat/panel model without `workspace_id`, update that fixture to create a workspace through the repository rather than weakening the contract.

- [ ] **Step 6: Commit contracts and repository changes**

```bash
git add src/research/contracts.py src/research/repository.py tests/test_research_repository.py
git commit -m "feat(research): persist workspace-owned chats and panels"
```

---

### Task 3: Add authenticated workspace APIs and preserve chat compatibility

**Files:**
- Modify: `src/api/routers/research.py`
- Modify: `tests/test_research_api.py`

**Interfaces:**
- `POST /api/v2/research/workspaces` with `{ "name": string }` returns a workspace.
- `GET /api/v2/research/workspaces?limit=50` returns `{ "workspaces": [...] }`.
- `GET /api/v2/research/workspaces/{workspace_id}` returns a workspace.
- `PATCH /api/v2/research/workspaces/{workspace_id}` with `{ "name": string }` returns a workspace.
- `DELETE /api/v2/research/workspaces/{workspace_id}` returns `{ "deleted": workspace_id }` only for an owned empty workspace; return 409 when chats remain.
- `GET /api/v2/research/workspaces/{workspace_id}/tabs` returns `{ "tabs": [...] }`.
- `GET /api/v2/research/workspaces/{workspace_id}/panels` returns `{ "panels": [...] }`.
- `POST /api/v2/research/chats` accepts optional `{ "workspace_id": string, "title": string }`; response includes `workspace_id`.
- `GET /api/v2/research/chats/{chat_id}/panels` remains available and returns the chat's workspace panels.
- `PATCH /api/v2/research/panels/{panel_id}` remains available and mutates by workspace ownership.

- [ ] **Step 1: Add failing endpoint tests**

Add tests covering the full owner boundary:

```python
@pytest.mark.asyncio
async def test_workspace_crud_and_fixed_tabs(api_pool, user_a):
    async with _client(user_a["token"]) as client:
        created = await client.post(
            "/api/v2/research/workspaces", json={"name": "Cricket"}
        )
        assert created.status_code == 200
        workspace_id = created.json()["workspace_id"]
        tabs = await client.get(f"/api/v2/research/workspaces/{workspace_id}/tabs")
        assert [tab["tab_type"] for tab in tabs.json()["tabs"]] == [
            "wallet_groups", "market_groups", "agents",
        ]
        renamed = await client.patch(
            f"/api/v2/research/workspaces/{workspace_id}",
            json={"name": "Cricket live"},
        )
        assert renamed.json()["name"] == "Cricket live"
```

Add tests that create a chat with the workspace ID, assert the chat response carries it, list workspace panels, and verify the old chat panels route returns the same workspace-owned panel. Add a second user assertion that every workspace, tab, panel read, patch, and delete by the foreign user returns 404. Add a delete test asserting a workspace with a chat returns 409 and an empty workspace can be deleted. Add an unauthenticated workspace request assertion returning 401.

Run:

```bash
pytest tests/test_research_api.py -q
```

Expected before implementation: 404s or response-shape failures.

- [ ] **Step 2: Add request models and workspace routes**

Add `WorkspaceCreate` and `WorkspacePatch` models with `name: str = Field(min_length=1, max_length=120)`. Strip names in the route/service boundary and return 422 for blank-after-trim input. Add the workspace routes before the dynamic `/chats/{chat_id}` routes to avoid path ambiguity.

Each route must call the repository with `_uid(user)`. Translate `None` to `HTTPException(status_code=404, detail="workspace not found")`. Return only Pydantic `model_dump(mode="json")` data; never expose owner IDs or database internals.

For delete, translate repository `False` due to attached chats into `409` with `detail="workspace has chats"`; translate a missing/foreign workspace into 404. Do not cascade-delete a workspace through the route when it still contains chats.

- [ ] **Step 3: Make chat creation explicitly workspace-aware**

Update `ChatCreate` with `workspace_id: UUID | None = None`. Pass it to `create_chat`. If it is absent, repository default-workspace behavior applies. If it is foreign, return 404 rather than creating a chat in another user's workspace. Existing list/get/patch/delete chat responses now include `workspace_id` automatically through the updated contract.

Keep all run, message, result, and position routes chat-scoped. Before starting a run, the existing `get_chat` ownership check still verifies the chat; the orchestrator will resolve its workspace in Task 4.

- [ ] **Step 4: Add workspace panel listing and retain compatibility routes**

Add `GET /workspaces/{workspace_id}/panels` with the same owner-scoped 404 behavior as tabs. Keep `GET /chats/{chat_id}/panels`, but implement it through the repository compatibility method. Keep `PATCH /panels/{panel_id}` unchanged at the public path so existing clients and the current floating canvas continue working during the frontend cutover.

- [ ] **Step 5: Run focused API tests and commit**

```bash
pytest tests/test_research_api.py -q

git add src/api/routers/research.py tests/test_research_api.py
git commit -m "feat(research): expose workspace and fixed-tab APIs"
```

---

### Task 4: Route orchestration panels to the workspace while retaining chat provenance

**Files:**
- Modify: `src/research/orchestrator.py`
- Modify: `tests/test_research_api.py`
- Modify: `tests/test_research_repository.py`

**Interfaces:**
- `ResearchRepository.get_chat(owner_id, chat_id)` exposes `workspace_id`.
- `ResearchOrchestrator._upsert_panel(owner_id, workspace_id, source_chat_id, tool_name, args, panel_type, result_set)` writes the workspace-owned panel.
- `panel.upserted` stream payload contains `workspace_id` and `source_chat_id`; it remains safe for a client to merge by `panel_id`.

- [ ] **Step 1: Add a failing run test for two chats sharing one workspace**

Using the existing `FakeLLMProvider`, create one workspace and two chats in it. Run the same tool family from each chat with different source result sets. Assert the workspace panel list contains one panel for the stable `panel_key`, its `workspace_id` is unchanged, `source_chat_id` equals the latest chat, and a previously persisted floating rectangle remains unchanged. Assert both chats still retain their independent result-set summaries and messages.

Run:

```bash
pytest tests/test_research_api.py::test_workspace_canvas_is_shared_across_chats -q
```

Expected: failure because the orchestrator currently passes `chat_id` to panel upsert and the API has no workspace panel read path.

- [ ] **Step 2: Resolve workspace identity once at run start**

In `run_stream`, fetch the owned chat before creating the run or use the returned run/chat contract to obtain `workspace_id`. Store it in a local `workspace_id` and include it in `run.started` data only if the event remains backward-compatible. Continue using `chat_id` for `build_context`, result-set writes, tool reference resolution, messages, and run status.

- [ ] **Step 3: Change deterministic panel upsert arguments**

Update `_upsert_panel` to list existing panels by workspace, preserve the matching panel's existing `layout.order`, and call:

```python
await self.repo.upsert_panel(
    owner_id,
    workspace_id,
    chat_id,
    key,
    panel_type.value,
    result_set.label,
    result_set.result_set_id,
    layout,
    config,
)
```

The result set remains chat-provenance data. Do not copy it into a workspace result table or make workspace panels own result snapshots. Update logging only to add workspace hash/ID where safe; never log prompt contents, wallet addresses, credentials, or provider payloads.

- [ ] **Step 4: Verify stream and persistence behavior**

Run:

```bash
pytest tests/test_research_api.py::test_run_with_tool_creates_panel_and_pages tests/test_research_api.py::test_workspace_canvas_is_shared_across_chats -q
pytest tests/test_research_repository.py -q
```

Expected: all pass, including analytical upserts preserving geometry and chat result provenance.

- [ ] **Step 5: Commit orchestration changes**

```bash
git add src/research/orchestrator.py tests/test_research_api.py tests/test_research_repository.py
git commit -m "feat(research): upsert analysis panels into workspaces"
```

---

### Task 5: Split frontend contracts and API helpers by workspace versus chat

**Files:**
- Modify: `frontend/src/types/research.ts`
- Modify: `frontend/src/utils/researchApi.ts`
- Modify: `frontend/src/hooks/usePanelLayout.ts`
- Modify: `frontend/src/hooks/usePanelLayout.test.tsx`

**Interfaces:**
- `ResearchWorkspace { workspace_id, name, created_at, updated_at }`.
- `WorkspaceTabType = "wallet_groups" | "market_groups" | "agents"`.
- `ResearchWorkspaceTab { workspace_tab_id, workspace_id, tab_type, label, created_at }`.
- `ResearchChat` gains `workspace_id`.
- `ResearchPanel` contains `workspace_id` and `source_chat_id: string | null`, not `chat_id`.
- API helpers:
  - `listWorkspaces() -> Promise<{ workspaces: ResearchWorkspace[] }>`
  - `createWorkspace(name?) -> Promise<ResearchWorkspace>`
  - `patchWorkspace(workspaceId, patch) -> Promise<ResearchWorkspace>`
  - `deleteWorkspace(workspaceId) -> Promise<{ deleted: string }>`
  - `listWorkspaceTabs(workspaceId) -> Promise<{ tabs: ResearchWorkspaceTab[] }>`
  - `listWorkspacePanels(workspaceId) -> Promise<{ panels: ResearchPanel[] }>`
  - `createChat(title?, workspaceId?) -> Promise<ResearchChat>`
- `UsePanelLayoutOptions` uses `workspaceId: string` instead of `chatId`.

- [ ] **Step 1: Add failing TypeScript/test fixtures**

Update one existing panel fixture and one hook test to use `workspace_id`/`source_chat_id`, then add this contract-level expectation to `frontend/src/hooks/usePanelLayout.test.tsx`:

```tsx
it("resets transient layout state when workspace identity changes", async () => {
  const panels = [mockPanel("p1")];
  const onSave = vi.fn().mockResolvedValue(panels[0]);
  const { result, rerender } = renderHook(
    ({ workspaceId }) => usePanelLayout({ workspaceId, panels, stageWidth: 1200, onSaveMutation: onSave }),
    { initialProps: { workspaceId: "workspace-1" } },
  );
  act(() => result.current.bringToFront("p1"));
  expect(result.current.activePanelId).toBe("p1");
  rerender({ workspaceId: "workspace-2" });
  expect(result.current.activePanelId).toBeNull();
});
```

Run:

```bash
cd frontend && npm test -- --run src/hooks/usePanelLayout.test.tsx
```

Expected: TypeScript/test failure until the option and fixture are changed.

- [ ] **Step 2: Update shared TypeScript contracts**

Add the workspace interfaces and update `ResearchChat`/`ResearchPanel` exactly as listed above. Keep `ResultSetSummary.chat_id` because immutable result sets remain chat-owned. Do not add group, basket, wallet credential, or live terminal types in this slice.

- [ ] **Step 3: Add workspace API helpers and update chat creation**

Implement helpers using the existing `request` function and URL conventions. `createChat` must omit `workspace_id` when it is `undefined` so the backend compatibility default remains available. Add `listWorkspacePanels`; retain `listPanels(chatId)` only for compatibility tests or callers not yet migrated.

- [ ] **Step 4: Change the layout identity without changing interaction behavior**

Rename the hook option and its internal render-time reset state from `chatId`/`prevChatId` to `workspaceId`/`prevWorkspaceId`. Keep all geometry calculations, queue serialization, optimistic saves, z-index compaction, retry behavior, mobile fallback, and keyboard interaction unchanged. Update comments from “chat” to “workspace” where they describe persistence ownership.

- [ ] **Step 5: Run focused frontend tests and type/lint checks**

```bash
cd frontend && npm test -- --run src/hooks/usePanelLayout.test.tsx src/components/research/__tests__/PanelCanvas.test.tsx
npm run lint
```

Expected: the hook tests pass; PanelCanvas tests may still need the component prop update in Task 6, but no unrelated lint errors may be introduced.

- [ ] **Step 6: Commit frontend contracts/API/layout identity**

```bash
git add frontend/src/types/research.ts frontend/src/utils/researchApi.ts frontend/src/hooks/usePanelLayout.ts frontend/src/hooks/usePanelLayout.test.tsx
git commit -m "refactor(research): separate workspace and chat frontend contracts"
```

---

### Task 6: Make `useResearchHub` maintain independent workspace and chat state

**Files:**
- Modify: `frontend/src/hooks/useResearchHub.ts`
- Create: `frontend/src/hooks/useResearchHub.test.tsx`

**Interfaces:**
- Returned state includes `workspaces`, `activeWorkspaceId`, `tabsByWorkspace`, `panelsByWorkspace`, and workspace helpers.
- Returned chat state remains `chats`, `archivedChats`, `activeChatId`, `messagesByChat`, `resultsByChat`, `positionsByChat`, and run state maps.
- `selectChat(chatId)` changes only chat state and refreshes messages/results/positions; it does not call a panel endpoint.
- `selectWorkspace(workspaceId)` changes workspace state and refreshes workspace tabs/panels; it does not alter `activeChatId` unless the current chat belongs to a different workspace, in which case it selects the first open chat in the selected workspace.
- `mutatePanel(workspaceId, panelId, mutation)` optimistically updates `panelsByWorkspace[workspaceId]` and calls `patchPanel`.
- `setPanelState(workspaceId, panelId, state)` delegates to `mutatePanel`.

- [ ] **Step 1: Add hook tests with mocked API helpers**

Create `useResearchHub.test.tsx` and mock `@/utils/researchApi` functions. Test these concrete behaviors:

```tsx
it("keeps the workspace canvas when selecting another chat", async () => {
  // listWorkspaces -> workspace-1; listChats -> chat-a and chat-b in workspace-1
  // listWorkspacePanels -> panel-1; listMessages/listResults/listPositions vary by chat
  const { result } = renderHook(() => useResearchHub());
  await waitFor(() => expect(result.current.activeChatId).toBe("chat-a"));
  expect(result.current.panelsByWorkspace["workspace-1"]).toHaveLength(1);
  await act(async () => result.current.selectChat("chat-b"));
  expect(result.current.activeChatId).toBe("chat-b");
  expect(result.current.panelsByWorkspace["workspace-1"]).toHaveLength(1);
  expect(mockedListWorkspacePanels).toHaveBeenCalledTimes(1);
});
```

Also test that a streamed `panel.upserted` event is stored under `panel.workspace_id`, not the active chat key, and that a workspace mutation rollback restores only that workspace's prior panel list. Run:

```bash
cd frontend && npm test -- --run src/hooks/useResearchHub.test.tsx
```

Expected: failure because the hook currently has only `panelsByChat` and has no workspace API calls.

- [ ] **Step 2: Load workspaces before selecting chats**

Add `workspaces` and `activeWorkspaceId` state plus refs. Initial loading must fetch workspaces and chats. If no workspaces exist, create one named `Research`; do not create a separate workspace for every new chat after the migration. Select the workspace associated with the chosen active chat, then load that workspace's tabs and panels once.

When `createChat` has an active workspace, pass its ID. When there is no active workspace, create/select a workspace first, then create the chat. Preserve the existing rule that empty chats are deleted rather than archived; deleting a chat must not clear workspace panels.

- [ ] **Step 3: Separate refresh functions and event reducers**

Replace `refreshChatData`'s panel request with a `refreshWorkspaceData(workspaceId)` function that fetches `listWorkspaceTabs` and `listWorkspacePanels` and stores them under workspace keys. Keep messages/results/positions fetching in `refreshChatData(chatId)`. The chat refresh may still list results and research positions; those remain chat-scoped by design.

In `applyEvent`, read `panel.workspace_id`. If absent for a legacy stream event, use the workspace ID from the chat lookup, but never use the chat ID as a panel map key. Result events continue to update `resultsByChat[chatId]`.

- [ ] **Step 4: Update panel mutations and workspace switching**

Change `mutatePanel` to accept `workspaceId`. Snapshot `panelsByWorkspace[workspaceId]`, apply the optimistic state/floating update there, call `patchPanel`, and replace/rollback only that workspace's list. `setPanelState` takes the same workspace ID. Keep the existing serialized layout queue in `usePanelLayout`; the hook now passes workspace-scoped callbacks.

Implement `selectWorkspace` with owner-safe API results. A workspace switch intentionally changes the canvas. Select the first open chat whose `workspace_id` matches the workspace; if none exists, create a new chat in that workspace. Do not alter messages or run state maps for other chats.

- [ ] **Step 5: Run hook tests and the current full frontend suite**

```bash
cd frontend && npm test -- --run src/hooks/useResearchHub.test.tsx src/hooks/usePanelLayout.test.tsx
npm test
```

Expected: focused tests and the existing suite pass after all fixtures use the new panel shape. No test should assert that switching chats reloads panels.

- [ ] **Step 6: Commit the state split**

```bash
git add frontend/src/hooks/useResearchHub.ts frontend/src/hooks/useResearchHub.test.tsx
 git commit -m "feat(research): keep canvas state independent from chats"
```

---

### Task 7: Add workspace selector and fixed canvas tabs

**Files:**
- Create: `frontend/src/components/research/WorkspaceSelector.tsx`
- Create: `frontend/src/components/research/CanvasTabs.tsx`
- Create: `frontend/src/components/research/__tests__/WorkspaceSelector.test.tsx`
- Create: `frontend/src/components/research/__tests__/CanvasTabs.test.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- `WorkspaceSelectorProps` receives `workspaces`, `activeWorkspaceId`, `onSelect`, `onCreate`, `onRename`, and `onDelete` callbacks.
- `CanvasTabsProps` receives `tabs`, `activeTabType`, and `onSelect`; it renders the three fixed types in order and disables no tab merely because its future resource list is empty.
- The current visual chat selector remains a chat selector; its aria label and panel controls must not claim to be the workspace/canvas selector.

- [ ] **Step 1: Write component tests first**

`WorkspaceSelector.test.tsx` must render two workspaces, select the second, create a workspace, rename through the callback, and request deletion through an accessible button. `CanvasTabs.test.tsx` must render tabs in this exact order and assert:

```tsx
expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
  "Wallet Groups", "Market Groups", "Agents",
]);
```

It must also assert `aria-selected`, keyboard activation with Enter/Space, and that no fourth custom tab can be rendered from a malformed server response. Run:

```bash
cd frontend && npm test -- --run src/components/research/__tests__/WorkspaceSelector.test.tsx src/components/research/__tests__/CanvasTabs.test.tsx
```

Expected: module-not-found failures until the components exist.

- [ ] **Step 2: Implement the workspace selector**

Use a native `select` or a compact popover with a visible current workspace name. Wire create to a minimal prompt-free default (`New workspace`) through the hook callback; wire rename/delete callbacks without embedding fetch logic in the component. Disable delete when the active workspace has chats if the hook exposes that status, and provide an accessible explanation. Do not display owner IDs or any credential/status fields in this foundation slice.

- [ ] **Step 3: Implement fixed canvas tabs**

Filter server tabs to the allow-listed `WorkspaceTabType` union and render labels from a local constant so a malformed label cannot create arbitrary top-level navigation. Keep the component present even when `tabs` is temporarily loading; use a stable loading/disabled state rather than remounting the canvas. Tab selection is presentation state only in this slice; it must not change panel ownership.

- [ ] **Step 4: Integrate selectors without making chat own the canvas**

In `ResearchHub.tsx`, render the workspace selector and canvas tabs above the canvas while keeping `ChatTabs` for conversations. Use `hub.activeWorkspaceId` and `hub.panelsByWorkspace[activeWorkspaceId]`. Keep the active chat's messages, results, run state, and research positions sourced from `activeChatId`.

When switching chats, do not change the canvas container key. When switching workspaces, use `key={activeWorkspaceId}` only if a workspace-level remount is required to clear transient layout state; never key it by `activeChatId`. Preserve the existing empty state for “no chat” while still allowing the selected workspace canvas to remain visible if it has no active conversation.

- [ ] **Step 5: Add focused styling and responsive behavior**

Add only the selector/tab styles needed to match existing research tabs and preserve narrow-layout overflow behavior. Use `overflow-x-auto`, visible focus styles, and `aria` state. Do not change trading-terminal semantics or relabel the mock panel as live data.

- [ ] **Step 6: Run component tests and commit**

```bash
cd frontend && npm test -- --run src/components/research/__tests__/WorkspaceSelector.test.tsx src/components/research/__tests__/CanvasTabs.test.tsx src/components/research/__tests__/PanelCanvas.test.tsx
npm run lint

git add frontend/src/components/research/WorkspaceSelector.tsx frontend/src/components/research/CanvasTabs.tsx frontend/src/components/research/__tests__/WorkspaceSelector.test.tsx frontend/src/components/research/__tests__/CanvasTabs.test.tsx frontend/src/app/hub/ResearchHub.tsx frontend/src/app/globals.css
git commit -m "feat(research): add workspace selector and fixed canvas tabs"
```

---

### Task 8: Convert PanelCanvas to workspace identity and prove chat switching is non-destructive

**Files:**
- Modify: `frontend/src/components/research/PanelCanvas.tsx`
- Modify: `frontend/src/components/research/__tests__/PanelCanvas.test.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Create or modify: `frontend/src/components/research/__tests__/PanelInteraction.test.tsx`

**Interfaces:**
- `PanelCanvasProps` uses `workspaceId: string | null` rather than `chatId`.
- `usePanelLayout({ workspaceId, panels, stageWidth, onSaveMutation })` is the only persistence identity passed to the canvas.
- `PanelCanvas` continues to preserve movement, resize, z-index, minimize, maximize, closed-panel restore, reset, save-error, and stacked mobile behavior.

- [ ] **Step 1: Update failing canvas fixtures and assertions**

Replace `chat_id` panel fixture fields with `workspace_id` and `source_chat_id`. Replace `chatId="chat-1"` props with `workspaceId="workspace-1"`. Add a rerender test that changes a parent chat value while passing the same workspace ID and the same panel list; assert the panel remains mounted and its active/transient geometry is not reset. Add a separate workspace-ID rerender test that asserts transient active state is reset.

Run:

```bash
cd frontend && npm test -- --run src/components/research/__tests__/PanelCanvas.test.tsx src/components/research/__tests__/PanelInteraction.test.tsx
```

Expected: type/prop failures until the component is changed.

- [ ] **Step 2: Change PanelCanvas props and layout invocation**

Replace `chatId?: string | null` with `workspaceId?: string | null`. Pass `workspaceId ?? "default"` to `usePanelLayout`. Do not add chat props or read chat IDs from panel records. Keep the default callback behavior for state-only tests and all existing renderer logic unchanged.

- [ ] **Step 3: Integrate workspace callbacks in ResearchHub**

Pass `workspaceId={hub.activeWorkspaceId}` and `panels={allPanels}`. Call `hub.setPanelState(activeWorkspaceId, panelId, state)` and `hub.mutatePanel(activeWorkspaceId, panelId, mutation)`. Guard callbacks when no workspace is selected; a canvas without a workspace is read-only/empty rather than sending a malformed request.

Remove the render-time `prevChatId` state that clears `selectedPosition` on chat changes, or replace it with a workspace-aware reset only if the selected research position is deliberately workspace-scoped. The first slice should preserve chat-specific research positions, so clearing the selected research position on chat change is allowed, but it must not affect panel state or canvas identity.

- [ ] **Step 4: Verify all interaction behavior remains intact**

Run:

```bash
cd frontend && npm test -- --run src/components/research/__tests__/PanelCanvas.test.tsx src/components/research/__tests__/PanelInteraction.test.tsx src/hooks/usePanelLayout.test.tsx
npm run lint
```

Expected: all existing geometry and interaction tests pass, including narrow viewport stacked layout and save retry. No test may find a `key={activeChatId}` on the canvas subtree.

- [ ] **Step 5: Commit the canvas cutover**

```bash
git add frontend/src/components/research/PanelCanvas.tsx frontend/src/components/research/__tests__/PanelCanvas.test.tsx frontend/src/components/research/__tests__/PanelInteraction.test.tsx frontend/src/app/hub/ResearchHub.tsx
git commit -m "feat(research): make canvas persistence workspace-owned"
```

---

### Task 9: Update ownership documentation and run the full verification matrix

**Files:**
- Modify: `docs/CORE_LOGIC.md`
- Modify: `docs/ARCHITECTURE_AND_WORKERS.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `tests/test_research_migration.py` if verification reveals a missing invariant
- Modify: only the focused test files above if a real contract mismatch is found

**Interfaces:**
- Documentation becomes the source of truth for workspace/chat ownership and the permanent canvas.
- Verification must cover backend migration/repository/API tests, frontend tests, lint, TypeScript/build, and responsive/manual acceptance.

- [ ] **Step 1: Update core rules**

In `docs/CORE_LOGIC.md`, change the geometry rule to say panel geometry and z-index are persisted per workspace; frontmost activation ranks are workspace-scoped; analytical upserts preserve workspace layout. Keep the chat-scoped research-position rule and the mock trading-ticket warning unchanged, explicitly noting that chat-derived positions are not connected-wallet live positions.

- [ ] **Step 2: Update architecture and API reference**

Document this data flow in `docs/ARCHITECTURE_AND_WORKERS.md`:

```text
workspace selector -> workspace/tabs/panels
chat selector      -> messages/runs/results/research positions
analysis run(chat) -> immutable chat result + workspace panel upsert
```

In `docs/API_REFERENCE.md`, add authenticated workspace CRUD, fixed-tab retrieval, workspace panel listing, and the optional `workspace_id` on chat creation. State that foreign workspace/chat/panel IDs return 404 and that fixed tabs cannot be renamed/deleted.

- [ ] **Step 3: Run backend verification**

```bash
alembic heads
alembic current
pytest tests/test_research_migration.py tests/test_research_repository.py tests/test_research_api.py -q
```

Expected: one Alembic head (`a0b1c2d3e4f5`), current database at that head, and all focused backend tests pass. Verify the migration test runs against a database with legacy research rows as well as an empty database if the repository's test harness supports both; the backfill must be idempotent in either case.

- [ ] **Step 4: Run frontend verification**

```bash
cd frontend
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Expected: all Vitest tests pass, ESLint reports no new errors, TypeScript has no errors, and the production build completes. If Next.js emits a warning, record it; do not hide or broadly suppress it.

- [ ] **Step 5: Perform the acceptance pass**

Manually verify desktop, tablet, and narrow layouts:

1. Create two workspaces and confirm each shows exactly Wallet Groups, Market Groups, and Agents.
2. Create two chats in one workspace, run an analysis in each, and confirm the canvas panel remains in one workspace canvas rather than duplicating per chat.
3. Move, resize, minimize, maximize, close, restore, and reorder a panel; reload and confirm geometry/state/z-index persist.
4. Switch chats repeatedly and confirm only messages, run state, results, and chat-derived positions change.
5. Switch workspaces and confirm the canvas changes intentionally while fixed tabs remain stable.
6. Delete/close a chat with a panel and confirm the workspace panel remains with nullable source provenance.
7. Use keyboard navigation and confirm visible focus, tab semantics, and no horizontal overflow.
8. Confirm the trading ticket still displays its mock/unavailable boundary and no live credential/order UI was introduced.

- [ ] **Step 6: Commit documentation and verification fixes**

```bash
git add docs/CORE_LOGIC.md docs/ARCHITECTURE_AND_WORKERS.md docs/API_REFERENCE.md tests frontend/src
 git commit -m "docs(research): document permanent workspace canvas"
```

Only include focused fixes required by the verification matrix; leave unrelated dirty-worktree changes untouched.

---

## Self-Review Checklist

### Spec coverage

- Workspace-first ownership and multiple named workspaces: Tasks 1–3 and 7.
- Exactly three fixed tabs with database uniqueness and service/API protection: Tasks 1–3 and 7.
- Required chat-to-workspace association: Tasks 1–3 and 5–6.
- Safe one-workspace-per-legacy-chat migration with provenance and no silent merge: Task 1.
- Workspace-owned panels with preserved geometry/z-index and source-chat/result provenance: Tasks 1–4 and 8.
- Chat/workspace frontend identity separation and non-destructive chat switching: Tasks 5–8.
- Existing agent, groups/baskets, live adapters, vault custody, and execution intentionally remain out of scope per the design's first-slice non-goals.
- Owner isolation and non-disclosing 404 behavior: Tasks 2–3 and 9.
- Existing floating interaction behavior and honest mock terminal boundary: Tasks 5, 8, and 9.

### Placeholder scan

The plan contains no `TBD`, `TODO`, “implement later”, or unspecified “appropriate handling” steps. Every task names files, interfaces, concrete tests, commands, and expected outcomes.

### Type consistency

- Backend panel identity is consistently `workspace_id` plus nullable `source_chat_id`; result summaries remain `chat_id`-owned.
- Frontend panel identity mirrors the backend and `PanelCanvas`/`usePanelLayout` use `workspaceId` consistently.
- `useResearchHub` keys panels/tabs by workspace and messages/results/runs/positions by chat.
- `ResearchOrchestrator` passes `workspace_id` to repository panel methods while retaining `chat_id` for analysis context.
- Workspace tab names use the same three literal values in migration, Pydantic, TypeScript, API tests, and UI tests.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-06-research-permanent-workspace-canvas.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, and iterate quickly.

**2. Inline Execution** — execute tasks in this session using executing-plans, with batch checkpoints for review.

Which approach?`