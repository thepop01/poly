# Product Roadmap: Agents, AI Terminal, Kalshi Arbitrage, Baskets

> **Not an implementation plan — this is the decomposition/sequencing doc.** Each phase links to (or will link to) its own detailed plan under `docs/superpowers/plans/`. Implement one phase-plan at a time.

**North star:** A user-friendly, multi-venue (Polymarket + Kalshi) prediction-market platform where users build **autonomous rule-based agents**, converse with an **AI terminal** to analyze data and deploy strategies, detect **cross-venue arbitrage**, and explore **interlinked market baskets** with AI insights. Explicitly *not* an elastic.ai clone.

**Guiding constraints (from 2026-07-17 product session + codebase exploration 2026-07-18):**
- Priority order: **(1) Agents/Strategies/Bots → (2) AI Terminal → (3) Kalshi Compare/Arbitrage → (4) Baskets.**
- Deferred: news terminal; scheduled market capture.
- Both venues are **read-only today.** Real order execution is a **dormant seam** everywhere — designed now, wired to keys later.
- **No LLM client exists in the repo yet** (the "category_classifier" is pure regex). Phase 2 introduces it; the Phase 3 matcher reuses it.
- **No auth/authorization model exists for mutating actions.** Agents that can (eventually) move money must be gated behind an explicit owner + approval model from day one.

---

## Why decompose into 4 sub-plans

Each subsystem produces working, testable software on its own and has a clean interface boundary:

| Phase | Subsystem | Depends on | Ships independently? |
|-------|-----------|------------|----------------------|
| 1 | Strategy/Agent engine (rules, evaluation loop, notifications, dormant execution seam) | existing workers + Polymarket data | ✅ notifications-only agent is fully usable read-only |
| 2 | AI Terminal (LLM client + tool-calling over existing data + strategy authoring) | Phase 1 (to *deploy* strategies) + new LLM client | ✅ read-only "ask questions about the data" ships before strategy authoring |
| 3 | Kalshi integration: Compare + Arbitrage | new `kalshi_client`, Phase 2's LLM client (matcher) | ✅ Compare table ships before Arbitrage edges |
| 4 | Baskets: interlinked markets + AI what-if insights | Phase 2 LLM client; optionally Phase 3 cross-venue markets | ✅ manual baskets ship before AI insights |

The **execution seam** (`ExecutionBroker` interface) is defined once in Phase 1 and reused by Phases 3–4. No phase places a real order until keys + an explicit go-live decision exist.

---

## Phase 1 — Strategy & Agent Engine  *(detailed plan: `2026-07-18-phase1-agent-engine.md`)*

**Goal:** Users create **agents** = (a saved **strategy** of conditions) + (a set of **actions**). A background worker evaluates active agents against live Polymarket data each cycle; when conditions fire, it runs the actions (notify now; trade via a dormant broker later). Every trade action routes through an `ExecutionBroker` whose only implementation today is `DryRunBroker` (logs the intended order, never sends).

**Key building blocks:**
- **Condition DSL** — a small, safe, JSON-serializable expression model (no `eval`): `{field, op, value}` leaves combined with `AND`/`OR`. Fields drawn from a whitelisted market-metric schema (price, 24h volume, liquidity, price-change-%, time-to-resolution, etc.).
- **Schema** (Alembic): `agents`, `agent_conditions` (or JSONB rule tree on `agents`), `agent_actions`, `agent_events` (audit log of every evaluation that fired), `notifications`.
- **Evaluation worker** `agent_evaluator.py` — supervised by the existing orchestrator, polls active agents, evaluates rule trees against a market snapshot, writes `agent_events`, dispatches actions.
- **Execution seam** — `ExecutionBroker` ABC + `DryRunBroker`. `PolymarketBroker`/`KalshiBroker` are stubs raising `NotConfiguredError`.
- **Ownership/auth gate** — agents have an `owner_id`; trade actions require `agent.trading_armed = TRUE` (default FALSE) *and* a configured broker. Read-only notify agents need neither.
- **API** `/api/v2/agents` CRUD + `/api/v2/agents/{id}/events` + `/api/v2/notifications`.
- **Frontend** `/agents` list + builder form (condition rows → actions) + notifications feed.

**Ships as:** notification-only agents against live Polymarket data, end to end. Trading is visibly "armed/disarmed" but always dry-run.

---

## Phase 2 — AI Terminal  *(plan TBD: `2026-07-18-phase2-ai-terminal.md`)*

**Goal:** A conversational terminal in the app that answers questions about the platform's own data, runs reports, and (tier 2) authors/deploys Phase-1 strategies from natural language.

**Key building blocks:**
- **LLM client** `src/utils/llm_client.py` — provider-agnostic wrapper (OpenAI/Anthropic via env), the *first* LLM dependency in the repo. Reused by Phase 3 matcher + Phase 4 insights.
- **Tool-calling layer** — a whitelisted set of read tools that map to existing endpoints/queries (top wallets, market lookup, wallet positions, alpha calls, strategy backtest). The LLM never touches the DB directly — only these tools.
- **Terminal session API** `/api/v2/terminal` (stateful conversation, streamed responses) + `/terminal` frontend page.
- **Strategy authoring (tier 2):** a `create_agent` tool that turns "alert me when any NBA market moves >10% in an hour" into a Phase-1 agent draft for user confirmation (never auto-arms trading).

**Ships as:** read-only Q&A terminal first; strategy authoring second.

---

## Phase 3 — Kalshi Integration: Compare & Arbitrage  *(plan TBD: `2026-07-18-phase3-kalshi-arbitrage.md`)*

**Goal:** Detect and display equivalent markets across Polymarket ↔ Kalshi (Compare), then price cross-venue dislocations (Arbitrage). Auto-execution stays a dormant seam.

**Architecture (from design session):** *match slowly, price fast.*
```
INGEST            MATCH (slow, hourly)      PRICE (fast, seconds)     SERVE
kalshi_client  →  market_matcher         →  edge_engine            →  /api/v2/aggregator/
gamma_client      (cheap filter → LLM      (order books on            compare
(exists)          confirm equivalence)      confirmed pairs only)      arbitrage
                  writes equivalent_pairs   writes live_edges
```
- **`kalshi_client.py`** — mirror of `gamma_client.py` (`ParsedMarket`/`ParsedEvent` shape) against Kalshi's public API.
- **`market_matcher.py`** (slow worker) — candidate generation (embeddings or fuzzy/entity filter) → **LLM confirmation** ("same outcome, same resolution date, same criteria?") → `equivalent_pairs` catalog. Reuses Phase 2 LLM client.
- **`edge_engine.py`** (fast worker) — for each confirmed pair, pull both order books, compute **both** a headline best-ask edge and a full-depth capacity-aware edge; write `live_edges`.
- **API/UI** `/api/v2/aggregator/compare` + `/arbitrage`; `/aggregator` frontend with side-by-side compare and an edge/capacity arbitrage table.
- **Agents integration:** arbitrage becomes a new condition-field source, so Phase-1 agents can watch edges (notify now; dual-leg execute via the dormant broker later).

**Ships as:** Compare table first; Arbitrage edges (headline + capacity) second.

---

## Phase 4 — Baskets with AI Insights  *(plan TBD: `2026-07-18-phase4-baskets.md`)*

**Goal:** Group interlinked markets and surface AI-generated causal insights ("if X resolves YES, what happens to Y?", "what other factors move this market?").

**Key building blocks:**
- **Schema** `baskets`, `basket_markets` (venue-agnostic market refs so Phase-3 Kalshi markets slot in).
- **Manual baskets first** — create/curate a group, show aggregated price/volume/time.
- **AI insight layer (tier 2)** — Phase-2 LLM client generates relationship explanations + what-if scenarios over the basket's markets; cached like other slow LLM output.

**Ships as:** manual interlinked baskets first; AI what-if insights second.

---

## Cross-cutting decisions locked in

1. **Execution is always dormant until keys + explicit arm.** `ExecutionBroker` ABC defined in Phase 1; only `DryRunBroker` is live. This is a security-sensitive seam — no silent order placement, ever.
2. **One LLM client, introduced in Phase 2, reused everywhere.** Don't add a second.
3. **Slow-match / fast-price split** applies wherever LLM cost meets live prices (Phase 3 matcher, Phase 4 insights): persist LLM output on a slow cycle, poll prices fast.
4. **Venue-agnostic market refs** from Phase 3 onward so Kalshi + Polymarket markets coexist in agents and baskets.
5. **Follow existing conventions:** raw-SQL Alembic migrations, `APIRouter(prefix="/v2/...")` routers registered in `src/api/main.py`, workers supervised by `src/orchestrator.py`, asyncpg pool from `src.db.get_pool()`, pytest.

---

## Open questions to resolve before each later phase (not blocking Phase 1)

- **Phase 2:** which LLM provider + budget ceiling? streaming transport (SSE vs WS — repo already has a WS broadcaster)?
- **Phase 3:** Kalshi API tier (public data only vs authenticated)? candidate-generation method (hosted embeddings vs local fuzzy/entity) given the no-new-heavy-dep preference?
- **Phase 4:** are AI insights point-in-time (cached snapshots) or refreshed on price moves?
