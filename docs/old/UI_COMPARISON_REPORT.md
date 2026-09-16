# UI/Frontend Comparison Report: Current vs. Reference

> Verified 2026-07-19 against the 14 screenshots in `image/` and the actual code in
> `frontend/src/` (branch `feat/curated-windowed-stats`).

## Reference Sources & Image Inventory

Two distinct products appear in the screenshots:

| Reference | Theme | Images |
|---|---|---|
| **PolyScope** — smart-money tracker (dark) | Near-black, green/teal accent | `dashboard 1.png`, `dashboard 2.png`, `activity tab.png`, `leaderboard 3.png` |
| **Elastics AI** — prediction-market platform (light) | White/gray, monochrome + violet accent | `leaderboard 2.png`, `agent chat.png`, `agent can do.png`, `agent strategies.png`, `trade with agent .png`, `arbritrage.png`, `compare .png`, `portfolio.png`, `basket.png`, `basket 1.png` |

PolyScope is the visual model for the *tracking* side (dashboard, leaderboards, alpha
feed). Elastics is the model for the *action* side (AI chat, trade, portfolio,
aggregator, baskets). This maps directly onto the product priorities: T1 = agents /
strategies / bots / AI terminal, T2 = Kalshi compare/arb, then baskets.

---

## 1. Design System

| Aspect | PolyScope (ref) | Elastics (ref) | Current (PolyTracker) |
|---|---|---|---|
| Background | Near-black (~#0B0E11), cards slightly lighter | Light gray page, white cards | Slate 900 `#0F172A`, surface `#1E293B` |
| Accent | Mint/teal green (used for PnL, tier badges, logo, active nav) | Neutral black/gray; violet only for AI-credit chip | Amber `#F59E0B` primary + violet `#8B5CF6` accent |
| Numerals | Monospace for every number (PnL, prices, addresses) | Proportional sans, tabular numbers | Fira Code mono for numbers — already matches |
| Positive/negative | Green `+$1.91M` / red | Green / red | Green / red — matches |
| Corner radius | Large (12–16px) on cards, pill badges | Large, very soft; pill chips everywhere | 8–12px — close |
| Density | Roomy rows (~52px), generous card padding | Roomy | Denser (py-2.5 rows) — slightly tighter than both refs |

**Gaps**
- Exo 2 / Orbitron font references removed (verified — not in globals.css).
- Reference stat cards, badges, and chips are a reusable kit; ✅ StatCard exists and is used in dashboard; TierBadge/Chip components still missing for other pages.

---

## 2. App Shell (sidebar, header, global chat)

### PolyScope shell
- Sidebar with **section headers**: "Discovery" (Curated Wallets, Might Cook, Alpha
  Calls) and "User Hub" (Overview, Tracked Wallets, Agents, Bots, AI Terminal, Market
  Info).
- Active item = filled dark pill, white text; icons on every item.
- **Collapse toggle** at the top of the content area (panel icon).
- Page header inside content: bold title + one-line gray description.
- Footer: "scanners live" green dot + `demo` chip.

### Elastics shell
- Sidebar: Dashboard, Elastics AI, Agents, Trade, Discover, News, Aggregator,
  Baskets, Portfolio; bottom group Community / Twitter / Support; **user avatar +
  email** pinned at the very bottom. Collapse toggle in the header.
- **Top header bar on every page**: page title, search (contextual), AI-credit chip
  (`$4.81`), wallet balance chip (`$0.00`), notification bell, filter icon.
- **Persistent "Ask me anything" chat input floating bottom-center of every page**
  (Discover, Trade, Aggregator, Portfolio — not just the AI page). This is the single
  most distinctive Elastics pattern.

### Current shell (`components/Sidebar.tsx`)
- 192px fixed sidebar, **no collapse**, no section headers. Nav: Activity, Wallets,
  Curated, Custom Wallets, My Tracker, Agents.
- Notifications bell, wallet-connect, Discord login, and "Feed Live" all live in the
  **sidebar footer** — references put balances/bell in a **top header bar** and keep
  the sidebar footer for identity (user avatar/email) and community links.
- No top header bar at all; each page renders its own heading.
- No global AI input.

**Gaps**
1. No sidebar collapse toggle (both refs).
2. No grouped nav sections ("Discovery" / "User Hub" style).
3. No top header bar (title + balances + bell + filters).
4. No persistent bottom "Ask me anything" bar (Elastics).
5. No user identity block at sidebar bottom (avatar + email).
6. Missing nav destinations: ~~Overview/Dashboard~~ ✅ exists, AI Terminal, Bots, ~~Might Cook~~ (deprecated in favor of /wallets tabs), 
   Market Info (PolyScope); Trade, News, Aggregator, Baskets, Portfolio (Elastics).

---

## 3. Dashboard / Overview — `dashboard 1.png`, `dashboard 2.png`

**Reference (PolyScope)**
- Page-level **pill sub-nav**: Overview | Tracked Wallets (4) | Agents | Bots | AI
  Terminal | Market Info — the whole User Hub lives under one Dashboard page.
- Overview tab:
  - **4 stat cards**: Tracked wallets (4, "+$3.18M combined PnL"), Bot performance
    (**+$14.9K** in green, "2/3 bots running"), Active agents (2, "38 runs today"),
    Alpha signals (5, "In the last feed window"). Pattern: muted label top-left,
    ghost icon top-right, big mono number, muted subtitle.
  - **Watchlist snapshot** card: rows of wallet name + truncated address on the left,
    green PnL + gray balance right-aligned.
  - **Latest alpha calls** card: TRADE/DEPOSIT outline badges, wallet name, market
    line, amount + relative time right-aligned, **"Open full feed ↗"** button.
- Tracked Wallets tab: full-width table — #, Wallet (name + `0x…` address), **Tier
  badge** (`TIER 2` green pill / `TIER 1` gray pill), PnL, ROI (both green mono),
  Balance, Volume, Win Rate, Open, **Sources chips** (Leaderboard / Trade Scanner /
  User Added), Last Trade ("2h ago").

**Current** (`app/dashboard/page.tsx`)
- ✅ **EXISTS** — `/` redirects to `/dashboard` (was `/wallets` in earlier session).
- ✅ Pill sub-nav with 3 tabs: Overview | Tracked Wallets (count) | Agents (count).
- ✅ **4 stat cards** in Overview tab: Tracked wallets (count + combined PnL), Active
  agents (count + runs today), Alpha signals (feed count + subtitle), Top performer
  (username + PnL). Uses `StatCard` + `StatCardRow` components (`components/ui/StatCard.tsx`).
- ✅ **WatchlistSnapshot** component shows top 6 wallets (username, address, PnL, balance).
- ✅ **AlphaCallsSnapshot** component shows 5 latest feed items (type badge, username,
  market, amount, time) with "Open full feed →" link.
- Tracked Wallets tab shows full watchlist; Agents tab shows agent list or empty state.

**Gaps from reference**
- Bot performance card missing (no bots feature yet).
- No Bots or AI Terminal tabs in the pill nav (features don't exist).
- Watchlist snapshot doesn't show ROI, Volume, Win Rate, Open, Sources, Last Trade — 
  just name/address/PnL/balance (simpler than reference table).
- Alpha calls snapshot doesn't show market titles (feed API doesn't join market data yet).

---

## 4. Curated Wallets Leaderboard — `leaderboard 3.png`

**Reference (PolyScope)**
- Header: "Curated Wallets — Global (Tier 1) and curated (Tier 2) wallets ranked by
  performance".
- **4 stat cards**: Tracked universe (11, "7 curated Tier 2"), Combined PnL
  (+$4.45M green, "All-time realized"), Capital deployed ($7.61M, "Current
  balances"), **Top performer** (OracleWhale, "+$1.91M PnL").
- Filter row: topic pills left (All | Crypto | Politics | Sports | Pop Culture |
  Science), **tier pills** (All Tiers | Tier 1 | Tier 2) + **search "alias or
  address"** right-aligned on the same row.
- Table: #, Wallet, Tier badge, PnL, ROI, Balance, Volume, Win Rate, Open, Sources
  chips, Last Trade. Tier 2 rows ranked above Tier 1.

**Current** (`app/wallets/page.tsx`, `wallets/curated`, `wallets/custom`)
- Tabbed table with **5 tabs**: All / Standard / Low Balance / New / Hibernated
  (lifecycle-based, not topic-based).
- Source filter pills and Source badges already exist (`SourceBadges.tsx`) — this
  matches the reference "Sources" column well.
- Sortable columns, pagination — good foundation via `WalletTable`.

**Gaps**
| Gap | Detail |
|---|---|
| Stat cards above table | None; reference leads every list page with 4 cards |
| Wallet-quality tier system | Reference `TIER 1`/`TIER 2` badges + tier filter pills; current has none on wallet tables |
| Topic category pills | Current tabs are lifecycle (Standard/New/Hibernated); reference adds Crypto/Politics/Sports/Pop Culture/Science |
| Win Rate, Open positions, Last Trade columns | Not in current table |
| Wallet alias names | Reference shows human aliases (OracleWhale) above address; current shows address-first |
| Search placement | Reference: inline right of filter pills; current: separate |

---

## 5. Alpha Calls / Activity Feed — `activity tab.png`

**Reference (PolyScope)**
- **4 stat cards**: Live events (12, "Trades + deposits over $5K"), Large trades (8,
  "Grouped partial fills"), Large deposits (4, "$974.5K inbound"), **Biggest signal
  ($512K in amber/orange** — the one non-green accent — "FreshWhale · $1.59M total
  flow").
- Tabs with counts: **All (12) | Trades (8) | Deposits (4)** — combined view is the
  default.
- Unified table: Type badge (TRADE teal outline / DEPOSIT blue outline), Wallet
  (name + address), Tier badge, **Market (title + Yes/No outcome subline; "USDC
  deposit" for deposits)**, **Side (BUY green / SELL red)**, **Price (31¢)**, Amount,
  **Tx (mono short hash)**, Time. Deposits show "—" in trade-only columns.

**Current** (`app/alpha-calls/page.tsx`)
- Only two mutually exclusive tabs (Deposits | Trades), no combined "All", no counts.
- Has: tier badges (Tier 1–5 **by trade size**, not wallet quality), category/
  subcategory chips, size, balance, open-position value, wallet address, polygonscan
  tx link + Polymarket profile links, Track button, search, pagination.

**Gaps**
| Gap | Detail |
|---|---|
| Stat cards | Missing all 4 |
| Combined All tab with counts | Tabs are either/or today |
| Market column | Trades don't show which market/outcome was traded — biggest content gap |
| Side + Price columns | Not shown |
| Tier semantics | Current tier = f(trade size); reference tier = wallet quality (matches curated tiers). Two different concepts using one word |
| Tx as column | Current has external link icons, reference shows short hash inline |

---

## 6. Discover / Traders — `leaderboard 2.png`

**Reference (Elastics)**
- Sub-tabs: **Markets | Events | Calendar | Traders**.
- Category strip: All, Politics, Elections, Geopolitics, Sports, Esports, Crypto,
  Economy, Finance, Commodities, Tech & Science, Culture, Climate & Weather,
  Mentions, Health… (~16, horizontally scrollable).
- **7 filter dropdowns**: Trading PnL, Unrealized, Volume, PnL 30D, Volume 30D,
  Portfolio, Positions — each with tiers All / >$1K / >$10K / >$100K / >$1M.
- Table: Whale (**colored avatar with initial** + name + address), Trading PnL
  (sortable, green), Unrealized (red when negative), Volume, PnL 30D, Volume 30D,
  Portfolio, Positions.
- Header search "Search for trader…"; persistent Ask-me-anything bar overlaying the
  bottom.

**Current**: `/wallets` covers "Traders" only. No Markets/Events/Calendar tabs, no
threshold filter dropdowns, no avatars, no 30-day windowed columns in the UI (the
backend windowed-stats work exists — surface it here).

---

## 7. AI Chat / Terminal — `agent chat.png`, `agent can do.png`, `agent strategies.png`

**Reference (Elastics AI)**
- Layout: chat-local left panel (+ new chat button, search, **Agents** section with
  "No agents yet" empty state, **Chats** history list) beside the main thread.
- Empty state: centered logo + "Find and act on market opportunities", large input
  ("Ask me anything", attach +, send ↑), **3 quick-action chips** (Search Markets,
  Create Basket, Agents), 3 suggested prompt lines below.
- Responses are rich markdown: bold, rules, headings with emoji, and **tables with a
  hover toolbar (copy / download / expand)**.
- `agent can do.png` shows graceful capability refusal with a "What I *can* do"
  table; `agent strategies.png` shows a strategy catalog table (Momentum Chaser, Mean
  Reversion, Closing Bell Fade, Liquidity Sniper, News Catalyst Buyer, Diversified
  Budget Allocator, Price Band Filter, ROI Gate Compounder) — each strategy is
  one-line explainable. Good target catalog for our strategy templates.
- Chat leads to action: agent offers "Set up a trading agent… / Pull the latest
  news…" as numbered follow-ups.

**Current**: nothing. `/agents` is a form-based rule builder (`AgentBuilder.tsx`)
gated behind Discord login. No chat surface anywhere.

**To build**
- [ ] Chat page (thread + input + suggested prompts + quick actions)
- [ ] Chat/agent left panel with history
- [ ] Markdown rendering with table toolbar (copy/download/expand)
- [ ] Strategy template catalog (the 8 reference strategies are a ready-made spec)
- [ ] Persistent bottom chat input on all other pages that deep-links into this page

---

## 8. Baskets — `basket.png`, `basket 1.png`

**Reference (Elastics)**
- Created conversationally: user states a thesis ("I think there won't be nuclear
  deal between US and Iran, create a basket") → status chip **"Basket created — No
  US-Iran Nuclear Deal · 9 markets"** → explanation paragraph.
- **Inline market cards** in the thread: venue icon, market title, `PRICE 31¢ | 71¢`
  (yes green / no red), category tag, `ENDS IN 3 months`, expand caret, **+ add**
  button.
- **Right-hand Basket panel**: basket name + "Open →", market count, multi-paragraph
  thesis description, list of member markets each with venue icon, price, and a
  remove (—) control.
- Assistant closes with thesis logic bullets and numbered next actions (set up a
  trading agent on the basket / pull news).

**Current**: no basket feature (T2 in the roadmap, after Kalshi arb).

---

## 9. Trade Page — `trade with agent .png`

**Reference (Elastics)**
- **Market header bar**: category chip (SPORTS), venue icon (K = Kalshi), question
  title, dropdown caret, then chips: STATUS Open, VOLUME $95.4M, 24H $20.5M, OPENED
  "about 1 year ago", ENDS IN "about 2 years"; bookmark + star on the right.
- **Three-column body**:
  1. **TradingView-style chart** (Price History): drawing-tool rail, indicators,
     undo/redo, screenshot, timeframe row 5y/1y/3m/1m/5d/1d, %/log/auto toggles,
     volume bars under price line.
  2. **Order Book**: ASKS (red, price/size/cumulative) over SPREAD row (0.4¢, best
     bid) over BIDS (green); scrollable.
  3. **Buy/Sell panel**: Buy|Sell tabs, order-type dropdown (Market), **YES 42¢ /
     NO 58.4¢** segmented toggle, Amount with balance, preset chips **+$1 +$5 +$10
     +$100 Max**, warning card ("This portfolio is not configured…"), full-width
     **Buy Yes** button; below it **Related News | Live Feed** tabs with article/
     tweet cards (favicon, source, type chip, age).
- **Bottom tabs**: Positions | Agents | Open Orders | Trade History | Order History,
  with count + All/Open/Closed filter; persistent Ask-me-anything bar.

**Current**: no trade page, no chart, no order book, no execution UI.

---

## 10. Portfolio — `portfolio.png`

**Reference (Elastics)**
- **Connection banner**: "⚠ Kalshi is not connected — Connect your Kalshi account…"
  with a right-aligned Connect Kalshi button.
- **Per-exchange rows**: Kalshi and Polymarket, each with venue icon, CASH chip,
  POSITIONS chip, settings gear; Polymarket adds **Deposit** (solid) and
  **Withdraw** (outline) buttons.
- **Summary cards row**: Total Portfolio Value, Active Position Value (green), Cash
  Balance, Open Limit Orders.
- **Second row**: Unrealized PnL (`+$0.00` green), Realized PnL, Total Volume — as
  flat wide cells, visually lighter than the cards above.
- Same bottom tab set as Trade (Positions/Agents/Open Orders/Trade History/Order
  History) + All/Open/Closed pills; "No open positions." empty state.

**Current**: wallet-connect exists in the sidebar; no portfolio page.

---

## 11. Aggregator — `compare .png` (Compare), `arbritrage.png` (Arbitrage)

**Reference (Elastics)** — one page, **Compare | Arbitrage** segmented toggle, shared
category strip (All … Transportation), search "events, outcomes, or market titles".

Compare mode:
- Filters: MATCH (Valid only), MIN PRICE GAP, TIME LEFT, **FULL BOOKS ONLY** toggle.
- Each row is a **venue pair**: Kalshi row over Polymarket row (venue icons),
  dotted separator, market titles per venue; shared Outcome cell ("Alaska House
  winner?" + category) and Match chip (● Equivalent).
- **Price (YES/NO)** columns show per-venue prices with **delta chips** — the
  cheaper side outlined in red with the gap (e.g. `16¢ −4¢`).
- Liquidity, Volume, Time Left shown per venue row.

Arbitrage mode:
- Filters: MATCH, MIN EDGE (%), MIN PROFIT ($), ARB CAPACITY, TIME LEFT.
- Columns: Market (+category), Outcome, Match, **Edge (Best Asks)** sortable — %
  and $ stacked, green, **Edge (Full Depth)**, **Strategy** — venue-tagged chips
  `[icon] YES 9.9¢ + [icon] NO 57¢`, **Capacity ($)**, Time Left.

**Current**: nothing. This is the T2 Kalshi work's UI target; the delta-chip pair-row
and strategy-chip patterns are the two components to get right.

---

## 12. Component Kit Gaps (cross-page)

| Component | Seen in | Current |
|---|---|---|
| StatCard (label/icon/number/subtitle) | Every PolyScope page | ✅ `ui/StatCard.tsx` (used in dashboard) |
| TierBadge (TIER 1 gray / TIER 2 green pill) | PolyScope tables | Missing (alpha-calls has size-based tiers only) |
| Source/attribute chip | PolyScope Sources col | ✅ `SourceBadges.tsx` |
| Type badge (TRADE/DEPOSIT outline) | PolyScope feed | Partial (styled differently) |
| Venue icon chip (K / Polymarket logos) | All Elastics market rows | Missing |
| Price pair + delta chip (`16¢ −4¢`) | Compare | Missing |
| Inline market card (venue, price, category, ends-in, +) | Chat/baskets | Missing |
| Order book panel | Trade | Missing |
| TradingView chart wrapper | Trade | Missing |
| Buy/Sell panel with presets | Trade | Missing |
| Chat message + markdown-table toolbar | AI pages | Missing |
| Basket side panel | Baskets | Missing |
| Connection banner + exchange row | Portfolio | Missing |
| Top header bar (balances, bell) | All Elastics pages | Missing |
| Persistent Ask-me-anything input | All Elastics pages | Missing |
| Sidebar collapse + user block | Both | Missing |
| Avatar with initial (colored circle) | Elastics traders | Missing (CSS gradients exist, unused) |
| Sortable-column arrows on money columns | Both | ✅ `WalletTable` |
| Pagination | — | ✅ `Pagination.tsx` |
| PillTabs (sub-nav) | PolyScope dashboard | ✅ `ui/PillTabs.tsx` (used in dashboard) |

---

## 13. Priority Roadmap

Aligned with product priorities (T1: agents/strategies/bots/AI terminal; T2: Kalshi
compare/arb, then baskets):

### HIGH (T1 surface area)
1. **~~Dashboard/Overview~~ ✅ DONE** — stat cards + watchlist snapshot + alpha-calls snapshot
   already built in `/dashboard`. Minor gaps: bot performance card, market titles in feed snapshot.
2. **AI Terminal / chat page** — thread UI, quick actions, suggested prompts,
   markdown tables; strategy catalog from `agent strategies.png` as templates.
3. **App shell upgrade** — top header bar, sidebar sections + collapse, user block;
   persistent chat input once the AI page exists.
4. **Alpha-calls parity** — stat cards, combined All tab with counts, Market/Side/
   Price columns (needs market data joined into the feed API).

### MEDIUM (leaderboard polish + T2 prep)
5. Wallet-quality tier system (TIER 1/2 badges + filter) distinct from trade-size
   tiers; wallet aliases.
6. Stat cards above `/wallets` and curated pages; Win Rate / Open / Last Trade
   columns; topic category pills.
7. **Aggregator page** (Compare + Arbitrage) — venue-pair rows, delta chips,
   strategy chips, edge/capacity filters.
8. Discover upgrade: threshold filter dropdowns (>$1K…>$1M), 30D windowed columns
   (backend already computes windowed stats), avatars.

### LOW (post-T2)
9. Trade page (chart, order book, buy/sell, news rail).
10. Portfolio page (exchange rows, summary cards, positions tabs).
11. Baskets (chat-driven creation + side panel + inline market cards).
12. News page; Bots management; Might Cook page; Community/Twitter/Support links.
