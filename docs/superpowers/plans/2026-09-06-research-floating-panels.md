# Research Hub Floating Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users resize table height, move tables inside the research canvas, and bring the clicked table above overlapping tables, with layout restored per chat.

**Architecture:** Replace grid-relative transforms with canvas-relative floating rectangles on desktop. A dedicated interaction hook manages transient pointer state; authenticated panel updates persist final rectangles and stacking ranks in the existing JSONB layout. Small screens retain a stacked presentation without overwriting desktop geometry.

**Tech Stack:** Existing React/TypeScript, Pointer Events, ResizeObserver, CSS, FastAPI/Pydantic, asyncpg/PostgreSQL, Vitest/Testing Library, pytest.

## Global Constraints

- This plan is a focused addition to the Phase 2 plan, not an instruction to implement positions queries or the mock trading ticket.
- “Move position” means moving the table panel, not moving the bottom Positions bar.
- Height resizing is primary: provide a bottom-edge handle. A bottom-right handle adjusts both width and height.
- Drag only from a header grip/title area; clicking or selecting table text must not start dragging.
- Clicking or keyboard-focusing a panel brings it to the front without moving or resizing another panel.
- Overlap is intentional; do not use collision avoidance or push adjacent tables away.
- Panels remain within the canvas content area; never cover the chat rail, bottom Positions dock, or right mock ticket.
- Persist per-chat geometry and stacking order through authenticated backend updates. No browser-global layout shared across chats.
- Existing maximize/minimize/close/restore behavior remains available; state changes must not destroy the normal rectangle.
- No trading, provider, analytical SQL, or financial-data changes.
- Documentation only during planning. Implementation and commits require their own authorization; do not stage entire dirty files blindly.
- Read `frontend/AGENTS.md` and relevant installed Next.js guides before implementation.

## Verified starting point

`PanelCanvas.tsx` currently keeps `spanOverrides`, `orderOverrides`, `panelOffsets`, and `panelZIndices` locally. Panels remain in grid flow and use `translate3d` offsets, so this is not a stable coordinate system for freely overlapping windows. Pointer listeners are installed on `window`; the replacement must clean up on cancellation, unmount, and chat switching.

`PanelFrame.tsx` exposes movement/span/reorder callbacks. Retire redundant grid-reorder and HTML drag/drop behavior rather than running two competing drag systems.

`src/research/contracts.py:PanelLayout` currently contains `col_span`, `min_height`, and `order`. `repository.py:upsert_panel` replaces layout on conflict. That overwrite must be removed for existing panels, or a new analytical result will reset user geometry. The existing panel PATCH only updates state.

## Product behavior and geometry

- Desktop floating mode: canvas viewport width at least **640px**, and browser viewport at least **768px**. Otherwise use stacked mode.
- Coordinates are CSS pixels relative to a dedicated `position: relative` canvas stage, not the browser viewport or a grid cell.
- Normal minimum size: **320 × 240px**, maximum persisted size: **4096 × 4096px**. Width is additionally clamped to available canvas width.
- Stage height: `max(viewportHeight, maximum panel bottom + 24px)`, capped at **100000px**. Vertical scrolling is allowed inside the canvas; horizontal page overflow is not.
- Constrain `x >= 0`, `y >= 0`, `x + width <= stageWidth`, and `y + height <= 100000`. On a narrower canvas, clamp only the rendered rectangle; do not save a viewport-induced clamp until the user explicitly moves/resizes it.
- Legacy/new panel defaults: sorted by `(layout.order, created_at, panel_id)`, width `min(560, stageWidth)`, height `max(240, min(layout.min_height, 4096))`; cascade each next panel by 24px horizontally and vertically, wrapping horizontal placement to 0 when necessary.
- Bottom-edge drag changes height only. Corner drag changes width and height. The frame has a fixed header and a `min-height: 0` scrolling body; rows must not force the frame taller.
- Minimize shows the header at the normal rectangle origin and preserves normal size. Maximize fills the canvas viewport and hides other bodies without modifying saved geometry. Close retains geometry for restore.
- A `Reset layout` action restores deterministic cascade rectangles and stacking order for this chat only. Do not reuse misleading “Align to Grid” wording.
- Mobile/stacked mode disables free movement and resize handles, uses DOM flow and readable full-width panels, and preserves saved desktop layout.

## Interfaces and file map

Modify:
- `src/research/contracts.py` — backward-compatible floating layout fields and mutation validation.
- `src/research/repository.py` — owner-scoped layout mutation, atomic raise-to-front, preserve layout during analytical upsert.
- `src/api/routers/research.py` — extend existing panel PATCH.
- `frontend/src/types/research.ts` and `frontend/src/utils/researchApi.ts` — typed mutation contracts.
- `frontend/src/hooks/useResearchHub.ts` — integrate returned panels without replacing unrelated chat state.
- `frontend/src/components/research/PanelCanvas.tsx` — stage, responsive rendering, callback composition.
- `frontend/src/components/research/PanelFrame.tsx` — header grip, resize handles, focus behavior.
- `frontend/src/app/hub/ResearchHub.tsx` — supply chat identity and mutation callback; key canvas by chat.
- `frontend/src/app/globals.css` — floating stage and bounded scrolling frames.
- `docs/API_REFERENCE.md`, `docs/CORE_LOGIC.md` — layout API and behavior.

Create:
- `frontend/src/components/research/panelGeometry.ts` — pure geometry calculations.
- `frontend/src/hooks/usePanelLayout.ts` — pointer interaction and serialized saves.
- `frontend/src/components/research/__tests__/panelGeometry.test.ts`.
- `frontend/src/components/research/__tests__/PanelInteraction.test.tsx`.
- `frontend/src/hooks/usePanelLayout.test.tsx`.

Extend existing `tests/test_research_repository.py`, `tests/test_research_api.py`, and `PanelCanvas.test.tsx` rather than creating a new testing framework.

```typescript
export interface FloatingRect {
  x: number;
  y: number;
  width: number;
  height: number;
}
// Preserve existing PanelLayout fields; add:
// floating?: FloatingRect | null
// z_index?: number (default 0 for old rows)
export interface PanelMutation {
  state?: PanelState;
  floating?: FloatingRect;
  bring_to_front?: boolean;
}
// PATCH /api/v2/research/panels/{panelId} returns ResearchPanel.
```

Do not allow the client to supply `z_index`, chat ownership, result references, or arbitrary JSON layout keys. Backend assigns the stacking rank. Keep existing state-only callers valid.

## Task 1: Persist geometry without losing existing layouts

**Files:** backend contracts, repository, router; existing repository/API tests.

- [x] Write failing contract tests: accept `{state: 'normal'}` and `{floating: {x: 0,y: 12,width: 500,height: 320}, bring_to_front: true}`. Reject empty mutations, unknown fields, negative coordinates, non-finite/fractional coordinates, width below 320, height below 240, dimensions above 4096, and `y + height > 100000`. Old layout JSON without floating fields still parses.
- [x] Write repository tests proving a geometry update survives a later `upsert_panel` with the same semantic panel key and a new result ID. Assert result/config updates still occur. Assert state-only updates preserve geometry and geometry-only updates preserve state.
- [x] Implement `FloatingRect` as a Pydantic model with strict integer fields and the bounds above; extend `PanelLayout` with optional `floating` and default `z_index=0`. Add an extra-forbid mutation model with at least one effective operation.
- [x] Add `update_panel(owner_id: str, panel_id: UUID, mutation: PanelMutation) -> ResearchPanel | None`. In one transaction, resolve and lock the owned chat row, then update only requested fields. Merge geometry into layout JSON, retaining legacy fields. For `bring_to_front`, assign one greater than the current maximum rank in that chat. Serialize all rank mutations using the same chat-row lock. When maximum rank reaches 1000000, compact all chat ranks in stable existing order before raising the target. Return the target panel and ensure subsequent list responses restore the full order; frontend may refresh the panel list after rank compaction.
- [x] Remove `layout = EXCLUDED.layout` from the existing-panel upsert conflict branch. New panels still use defaults. Preserve all existing ownership checks.
- [x] Extend panel PATCH to call `update_panel`. Retain the state helper as a compatibility wrapper if existing callers/tests use it. No database migration is needed: layout is already JSONB.
- [x] Test missing authentication using the existing auth expectation, foreign panel 404, same-user different-chat independence, concurrent raises producing distinct ranks, and no changes after invalid requests.
- [x] Run `./.venv/Scripts/python.exe -m pytest tests/test_research_repository.py tests/test_research_api.py -v`. Require pass; run against a dedicated test database, not production.

## Task 2: Establish one geometry model

**Files:** `panelGeometry.ts`, its tests, shared frontend types.

```typescript
export type ResizeMode = 'height' | 'both';
export function clampRect(rect: FloatingRect, stageWidth: number): FloatingRect;
export function moveRect(rect: FloatingRect, dx: number, dy: number, stageWidth: number): FloatingRect;
export function resizeRect(rect: FloatingRect, dx: number, dy: number,
  mode: ResizeMode, stageWidth: number): FloatingRect;
export function defaultRect(index: number, stageWidth: number, minHeight: number): FloatingRect;
```

- [x] Write tests before implementation using exact examples:

```typescript
const rect = { x: 20, y: 30, width: 400, height: 300 };
expect(resizeRect(rect, 90, 100, 'height', 1000))
  .toEqual({ x: 20, y: 30, width: 400, height: 400 });
expect(moveRect(rect, -100, -100, 1000))
  .toEqual({ x: 0, y: 0, width: 400, height: 300 });
expect(moveRect(rect, 900, 0, 1000).x).toBe(600);
expect(resizeRect(rect, 0, -900, 'height', 1000).height).toBe(240);
```

- [x] Implement immutable arithmetic helpers; round pointer deltas to integer CSS pixels. Test bottom boundary, corner width bound, legacy defaults, and stage widths at the floating/stacked cutoff.
- [x] Keep geometry calculations independent of React/DOM. Do not mutate stored rectangles when deriving a viewport-clamped display rectangle.
- [x] Run `npm --prefix frontend test -- src/components/research/__tests__/panelGeometry.test.ts` and require pass.

## Task 3: Replace competing drag systems with pointer interactions

**Files:** `usePanelLayout.ts`, `PanelCanvas.tsx`, `PanelFrame.tsx`, `globals.css`, interaction tests.

- [x] Add failing tests that header dragging changes x/y, bottom resizing changes only height, corner resizing changes width/height, and body clicking raises without dragging. Test drag exclusion for buttons, links, inputs, selectable text, and menu items.
- [x] Implement one active gesture record containing pointer ID, panel ID, initial rectangle, initial pointer coordinates, and initial canvas scroll offsets. Use pointer capture on the handle; account for canvas scrolling during a gesture. Update transient geometry locally, optionally throttled with `requestAnimationFrame`; never send a request on each pointer move.
- [x] On pointerup, commit one final rectangle. On pointercancel, lost capture, Escape, unmount, or chat switch, discard the transient gesture and release listeners/capture; do not save a half-finished drag.
- [x] Replace grid-relative transforms with absolute positioning inside an isolated stage (`position: relative; isolation: isolate`). Use `left/top/width/height` from the display rectangle and persisted/transient rank. Canvas viewport clips horizontal overflow and owns vertical scrolling.
- [x] Remove span overrides, HTML drag/drop reorder, prev/next grid buttons, and duplicate frame-level bring-to-front dispatch. Use one capture-phase pointerdown handler and one guarded focus handler per panel; avoid a second raise when pointer focus follows the same interaction.
- [x] Add labelled handles: `Move <title>`, `Resize height of <title>`, and `Resize <title>`. Header grip supports arrow-key movement, height handle Up/Down resizing, corner handle arrows for each axis, at 16px increments. Use `touch-action: none` only on handles, not the table.
- [x] Preserve panel header metadata, table actions, and scrolling. Use a flex-column frame with a fixed header and scrolling content area.
- [x] Run geometry and interaction tests. Assert minimized and maximized panels do not expose inappropriate resize handles and restore retains the normal rectangle.

## Task 4: Integrate durable saves and click-to-front

**Files:** client API, research hook, layout hook, hub, hook tests.

- [x] Extend the typed panel PATCH helper to accept `PanelMutation`, adapting state-only callers without changing their behavior.
- [x] Supply `chatId` to the canvas and key its mounted interaction state by chat ID. Clear selected/active gesture state on switches; never reuse a previous chat's offsets.
- [x] Keep a per-chat serialized mutation queue. Coalesce unsent rectangle updates for the same panel; retain ordering of bring-to-front operations. This prevents an older resize response from replacing a newer one and prevents server request order from reversing local click order. Only apply returned fields to the corresponding panel/chat, never replace the entire panels array with an old snapshot.
- [x] Bring a panel forward optimistically on pointerdown or keyboard focus. Persist once per actual activation; clicking an already frontmost panel is a no-op. After successful saves use returned canonical ranks; preserve pending newer local changes over incoming stream upserts/refetches.
- [x] Failure behavior: show `Layout not saved` with Retry; retain the visible unsaved rectangle. Do not silently claim persistence or roll back newer local edits. Retry uses the latest intended state, not the failed obsolete payload. On chat change/unmount, finish already queued saves without updating another chat's UI; abandon active gestures.
- [x] Tests: old response after newer drag, stream refresh during resize, resize then maximize, switch A→B while A save resolves, failure/retry, reload restoration, and rapid A→B→A foreground selection.
- [x] Run `npm --prefix frontend test -- src/hooks/usePanelLayout.test.tsx` plus existing API client and canvas tests.

## Task 5: Responsive states, reset, and acceptance

**Files:** canvas/frame/CSS, canvas tests, API reference and core logic docs.

- [x] Implement ResizeObserver-based floating-mode eligibility. In stacked mode render panels in stable layout order, without desktop absolute geometry or resize handles. Returning to desktop restores the saved rectangles. Do not persist changes merely because the browser or chat rail was resized.
- [x] Implement `Reset layout` using the deterministic cascade and the same serialized save queue. Apply normal rectangles without changing result references or open/closed states. Clearly show save failures; retry remaining latest intended changes. Reset only the current chat.
- [x] Add tests for click-to-front with three overlapping tables; close/restore; minimize/restore; maximize/restore; legacy panels without geometry; a newly streamed panel; and reset. Existing analytical panel pagination and click actions must remain usable.
- [x] Browser acceptance at 1440×900, 1024×768, and 390×844: drag headers, resize height, resize corners, select text, activate links, scroll rows, resize chat rail, reload, switch chats, and simulate failed saves. Verify actual visual stacking and hit-testing, not only assigned z-index values. Use the project run skill when executing this browser verification.
- [x] Run backend research tests, `npm --prefix frontend test`, `npm --prefix frontend run lint`, and `npm --prefix frontend run build`. Record actual failures; do not state pre-existing tests passed without running them.
- [x] Document extended panel PATCH, compatibility, geometry bounds, stacking persistence, mobile fallback, and update-preserves-layout behavior in `docs/API_REFERENCE.md` and `docs/CORE_LOGIC.md`. Add a changelog entry only once implemented and verified.

## Completion criteria

1. Dragging a table's bottom edge visibly changes height without widening it or shifting adjacent tables.
2. Header dragging moves a panel freely within the canvas; overlap remains possible.
3. Clicking any visible part of a lower panel raises it above every other normal panel without swallowing the original table action.
4. Reload and chat switching preserve committed position, dimensions, and stacking order.
5. New analytical content does not reset an existing panel's user layout.
6. Minimize/maximize/close/restore preserve the normal rectangle.
7. Narrow screens remain readable and cannot destroy desktop layouts.
8. Foreign-user mutations fail, and failed saves are visible and retryable.
9. No changes to the bottom Positions dock location, mock trading behavior, or analytical results.

## Self-review

The requested height resizing, free movement, and foreground-on-click each have explicit interaction and acceptance tests. Persistence uses the existing JSONB column, keeps legacy fields, and addresses the verified analytical-upsert overwrite. Pointer cancellation, save ordering, viewport changes, chat isolation, and accessible alternatives are included. This plan does not require a new drag/grid package or a schema migration.
