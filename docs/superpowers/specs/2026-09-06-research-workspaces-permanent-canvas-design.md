# Research Workspaces and Permanent Canvas Design

**Date:** 2026-09-06  
**Status:** Design approved during brainstorming; implementation not included in this document.

## Context

The current Research Hub treats a chat as the owner of messages, analysis result sets, panels, and panel geometry. Changing chats therefore changes the visible canvas. That is appropriate for conversation history, but it is the wrong model for a durable research and trading workspace.

The new product model separates a persistent named workspace from its assisting chats. A workspace is the durable home for the user's canvas, groups, baskets, selected agents, and terminal context. A chat is an assistant/history layer attached to a workspace. Chat prompts can assist with workspace actions, but changing the active chat must never replace the workspace canvas.

The product must also prepare for multiple connected wallets, backend-normalized live market/account data, and future auto-submitted trading. Live execution is a later phase and must not bypass wallet arming, limits, idempotency, audit, or emergency disarm controls.

## Goals

- Support multiple named workspaces/canvases per user.
- Make the canvas permanent across chat switching.
- Provide exactly three top-level canvas tabs: Wallet Groups, Market Groups, and Agents.
- Support curated and dynamic wallet/market groups.
- Support wallet baskets and market baskets as non-executable first-class objects.
- Reuse existing owner-scoped automation agents in the Agents tab.
- Attach chats to workspaces without making chats the canvas owner.
- Support multiple connected wallets with a visible wallet selector.
- Establish a secure foundation for API-credential and wallet-signing connection flows.
- Provide a backend-normalized path for live positions, open orders, fills, orderbook, and market depth.
- Allow canvas market selection to drive the terminal unless the terminal market is explicitly pinned.
- Route all future execution sources through one policy and audit gate.

## Non-goals for the first implementation slice

- Live order placement.
- Wallet signing or credential custody implementation.
- Live orderbook/open-order adapters.
- Executable order baskets.
- Replacing the existing `/agents` domain with a second agent system.
- Generic event-sourced resource graphs.
- Unrestricted model-generated SQL.
- Silent merging of incompatible legacy chat canvases.

The first implementation slice is the permanent workspace canvas, fixed tabs, safe migration, and chat/workspace state separation. Groups, live terminal reads, and execution follow as separate milestones.

## Product model

### Workspaces

A user may create multiple named workspaces, such as `Cricket`, `Politics`, or `Live trading`. A workspace owns the permanent canvas and the following resources:

- Canvas panels and their state, geometry, and stacking order.
- Three fixed tabs: Wallet Groups, Market Groups, and Agents.
- Wallet groups, market groups, wallet baskets, and market baskets.
- Associations to selected existing automation agents.
- Selected and pinned market context for the trading terminal.
- Later, wallet access policies and execution settings.

Tabs are stable workspace presentation and authorization boundaries. They do not create separate canvas owners. A panel remains workspace-owned while a tab determines which compatible objects are surfaced.

Every workspace is transactionally seeded with exactly one tab of each allowed type:

- `wallet_groups`
- `market_groups`
- `agents`

The database enforces `UNIQUE(workspace_id, tab_type)` and an allow-list for tab types. API operations do not permit deleting or renaming the fixed tabs. A service-level invariant and, where appropriate, a database trigger protect the requirement that every workspace retains all three tabs.

### Chats

A chat has a required `workspace_id`. It continues to own:

- Messages.
- Runs and stream status.
- Immutable result-set snapshots and members.
- Prompt context and assistant history.

Changing `activeChatId` changes only the Chat Rail and assistant context. It does not replace, reset, or reload the active workspace's canvas, groups, baskets, agent associations, or terminal state. Changing `activeWorkspaceId` intentionally changes those workspace-owned resources and the workspace context available to chats.

Chat actions use typed server-side commands. An action must identify its target workspace and resource type. The server verifies owner and workspace access, validates the command, and records provenance. The model receives opaque IDs and bounded summaries, never credentials, signing material, unrestricted rows, or generated SQL.

### Groups

Groups are typed workspace resources with `kind = wallet | market` and `mode = curated | dynamic`.

A curated wallet group stores explicit normalized wallet addresses. A curated market group stores explicit market condition IDs. A dynamic group stores an allow-listed query definition. The query definition is a typed DSL translated by backend code into parameterized analytics operations; it is never model-generated SQL.

Each dynamic refresh creates a versioned membership snapshot with:

- Snapshot/version ID.
- Membership count and bounded member records.
- Definition hash or canonical definition.
- Refreshed timestamp.
- Source timestamp and stale indicator.

The snapshot used by an analysis remains reproducible even after a dynamic group refreshes. Query cost, result size, refresh frequency, and expansion depth are bounded.

### Baskets

Baskets are first-class, saved, non-executable objects shown alongside groups through filters such as `All`, `Groups`, and `Baskets` in the relevant tab.

- A wallet basket contains wallets and/or compatible wallet groups.
- A market basket contains markets and/or compatible market groups.
- Baskets contain no order legs, prices, sizes, execution policies, broker instructions, or other order-basket fields.
- Cross-kind references, cycles, excessive nesting, and unbounded expansion are rejected by both service validation and database-compatible constraints.
- The UI distinguishes direct members from members inherited from referenced groups.

A basket is an organizational and analytical collection, not a trading instruction.

### Agents

The Agents tab reuses the existing owner-scoped `/v2/agents` records. Those rows remain authoritative for agent name, rule tree, actions, active state, trading-armed state, cooldown, and events. A `research_workspace_agents` association exposes an existing agent in one or more workspaces without copying or forking it.

The tab displays active/inactive state, armed/disarmed state, linked wallet context where available, rule/action summary, last evaluated/fired timestamps, and recent events. Workspace association does not weaken existing agent ownership.

Before live execution is enabled, every execution source must use one shared execution gate. The current `src/agents/dispatch.py` direct broker path must be refactored so existing agents cannot bypass that gate. The same gate must serve terminal submissions and scheduled/strategy rules.

## Trading terminal model

The terminal is a workspace-level operational surface, not a chat panel. It has a visible wallet selector supporting multiple connected wallets:

```text
Wallet 1  [selected]
Wallet 2
Wallet 3
+ Connect wallet
```

### Wallet identity and credentials

Public identity and secret material are separate resources.

- `wallet_accounts` stores owner, user label, normalized address, chain/network, connection state, and safe capabilities.
- API/CLOB credentials use a separate encrypted server-side vault/KMS reference.
- Wallet-signing credentials use a separate encrypted server-side vault/KMS reference and a visibly distinct permission/status path.
- The browser and model receive only opaque IDs, labels, safe public address metadata where appropriate, capability flags, and connection/armed status.
- Raw API secrets, passphrases, private keys, and decrypted credential material never reach the browser or LLM context.

The selected wallet determines the terminal's live positions, balances, open orders, fills, and account state. The selected wallet identity is always visible next to live account data and order controls.

### Market selection

The terminal has its own market search/selector. Canvas selection can also set the terminal market:

- Selecting a market from a group, basket, panel, or position row updates the terminal when no market is pinned.
- A user can manually select and pin a terminal market.
- While pinned, canvas and chat changes do not change the terminal market.
- Unpinning restores canvas-driven selection.

### Normalized live data

Backend venue adapters own provider API/WebSocket details and emit stable contracts for:

- User positions.
- Open orders.
- Recent fills and account activity.
- Orderbook bids and asks.
- Market depth/aggregated liquidity.
- Connection state, source timestamp, last update, and stale/reconnecting status.

Public market data may use a public adapter. Private positions and orders use the selected wallet's authenticated adapter. The browser consumes a user/workspace-scoped stream or polling contract; it does not connect directly to private venue APIs. Existing global activity broadcasts are not reused for private terminal state.

Discovered-wallet research positions remain analytically distinct from connected-user-wallet positions. Missing or stale values are shown as unavailable; the UI never fabricates prices, balances, order status, or depth.

## Execution safety boundary

Live execution is a later milestone. Once implemented, auto-submit may be enabled only for explicitly configured wallets and actors. The terminal, existing agents, and scheduled/strategy rules may submit after setup; chat is an orchestrator of typed commands, not an alternate broker path.

Every order intent passes through a common gate that verifies:

1. Wallet connection and explicit armed state.
2. Actor authorization for that wallet.
3. Market, outcome, side, price, size, and venue validity.
4. Per-order, per-market, daily, and portfolio limits.
5. Idempotency key and duplicate protection.
6. Broker-adapter result normalization.
7. Immutable execution audit record.
8. Emergency-disarm and policy failure checks.

The gate is the only path to a broker. Dry-run/refusal behavior remains the default until a real adapter is implemented and tested. Credentials and signing remain backend-only.

## Persistence and migration

The existing research migration created chat-owned `research_panels`. Before adding new migrations, verify the actual current Alembic head and base the migration on that single head rather than assuming the original research revision is current.

The target model introduces the following logical resources:

```text
research_workspaces
research_workspace_tabs
research_chats.workspace_id
workspace-owned research panels/layout
research_groups
research_group_members or versioned snapshots
research_baskets
research_basket_items
research_workspace_agents
wallet_accounts
credential/vault bindings
workspace_terminal_state
normalized terminal snapshots/events
execution policies/intents/audit
```

The migration must preserve existing chat history and panel state:

1. Create a deterministic workspace for each legacy chat unless a future, explicit merge operation is defined. Do not silently merge incompatible canvases.
2. Seed exactly the three fixed tabs in one transaction.
3. Add and populate `research_chats.workspace_id`.
4. Move or copy panels to workspace ownership while retaining source chat and result-set provenance.
5. Preserve floating rectangles, z-index, panel state, result references, messages, and runs.
6. Add dual-read/ownership tests before removing the old chat-owned path.
7. Refactor frontend state only after the persisted workspace contract is verified.

The migration must be owner-scoped and idempotent. Every child read and mutation joins through the authenticated owner and workspace. Existing result sets remain chat-provenance records; they are not silently converted into canonical groups.

## Frontend state and component direction

The current `useResearchHub` maps `panelsByChat`, results, and positions by chat. The new state must separate the two identities:

```text
Workspace state:
  workspaces
  activeWorkspaceId
  panels/groups/baskets/agents/terminalByWorkspace

Chat state:
  chats
  activeChatId
  messages/runs/resultsByChat
```

`ResearchHub` renders `PanelCanvas` from `activeWorkspaceId`. `ChatRail` renders messages and run state from `activeChatId`. `PanelCanvas` no longer receives chat identity as its persistence key. Panel mutations target workspace-owned panel IDs and verify workspace ownership on the server.

The current floating geometry implementation can be reused as interaction behavior, but its persistence owner must change from chat to workspace. Existing panel layout fields and safe geometry constraints remain valuable. The mock trading terminal remains visibly mock/unavailable until normalized read adapters are available; it must not be relabeled as live prematurely.

## API and data-flow boundaries

Workspace APIs should cover:

- Workspace CRUD and selection.
- Fixed-tab retrieval.
- Group and basket CRUD, membership, refresh, and snapshots.
- Workspace-panel listing and mutation.
- Workspace-agent association and read views.
- Chat creation/listing with workspace context.
- Typed chat-assist commands with provenance.
- Wallet-account connection status and selector state.
- Terminal snapshots and user/workspace-scoped live stream.

All endpoints require authenticated ownership checks. Foreign workspace, chat, panel, group, basket, agent, wallet, or credential IDs return a non-disclosing not-found response. Clients submit opaque IDs and typed fields; they do not submit arbitrary SQL, ownership fields, vault references, or execution policy bypasses.

A typical read-only terminal flow is:

```text
selected workspace + selected wallet + selected/pinned market
  -> backend adapter/session
  -> normalized snapshot/event contract
  -> user/workspace-authorized stream
  -> terminal panels
```

A later execution flow is:

```text
terminal / agent / scheduled intent
  -> typed command validation
  -> wallet + actor + policy + limits + idempotency gate
  -> broker or signer adapter
  -> normalized receipt
  -> immutable audit event
  -> user/workspace stream
```

## Phased delivery

### Phase 0 — foundation and migration

- Verify current Alembic head.
- Add workspace and fixed-tab schema.
- Add chat workspace context.
- Migrate legacy panels without losing layout or provenance.
- Add owner/isolation and migration tests.

### Phase 1 — permanent canvas

- Refactor frontend state so canvas is workspace-keyed and chat is independently keyed.
- Add workspace selector and fixed three-tab canvas navigation.
- Preserve floating panel movement, resize, stacking, minimize/maximize, and restore behavior under workspace ownership.
- Ensure chat switching cannot reset the canvas.

### Phase 2 — groups and baskets

- Add curated group CRUD and membership.
- Add allow-listed dynamic query DSL, refresh, versioned snapshots, and stale indicators.
- Add wallet/market baskets with compatible group/entity references.
- Add bounded expansion and cycle tests.
- Allow result snapshots to seed groups with explicit provenance.

### Phase 3 — workspace-aware chat and Agents

- Build typed workspace actions for chat assistance.
- Add workspace-agent associations and Agents tab views.
- Preserve the existing `/v2/agents` authority and ownership model.
- Design/refactor all agent execution entry points toward the shared gate without enabling live orders yet.

### Phase 4 — wallet connections and read-only terminal

- Add multiple wallet account records and selector UI.
- Add separate API-credential and signing connection flows backed by encrypted vault references.
- Add normalized positions, open orders, fills, orderbook, and market-depth adapters.
- Add selected-versus-pinned market behavior and stale/reconnect states.

### Phase 5 — guarded execution

- Replace refusal-only broker paths with tested adapters.
- Add armed-wallet policies, limits, idempotency, immutable audit, and emergency disarm.
- Route terminal, agent, and scheduled/strategy submissions through the one gate.
- Enable auto-submit only for explicitly configured actors and wallets.

## Testing and acceptance criteria

### Workspace and migration

- A user can create, rename, select, and delete only their own named workspaces.
- Every workspace has exactly one Wallet Groups, Market Groups, and Agents tab.
- Legacy chats and panels migrate without losing messages, runs, result references, geometry, z-index, state, or ownership isolation.
- Switching chats changes assistant history only; switching workspaces changes the canvas intentionally.
- Same-user and cross-user workspace/panel mutations are isolated.

### Groups and baskets

- Curated groups preserve explicit members.
- Dynamic groups use only the allow-listed DSL and parameterized backend queries.
- Refreshes create reproducible snapshots and show stale state when appropriate.
- Wallet baskets reject market members; market baskets reject wallet members.
- Cycles and unbounded group expansion are rejected.
- No basket API or schema contains executable order semantics.

### Agents and safety

- Existing agents appear only when owner-authorized and associated with the workspace.
- No agent path can call a broker outside the shared execution gate.
- Disarmed wallets and policy violations block execution.
- Duplicate idempotency keys do not submit twice.
- Execution writes immutable audit records and supports emergency disarm.

### Terminal

- Wallet 1/2/3 selection changes all account-private terminal data consistently.
- Raw credentials never appear in browser payloads, logs, messages, or model context.
- Positions, open orders, fills, orderbook, and depth carry source timestamp and stale/reconnecting state.
- Canvas market selection changes the terminal only when unpinned.
- Pinned terminal markets remain stable across canvas/chat changes.
- Discovered-wallet analytical positions and connected-user positions remain separate contracts.

### Verification commands

The implementation plan should run the focused backend migration/repository/API tests, focused frontend component/hook tests, full frontend tests, lint, and production build. Browser acceptance should cover at least desktop, tablet, and narrow layouts; chat switching, workspace switching, panel reload, fixed tabs, group/basket filters, wallet selector, market pinning, stale terminal states, keyboard access, and no horizontal overflow.

## Critical files and reusable boundaries

- `src/research/repository.py` — reuse owner-join persistence patterns; refactor panel ownership.
- `src/research/analytics.py` and `src/research/tools.py` — reuse parameterized analytics and immutable result snapshots.
- `src/research/orchestrator.py` and `src/research/llm.py` — reuse bounded provider/tool orchestration; add workspace context and typed actions.
- `src/api/routers/research.py` — extend authenticated workspace/chat APIs.
- `src/api/routers/agents.py` — reuse existing agent ownership and CRUD semantics.
- `src/agents/dispatch.py` and `src/agents/execution.py` — route direct dispatch through the future shared execution gate; preserve dry-run/refusal defaults.
- `frontend/src/hooks/useResearchHub.ts` — split workspace state from chat state.
- `frontend/src/app/hub/ResearchHub.tsx` — render independent workspace canvas and chat rail.
- `frontend/src/components/research/PanelCanvas.tsx` and `frontend/src/hooks/usePanelLayout.ts` — reuse floating interactions with workspace identity.
- `frontend/src/components/research/PositionsBar.tsx` and the current trading panel — preserve honest mock/unavailable behavior until live normalized data exists.
- `alembic/versions/` — verify current head before adding the workspace migration.

## Risks and mitigations

- **Legacy ownership migration:** use idempotent, owner-scoped backfill and preserve source provenance; do not merge canvases implicitly.
- **Dynamic freshness:** retain immutable snapshots, canonical definitions, refresh timestamps, and stale indicators.
- **Group/basket cycles:** enforce kind compatibility, cycle detection, depth/member caps, and deterministic expansion.
- **Credential compromise:** keep vault references and decryption server-side; separate API and signer permissions; never expose secrets to browser/model.
- **Adapter staleness/reconnect:** include source timestamps, sequence/version data, connection state, and stale markers in every live contract.
- **Agent bypass:** make the shared execution gate the only broker entry point and test direct dispatch rejection.
- **Duplicate orders:** require idempotency keys and immutable intent/receipt/audit records.
- **Concurrent workspace edits:** use owner-scoped optimistic updates/version checks and serialized panel mutations where needed.
- **Address normalization:** store normalized address plus network/chain and retain a display form without treating labels as identity.

## Final design decision

Adopt the workspace-first canonical model. The permanent canvas is workspace-owned; chats are workspace-scoped assistant histories; groups and baskets are typed non-executable workspace resources; Agents reuses existing owner-scoped automation; live terminal data is backend-normalized and multi-wallet; and all future execution routes through an armed-wallet policy/audit gate. Implement the permanent workspace foundation first, then add groups/baskets, live read adapters, and execution in separate verified phases.
