# Research Hub Phase 2: Positions and Mock Trading Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Research Hub workspace with a real, owner-scoped positions view for wallets discovered in the active chat while adding a clearly non-functional frontend-only mock trading ticket.

**Architecture:** The backend adds one read-only endpoint that resolves wallet memberships through the authenticated chat's persisted result sets and joins them set-wise to `wallet_positions_v2` and `markets_v2`. The frontend loads those rows for the active chat and renders them in the bottom Positions bar; the right-side Trading Panel is presentation-only, receives a selected market snapshot, and never calls an order API or the execution broker.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL, pytest/pytest-asyncio, Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, Vitest, Testing Library.

## Global Constraints

- Do not add market-order placement, CLOB credentials, wallet signing, or any live/dry-run broker call.
- The Trading Panel must visibly say that it is a mock/preview and must not imply an order was submitted.
- Every positions query must enforce both authenticated owner and chat ownership in SQL; cross-owner IDs return 404. Unauthenticated requests follow the existing API contract and return 401.
- Positions include only `wallet_positions_v2.current_value > 0` and `is_resolved = FALSE`, matching the existing open-position definition.
- Do not invent prices, balances, expirations, payout values, day P&L, ticker symbols, or order status. Missing database fields render an em dash.
- Positions are read from persisted result-set members; never accept an arbitrary wallet address list from the browser.
- Preserve all unrelated user changes in the dirty worktree. Do not reset, stash, reformat, or commit unrelated files.
- Follow `frontend/AGENTS.md` and read the relevant Next.js guide before modifying frontend code.

---

## File Map

### Backend

- Modify: `src/api/routers/research.py` — add the authenticated positions route.
- Modify: `src/research/repository.py` — add owner/chat-scoped result-set membership lookup if the analytics query needs a repository primitive.
- Modify: `src/research/analytics.py` — add the set-based positions query and row normalization if that is the established boundary for analytical SQL.
- Modify: `src/research/contracts.py` — add a typed position response only if the existing contract style requires it; otherwise keep the endpoint response as typed dictionaries matching existing result members.
- Modify: `tests/test_research_api.py` — endpoint auth, ownership, pagination, and empty-state coverage.
- Modify: `tests/test_research_analytics.py` — SQL semantics and unresolved/current-value filtering.

### Frontend

- Modify: `frontend/src/utils/researchApi.ts` — typed positions request.
- Modify: `frontend/src/hooks/useResearchHub.ts` — load/cache positions per chat and expose selection state.
- Modify: `frontend/src/types/research.ts` — `ResearchPosition` and API response types.
- Modify: `frontend/src/app/hub/ResearchHub.tsx` — connect positions bar, selected position, and mock ticket.
- Modify: `frontend/src/components/research/PositionsBar.tsx` — render real position rows and selection.
- Modify: `frontend/src/components/research/TradingPanel.tsx` — mock-only copy and selected-market display.
- Modify: `frontend/src/app/globals.css` — styles for positions bar and mock trading panel.
- Create: `frontend/src/components/research/__tests__/PositionsBar.test.tsx` — selection, empty, loading, and missing-field behavior.
- Modify: `frontend/src/components/research/__tests__/PanelCanvas.test.tsx` only if the hub layout contract changes.

### Documentation

- Modify: `docs/API_REFERENCE.md` — positions endpoint contract.
- Modify: `docs/CORE_LOGIC.md` — chat-scoped position definition and mock-trading boundary.
- Modify: `docs/CHANGELOG.md` — newest-first Phase 2 entry after tests pass.

---

## Task 1: Repair and baseline the existing Phase 2 frontend

**Files:**
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/research/ChatRail.tsx`
- Modify: `frontend/src/components/research/PanelFrame.tsx`
- Modify: `frontend/src/components/research/TradingPanel.tsx`
- Modify: `frontend/src/components/research/PositionsBar.tsx`
- Test: existing frontend test suite

**Interfaces:**
- Produces a compiling baseline for the later positions wiring.
- Does not change backend behavior or add an order interface.

- [ ] **Step 1: Inspect the six changed TSX files and normalize only accidental escaping**

  If a file literally contains `\\"`, replace those byte sequences with ordinary TypeScript quotes. Do not alter valid JSX entities, string contents, or unrelated formatting. If the files already contain ordinary quotes when implementation begins, make no change.

- [ ] **Step 2: Run the baseline checks**

  Run from `frontend`:

  ```powershell
  npm test
  npm run lint
  npm run build
  ```

  Expected: the baseline either passes or produces a concrete list of existing failures. Do not continue while a syntax error from escaped quotes remains.

- [ ] **Step 3: Commit only the baseline repair if needed**

  ```powershell
  git add frontend/src/app/hub/ResearchHub.tsx frontend/src/components/Sidebar.tsx frontend/src/components/research/ChatRail.tsx frontend/src/components/research/PanelFrame.tsx frontend/src/components/research/TradingPanel.tsx frontend/src/components/research/PositionsBar.tsx
  git commit -m "fix(research-ui): restore valid TypeScript source"
  ```

  Skip the commit when no repair was needed; never stage unrelated files.

---

## Task 2: Add the owner-scoped positions query

**Files:**
- Modify: `src/research/analytics.py` or `src/research/repository.py` according to the existing separation of SQL and persistence.
- Modify: `tests/test_research_analytics.py`

**Interfaces:**
- Produces `list_positions(owner_id: str, chat_id: UUID, offset: int = 0, limit: int = 100) -> list[dict[str, object]]` (or the equivalent existing naming convention, used consistently by the router and tests).
- Each returned row contains `address`, `condition_id`, `market_title`, `outcome`, `size`, `avg_price`, `current_value`, `unrealized_pnl`, `entry_at`, and `computed_at`; nullable fields remain `None`.

- [ ] **Step 1: Add failing database tests**

  Seed two users, two chats, a wallet result set owned by the first user, wallet result members, markets, and positions. Assert:

  ```python
  rows = await analytics.list_positions(owner_a, chat_a, 0, 100)
  assert [row["address"] for row in rows] == [wallet_a]
  assert rows[0]["condition_id"] == market_a
  assert rows[0]["current_value"] > 0
  ```

  Also seed a zero-value position, a resolved/closed position according to the actual schema, a wallet member in another chat, and a result set owned by the second user. Assert those rows never appear in `chat_a` results. Assert deterministic ordering by `current_value DESC`, then `condition_id`, `outcome`, and address. Assert offset and maximum page size are bounded.

- [ ] **Step 2: Run the focused tests and verify failure**

  ```powershell
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_research_analytics.py -k positions -v
  ```

  Expected: missing method or missing route implementation.

- [ ] **Step 3: Implement one set-based query**

  First resolve the requested chat and result references under the owner. The query must constrain `rs.chat_id = $2::uuid` and `rs.kind = 'wallet_set'` for direct wallet results. If the UI later consumes an overlap result, resolve its persisted `definition.arguments.wallet_result_set_id`, verify that upstream result belongs to the same owner and chat, and constrain the overlap's market members as well. Do not treat owner-only result authorization as sufficient.

  Start from the authenticated chat's wallet result members:

  ```sql
  WITH chat_wallets AS (
      SELECT DISTINCT m.entity_key AS address
      FROM research_result_members m
      JOIN research_result_sets rs ON rs.result_set_id = m.result_set_id
      JOIN research_chats c ON c.chat_id = rs.chat_id
      WHERE c.owner_id = $1::uuid
        AND c.chat_id = $2::uuid
        AND m.entity_type = 'wallet'
  )
  SELECT p.address, p.condition_id, mk.title AS market_title,
         p.outcome, p.size, p.avg_price, p.current_value,
         p.unrealized_pnl, p.entry_at, p.computed_at
  FROM wallet_positions_v2 p
  JOIN chat_wallets cw ON cw.address = p.address
  LEFT JOIN markets_v2 mk ON mk.condition_id = p.condition_id
  WHERE COALESCE(p.current_value, 0) > 0
  AND COALESCE(p.is_resolved, FALSE) = FALSE
  ORDER BY p.current_value DESC NULLS LAST, p.condition_id, p.outcome, p.address
  OFFSET $3 LIMIT $4
  ```

  Use parameters for owner, chat, offset, and limit. Do not interpolate IDs or limits. If the existing schema has no unresolved flag on `wallet_positions_v2`, define the endpoint as current positions (the table itself is the open-position source) and test that exact rule rather than referencing a nonexistent column.

- [ ] **Step 4: Run the focused tests**

  ```powershell
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_research_analytics.py -k positions -v
  ```

  Expected: all position query tests pass, including cross-owner isolation.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/research/analytics.py src/research/repository.py tests/test_research_analytics.py
  git commit -m "feat(research): query chat-scoped open positions"
  ```

---

## Task 3: Expose the paginated positions API

**Files:**
- Modify: `src/api/routers/research.py`
- Modify: `tests/test_research_api.py`

**Interfaces:**
- `GET /api/v2/research/chats/{chat_id}/positions?offset=0&limit=100`
- Response: `{ "positions": [ResearchPosition], "offset": number, "limit": number }`.
- Unauthenticated requests return 403; an inaccessible chat returns 404 without revealing whether it exists.

- [ ] **Step 1: Add failing API tests**

  Cover authenticated success, empty chat, `limit > 200` validation, unauthenticated 401, and a second user's chat ID returning 404. Assert that the response never includes positions belonging to wallets from another chat or owner, and that same-owner results from a different chat are excluded.

- [ ] **Step 2: Run and verify failure**

  ```powershell
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_research_api.py -k positions -v
  ```

  Expected: 404 because the route does not yet exist.

- [ ] **Step 3: Implement the route**

  Follow the existing route pattern: validate chat ownership first, parse `offset: int = Query(0, ge=0)` and `limit: int = Query(100, ge=1, le=200)`, call the set-based query with `_uid(user)`, and return JSON. Do not accept `address`, `condition_id`, or result-set IDs from the client. Match the existing auth tests: missing credentials return 401 and foreign resources return 404.

- [ ] **Step 4: Run backend research tests**

  ```powershell
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_research_api.py tests/test_research_analytics.py -v
  ```

  Expected: all selected tests pass.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/api/routers/research.py tests/test_research_api.py
  git commit -m "feat(research): expose paginated positions endpoint"
  ```

---

## Task 4: Add typed client and hook state

**Files:**
- Modify: `frontend/src/types/research.ts`
- Modify: `frontend/src/utils/researchApi.ts`
- Modify: `frontend/src/hooks/useResearchHub.ts`
- Test: `frontend/src/utils/researchApi.test.ts`

**Interfaces:**

```typescript
export interface ResearchPosition {
  address: string;
  condition_id: string;
  market_title: string | null;
  outcome: string | null;
  size: number | null;
  avg_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  entry_at: string | null;
  computed_at: string | null;
}

export interface PositionsPage {
  positions: ResearchPosition[];
  offset: number;
  limit: number;
}

export async function listPositions(chatId: string, offset = 0, limit = 100): Promise<PositionsPage>;
```

- [ ] **Step 1: Add failing client tests**

  Mock `fetch` and assert the URL, auth headers, query parameters, JSON decoding, non-2xx error, and abort signal. Add a test that `refreshChatData(chatId)` requests positions and stores them under that chat.

- [ ] **Step 2: Run and verify failure**

  ```powershell
  cd frontend
  npm test -- src/utils/researchApi.test.ts
  ```

  Expected: missing `listPositions` or missing hook state.

- [ ] **Step 3: Implement the client and state**

  Add `listPositions` using the existing `request` helper. Extend the hook with `positionsByChat: Record<string, ResearchPosition[]>`, load the first page in `refreshChatData`, and expose `positionsForChat(chatId)`. Refresh after a terminal run exactly as messages, panels, and result summaries are refreshed. A positions-fetch failure must not discard already loaded messages/panels; retain the previous positions and surface no fake rows.

- [ ] **Step 4: Run frontend tests and build**

  ```powershell
  npm test -- src/utils/researchApi.test.ts
  npm run build
  ```

  Expected: all selected tests pass and the production build succeeds.

- [ ] **Step 5: Commit**

  ```powershell
  git add frontend/src/types/research.ts frontend/src/utils/researchApi.ts frontend/src/hooks/useResearchHub.ts frontend/src/utils/researchApi.test.ts
  git commit -m "feat(research-ui): load chat-scoped positions"
  ```

---

## Task 5: Render real positions and selection

**Files:**
- Modify: `frontend/src/components/research/PositionsBar.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Create: `frontend/src/components/research/__tests__/PositionsBar.test.tsx`

**Interfaces:**
- `PositionsBar` consumes `rows: ResearchPosition[]`, `chatTitle?: string`, and `onSelectPosition?: (position: ResearchPosition) => void`.
- `TradingPanel` consumes `selectedPosition?: ResearchPosition` and remains frontend-only.

- [ ] **Step 1: Write failing component tests**

  Cover:

  ```tsx
  render(<PositionsBar rows={[position]} onSelectPosition={onSelect} />);
  expect(screen.getByText("Market Alpha")).toBeInTheDocument();
  expect(screen.getByText("YES")).toBeInTheDocument();
  expect(screen.getByText("$12.50")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /market alpha/i }));
  expect(onSelect).toHaveBeenCalledWith(position);
  ```

  Also cover empty state, null values as `—`, accessible collapse control, and that Orders/Fills/Taker tabs explicitly show unavailable/mock empty states rather than fabricated rows.

- [ ] **Step 2: Run and verify failure**

  ```powershell
  cd frontend
  npm test -- src/components/research/__tests__/PositionsBar.test.tsx
  ```

  Expected: prop/type or assertion failures because the current component expects `ResultMember[]` and renders fields that do not exist in the API contract.

- [ ] **Step 3: Implement the real table**

  Replace `ResultMember` extraction with typed `ResearchPosition` rendering. Use columns that the database supplies: market title/condition ID fallback, outcome, contracts (`size`), average price, current value, and unrealized P&L. Do not render hardcoded ticker, cost, payout, day P&L, or total P&L. Make each position row a keyboard-accessible button or provide an explicit select button; preserve horizontal scrolling at narrow desktop widths.

- [ ] **Step 4: Wire the hub**

  In `ResearchHub.tsx`, derive `positionsForChat(activeId)`, keep `selectedPosition` local to the active chat (clear it when switching chats), pass rows and `onSelectPosition` to `PositionsBar`, and pass the selection to `TradingPanel`. Do not pass `rows={[]}` or `positionRows={[]}` once the hook exposes data.

- [ ] **Step 5: Run tests and commit**

  ```powershell
  npm test -- src/components/research/__tests__/PositionsBar.test.tsx src/components/research/__tests__/ChatRail.test.tsx
  npm run lint
  ```

  Expected: selected tests and lint pass.

  ```powershell
  git add frontend/src/components/research/PositionsBar.tsx frontend/src/components/research/__tests__/PositionsBar.test.tsx frontend/src/app/hub/ResearchHub.tsx
  git commit -m "feat(research-ui): render selectable wallet positions"
  ```

---

## Task 6: Make the Trading Panel an honest frontend mock

**Files:**
- Modify: `frontend/src/components/research/TradingPanel.tsx`
- Modify: `frontend/src/app/hub/ResearchHub.tsx`
- Modify: `frontend/src/components/research/__tests__/PositionsBar.test.tsx` or create `frontend/src/components/research/__tests__/TradingPanel.test.tsx`

**Interfaces:**
- `TradingPanel` receives `selectedPosition?: ResearchPosition`, `visible?: boolean`, and `onToggle?: () => void`.
- It performs no fetch, mutation, broker call, or navigation to an order endpoint.

- [ ] **Step 1: Add failing mock-boundary tests**

  Assert the panel displays `Preview only` / `Mock order ticket`, selected market and outcome when a position is selected, and a disabled or non-submitting review control. Assert that clicking the review control does not call `fetch` and does not emit an order request.

- [ ] **Step 2: Run and verify failure**

  ```powershell
  npm test -- src/components/research/__tests__/TradingPanel.test.tsx
  ```

  Expected: missing honest mock copy or selected-position behavior.

- [ ] **Step 3: Implement mock-only behavior**

  Keep local controls for buy/sell, share presets, limit/market display, and time-in-force only as visual interaction. Replace hardcoded account balance, expiration, payout, and price claims with `—` or explicit `Mock` labels. The primary control must say `Review mock order` and either be disabled or only show a local confirmation state; it must never call an API. Add an accessible warning explaining that market order placement is not integrated.

- [ ] **Step 4: Run tests and commit**

  ```powershell
  npm test -- src/components/research/__tests__/TradingPanel.test.tsx
  npm run build
  ```

  Expected: all selected tests pass and no order-related network request is made.

  ```powershell
  git add frontend/src/components/research/TradingPanel.tsx frontend/src/components/research/__tests__/TradingPanel.test.tsx frontend/src/app/hub/ResearchHub.tsx
  git commit -m "feat(research-ui): add frontend-only mock order ticket"
  ```

---

## Task 7: Style the three-zone workspace and responsive states

**Files:**
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/app/hub/ResearchHub.tsx` only for class/ARIA wiring required by CSS.

- [ ] **Step 1: Add focused styling**

  Add styles for `.positions-bar`, `.positions-bar-header`, `.positions-tabs`, `.positions-table`, `.positions-th`, `.positions-td`, `.trading-panel`, `.trading-panel-hidden`, and their controls. Use the existing background, surface, border, primary, success, and danger tokens. Keep the existing light workspace palette; do not introduce a second theme.

- [ ] **Step 2: Define responsive behavior**

  At the existing desktop breakpoint, retain chat rail + canvas + right mock panel. At widths below 1100px, stack analytical canvas panels while retaining the workspace split. Below 768px, hide the right mock panel behind a toggle and use the existing Chat/Results view switcher; the Positions bar remains horizontally scrollable rather than overflowing the viewport.

- [ ] **Step 3: Verify visual and accessibility states**

  Run:

  ```powershell
  cd frontend
  npm test
  npm run lint
  npm run build
  ```

  Manually verify 1440×900, 1024×768, and a sub-768px viewport. Verify keyboard focus, `aria-label`s, no horizontal page overflow, empty positions state, collapsed bar, selected row, and mock warning.

- [ ] **Step 4: Commit**

  ```powershell
  git add frontend/src/app/globals.css frontend/src/app/hub/ResearchHub.tsx
  git commit -m "style(research-ui): style positions dock and mock ticket"
  ```

---

## Task 8: Document and run the release gate

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/CORE_LOGIC.md`
- Modify: `docs/CHANGELOG.md`
- Create: `tests/test_research_phase2.py` only if an end-to-end backend/frontend contract test is not already covered by the existing modules.

- [ ] **Step 1: Document the positions endpoint**

  Add the exact path, query bounds, response fields, owner/chat isolation behavior, current-position predicate, ordering, and pagination semantics to `docs/API_REFERENCE.md`.

- [ ] **Step 2: Document the product boundary**

  In `docs/CORE_LOGIC.md`, state that positions are derived from wallet members persisted by the active chat and that the right-side ticket is a UI mock. Explicitly state that no order is placed, no execution broker is called, and no price/balance/expiration is authoritative in the mock.

- [ ] **Step 3: Add a changelog entry**

  Add a newest-first entry dated `2026-09-06` describing the chat-scoped positions dock, selectable market context, frontend-only mock ticket, ownership isolation, and tests. Do not claim live trading or order placement.

- [ ] **Step 4: Run the complete feature gate**

  Backend:

  ```powershell
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_research_migration.py tests/test_research_repository.py tests/test_research_analytics.py tests/test_research_tools.py tests/test_research_context.py tests/test_research_orchestrator.py tests/test_research_api.py tests/test_research_query_plans.py tests/test_research_e2e.py -v
  ```

  Frontend:

  ```powershell
  cd frontend
  npm test
  npm run lint
  npm run build
  ```

  Expected: all feature tests, lint, and build pass. If an existing unrelated test fails, record its exact failure and do not hide it by changing the test.

- [ ] **Step 5: Commit documentation only**

  ```powershell
  git add docs/API_REFERENCE.md docs/CORE_LOGIC.md docs/CHANGELOG.md
  git commit -m "docs: document Research Hub positions and mock trading"
  ```

---

## Release Gates

- The positions endpoint is read-only, paginated, set-based, and owner/chat scoped.
- A second user cannot infer another user's chat, result set, or positions.
- The active chat loads real `wallet_positions_v2` values; no empty-array placeholder remains in the hub wiring.
- Missing database values render as `—`; no fabricated financial values appear in the positions table.
- The Trading Panel is visibly a frontend mock and makes no network or broker calls.
- Orders, fills, and taker activity are labelled unavailable/mock rather than represented by fake records.
- The layout works at desktop, tablet, and narrow/mobile breakpoints without page overflow.
- Backend research tests, frontend tests, lint, and production build pass.
- Existing `/agents`, `/wallets`, `/feed`, `/tracker`, and wallet-detail routes remain unchanged.

## Plan Self-Review

- **Scope:** This plan covers only positions data wiring and the explicitly requested frontend mock trading panel; live trading, CLOB integration, and execution are excluded.
- **Data integrity:** All displayed position values originate from database rows returned by the authenticated chat-scoped query; unavailable fields are not synthesized.
- **Ownership:** The SQL path begins at `research_chats` and checks `owner_id`; the API performs a 404 chat check before querying.
- **Type consistency:** `ResearchPosition` is the single frontend row type, replacing the current `ResultMember`/hardcoded-field mismatch for the Positions bar.
- **Placeholder scan:** No implementation step uses TBD/TODO or asks an implementer to infer unspecified behavior; the only schema-dependent branch is explicitly resolved by inspecting the actual `wallet_positions_v2` columns before coding.
- **Dirty worktree safety:** The plan stages only feature files per task and never resets or removes existing changes.
