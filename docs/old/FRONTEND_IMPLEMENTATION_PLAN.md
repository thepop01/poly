# Frontend Implementation Plan — Reference Parity (Phase: No-Kalshi / No-LLM)

> Companion to `UI_COMPARISON_REPORT.md`. Scope: restyle and restructure the existing
> Polymarket-tracking frontend to match the PolyScope reference look and fill the
> buildable gaps.
>
> **Explicitly out of scope for now** (missing integrations):
> - "Ask me anything" persistent chat bar + AI Terminal / chat page (no LLM yet)
> - Aggregator Compare / Arbitrage pages (no Kalshi yet)
> - Trade execution page, Portfolio exchange connections, Baskets, News
>
> When those integrations land, the shell built here (header bar, sidebar slots)
> already reserves space for them — nothing needs re-architecting.

**Visual target:** PolyScope (dark reference) is the style guide for everything in
scope. Elastics patterns are only borrowed where they don't depend on excluded
features (avatars, threshold filter dropdowns).

---

## Phase 0 — Design tokens + shared component kit

Foundation for every later phase. No page behavior changes.

### 0.1 Token pass (`app/globals.css`)
- **Decision needed:** accent color. PolyScope is green-dominant (logo, active nav,
  tier badges, PnL all share one mint/teal green). Recommendation: adopt
  **teal/green `#34D399`-family as primary**, demote amber to a "signal/highlight"
  color (reference uses amber only for "Biggest signal"). Keep violet as-is or drop.
- Darken background one step toward near-black (`#0B0F14` page / `#11161C` surface)
  to match PolyScope's contrast; current Slate 900 reads blue-gray.
- Remove dead `Exo 2` / `Orbitron` font imports (unused).
- Add tokens: `--color-tier-curated` (green pill), `--color-tier-global` (gray pill),
  badge-outline variants (TRADE / DEPOSIT / BUY / SELL).
- Increase table row height (`.data-table td` padding 14px → 16px) to match the
  reference's roomier density.

### 0.2 New shared components (`components/ui/`)
| Component | Spec (from screenshots) | Used by |
|---|---|---|
| `StatCard` | Muted label top-left, ghost icon top-right, large mono value (color prop), muted subtitle. Grid of 4. | Dashboard, Alpha Calls, Curated, Wallets |
| `StatCardRow` | Responsive 4→2→1 grid wrapper | same |
| `TierBadge` | `TIER 2` = green filled pill, `TIER 1` = gray pill, mono uppercase | Wallet tables, feed |
| `TypeBadge` | Outline pill: TRADE (teal), DEPOSIT (blue), BUY (green text), SELL (red text) | Feed, dashboard |
| `PillTabs` | Pill-style tab row with optional counts ("All (12)") and active fill | Dashboard sub-nav, feed tabs, tier filter |
| `Avatar` | Colored circle + first letter (reuse existing `.avatar-gradient-*` classes, currently unused) | Wallet cells |
| `PageHeader` | Title + one-line description, standardized (replaces per-page ad-hoc headers) | All pages |
| `EmptyState` | Icon + line + optional CTA | All tables |

### 0.3 Refactors
- `SourceBadges.tsx`, `WalletCell.tsx`, `WalletTable.tsx`, `Pagination.tsx` stay —
  restyle only to new tokens. `WalletCell` gains optional `alias` + `Avatar`.

**Files:** `globals.css`, ~8 new files in `components/ui/`, touch 4 existing
components. No backend work.

---

## Phase 1 — App shell (sidebar + top header bar)

### 1.1 Sidebar rework (`components/Sidebar.tsx`)
- **Grouped sections** with muted headers, PolyScope-style:
  - `Discovery`: Wallets (→ `/wallets`), Curated, Custom Wallets, Activity (alpha-calls)
  - `User Hub`: Overview (→ new `/dashboard`), My Tracker, Agents
- Active item: filled pill (surface-2 bg, white text) instead of amber border box.
- **Collapse toggle**: chevron/panel icon; collapsed = 56px icon rail with tooltips.
  Persist state in `localStorage`. Content area flexes automatically.
- **Bottom block** (Elastics pattern, no chat): user identity — Discord avatar +
  username when logged in, "Login with Discord" button when not; wallet-connect
  button below it; "Scanners live" green-dot status line stays at the very bottom.
- **Move out**: notifications bell (→ header bar, Phase 1.2).

### 1.2 New top header bar (`components/HeaderBar.tsx`, mounted in `app/layout.tsx`)
- Left: sidebar collapse toggle + current page title/description (from a small
  route→title map or context set by each page).
- Right: notifications bell + dropdown (move existing logic from Sidebar, keep the
  WebSocket wiring in a shared hook `hooks/useTradeNotifications.ts`), live-status
  dot. Reserved slot order matches Elastics (balances/credits chips slot in later).

**Files:** `Sidebar.tsx` (rewrite), new `HeaderBar.tsx`, `layout.tsx`, new hook.
No backend work.

---

## Phase 2 — Dashboard / Overview page (new `/dashboard`)

Replicates `dashboard 1.png`. Root `/` redirect changes: `/wallets` → `/dashboard`.

### 2.1 Layout
- `PillTabs` sub-nav: **Overview | Tracked Wallets (n) | Agents** (AI Terminal /
  Bots / Market Info tabs deferred — do not render placeholders).
  - Tracked Wallets tab = existing watchlist data in the shared `WalletTable`
    (dashboard 2 look: #, Wallet, Tier, PnL, ROI, Balance, Volume, Sources, Last Trade).
  - Agents tab = embed the existing agents list (reuse `/agents` page components,
    extracted into `components/agents/AgentList.tsx`).
- Overview tab, top row — 4 × `StatCard`:
  1. **Tracked wallets** — count + combined PnL subtitle → `getWatchlist()` + stats
  2. **Active agents** — count + runs today → `listAgents()` / `listNotifications()`
  3. **Alpha signals** — count in last feed window → feed counts (see 3.3)
  4. **Top performer** — best watchlist wallet by PnL (swap for "Bot performance"
     when bots exist)
- Below, two-column (7/5 split):
  - **Watchlist snapshot** card: top 5 watchlist wallets, name/address left, green
    PnL + gray balance right. Links to wallet detail.
  - **Latest alpha calls** card: top 5 feed items — `TypeBadge`, wallet, market
    title line, amount + `timeAgo` right. **"Open full feed ↗"** → `/alpha-calls`.

### 2.2 Backend needs
- None hard-blocking: all data exists (`getWatchlist`, `getWalletStats`,
  `getSmartMoneyAlerts`, `listAgents`). A single `GET /api/v2/dashboard/summary`
  aggregate endpoint is a nice-to-have to avoid 4 client round-trips — optional.

**Files:** `app/dashboard/page.tsx` + 3 panel components, edit `app/page.tsx`
redirect, extract `AgentList.tsx`.

---

## Phase 3 — Alpha Calls page upgrade (`app/alpha-calls/page.tsx`)

Replicates `activity tab.png`. Biggest existing-page delta.

### 3.1 Unified table (frontend)
- Replace the either/or Deposits|Trades tabs with `PillTabs`: **All (n) | Trades (n)
  | Deposits (n)** — All is default; deposits render "—" in trade-only columns.
- New column set: `Type` (TypeBadge) · `Wallet` (address + alias/Avatar) · `Tier` ·
  `Market` (title + Yes/No outcome subline; "USDC deposit" for deposits) · `Side`
  (BUY green / SELL red) · `Price` (¢) · `Amount` · `Tx` (short mono hash →
  polygonscan) · `Time` (relative). Keep the Track button + profile links in a
  row-hover action cluster; keep category/subcategory as filters, drop them as
  columns (reference doesn't show them).
- 4 × `StatCard` above the tabs: Live events (window count + "> $5K" subtitle),
  Large trades (count), Large deposits (count + inbound $ sum), **Biggest signal**
  (amber value + wallet subtitle).

### 3.2 Tier semantics fix
- Current page derives "Tier 1–5" from trade size — collides with the wallet-quality
  TIER 1/2 concept used by curated. Rename size tiers to **Size buckets** (e.g.
  `$5K+ / $25K+ / $100K+` chips) in the filter, and show the *wallet's* tier in the
  Tier column via `TierBadge`.

### 3.3 Backend needs (small, real)
- Feed rows: `alpha_calls_v2` already selects `condition_id`, `outcome`,
  `title as market_title` — confirm the route the frontend calls returns them, and
  **add `side` and `price`** for trade rows if absent (data exists in `trades` /
  `whale_trades`).
- **Counts + window aggregates endpoint** for the stat cards and tab counts:
  `GET /api/v2/alpha-calls/summary` → `{trades, deposits, deposit_inflow,
  biggest: {amount, wallet, alias}}` over the feed window.
- Wallet tier + alias joined into feed rows (needed for Tier column).

---

## Phase 4 — Leaderboard pages (`/wallets`, `/wallets/curated`, `/wallets/custom`)

Replicates `leaderboard 3.png` / `dashboard 2.png`.

### 4.1 Curated page
- 4 × `StatCard`: Tracked universe (count + "n curated Tier 2"), Combined PnL,
  Capital deployed (Σ balances), Top performer (alias + PnL).
- Filter row, single line: topic pills left (**All | Crypto | Politics | Sports |
  Pop Culture | Science** — categories already exist in the curated data model),
  **All Tiers | Tier 1 | Tier 2** pills + search ("alias or address") right.
- Table: add **Tier** (`TierBadge`), **Win Rate**, **Open** (open positions count),
  **Last Trade** columns; alias-first `WalletCell` with `Avatar`.

### 4.2 Main `/wallets` page
- Keep the 5 lifecycle tabs (All/Standard/Low Balance/New/Hibernated) — they're a
  real product feature the references don't have — but restyle as `PillTabs`.
- Add a 4-card stat row above (counts per lifecycle bucket from existing
  `getWalletCounts()` + combined PnL/volume).
- Threshold filter dropdowns (Elastics `leaderboard 2.png` pattern): PnL / Volume /
  Balance with `All | >$1K | >$10K | >$100K | >$1M` options — pure query-param work
  if the v2 wallet list endpoint accepts min filters (add if missing).
- Optional (backend-gated): PnL 30D / Volume 30D columns — the windowed-stats
  backend work exists on this branch; surface it as two sortable columns.

### 4.3 Backend needs
- Curated summary endpoint (or compute client-side from the full curated list —
  acceptable at 11–100 wallets).
- Win Rate / Open count / Last Trade in the wallet list payloads if not present.
- `min_pnl` / `min_volume` / `min_balance` params on `/api/v2/leaderboard/wallets`.

---

## Phase 5 — Supporting pages, consistency pass

- **`/tracker` (My Tracker)**: restyle with `PageHeader`, `StatCard` row (list
  count, combined PnL), shared `WalletTable`. It becomes the "Tracked Wallets"
  dashboard tab's fuller page.
- **`/agents`**: restyle to card grid matching reference badge/pill language; keep
  the form builder. Empty state via `EmptyState` ("No agents yet" — mirrors
  Elastics).
- **`/wallet/[address]` detail**: token restyle only (no layout change this phase).
- Delete/redirect any legacy pages superseded by the dashboard (`/wallets/global`
  if the tabbed page fully covers it).
- Sweep: every page uses `PageHeader`, tokens, `EmptyState`; no ad-hoc hex colors.

---

## Sequencing & effort

| Phase | Depends on | Backend work | Rough size |
|---|---|---|---|
| 0 Tokens + kit | — | none | M |
| 1 Shell | 0 | none | M |
| 2 Dashboard | 0, 1 | optional summary endpoint | M |
| 3 Alpha Calls | 0 | small (side/price/tier in feed, summary endpoint) | L |
| 4 Leaderboards | 0 | small (columns + min filters) | L |
| 5 Consistency | 0–4 | none | S–M |

Phases 0→1 are pure-frontend and unblock everything; ship them first as one PR.
Phases 2, 3, 4 are independent of each other and can proceed in any order (2 is the
most visible win; 3 has the highest data value). Phase 5 last.

## Decisions to confirm before Phase 0
1. **Accent color**: switch primary from amber to PolyScope green (recommended), or
   keep amber identity and use green only for data/PnL.
2. **Root route**: `/` → `/dashboard` once Phase 2 ships (recommended), or keep
   `/wallets`.
3. Curated topic categories: confirm the five reference topics match the curated
   tagging taxonomy already in the DB (`migrate_curated_tags.py` suggests tags exist).

## Explicit deferrals (revisit when integrations land)
- LLM: AI Terminal page, persistent Ask-me-anything bar, chat-driven baskets,
  strategy-catalog chat. Header bar and sidebar already reserve slots.
- Kalshi: Aggregator (Compare/Arbitrage), venue icons/delta chips, portfolio
  exchange rows, Trade page order book/execution.
- Bots: "Bot performance" stat card + Bots dashboard tab (slot reserved on the
  dashboard sub-nav).
