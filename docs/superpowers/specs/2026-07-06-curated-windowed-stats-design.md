# Curated Windowed Stats — Design

**Date:** 2026-07-06
**Status:** Approved (design), pending implementation plan
**Scope:** Reworks how PnL / win% / ROI / volume are sourced and displayed, and adds
per-category, per-trade-window statistics for curated wallets.

---

## 1. Problem

Today a wallet's headline PnL is a fragile either/or:
`effective_pnl = website_pnl if website_pnl != 0 else total_pnl` (`leaderboard_stats.py:214`).
It silently substitutes the Polymarket leaderboard number for our fresh-start
realized+unrealized calc, the two numbers measure different windows, and the stored
breakdown can fail to reconcile.

Separately, the curated page needs to show performance over **trade windows**
(last 100 / 300 / 800 / 1500 / 2500) **per market category** (All, Sports, Politics,
Crypto, …), with **all** metrics — not just PnL — reflecting the selected window. The
schema groundwork exists (`wallet_trade_window_stats`, `curated_wallet_trades`) but the
window table is keyed only by `(address, window_size)` (no category), the API surfaces
only per-window `pnl`, and the frontend only swaps the PnL column.

## 2. Goals

1. **Headline PnL/volume come from the Polymarket leaderboard** (`/v1/leaderboard`), which
   is realized and all-time. Fall back to trade/position-computed PnL only when the wallet
   is not on any leaderboard.
2. **Win% and ROI are computed exactly as today** — from `closed-positions`
   (`win_rate = winning_count / resolved_count`, `roi_pct = pnl / volume * 100`). No change
   to the formulas. Open (unresolved) positions are intentionally ignored.
3. **Curated wallets get per-category × per-window stats** stored in separate physical
   tables for fast reads, refreshed on an hourly (up to ~3-hourly at peak) cycle.
4. **Frontend curated page**: category tabs × window filter; selecting a window swaps every
   displayed metric (pnl, volume, win%, roi, trades, wins, last active) to that window's
   precomputed values. No status column.

## 3. Non-goals

- No change to win% methodology (held/open losers stay excluded — explicit decision).
- No windows on the **global** list — global wallets show headline PnL/volume + all-time
  win%/ROI only.
- No mark-to-market or probability-weighted win rate.
- Not dropping the realized/unrealized calc or the Alchemy deposit/withdrawal/balance
  calls — they are retained (needed for the non-leaderboard fallback and deposit tracking).

## 4. Verified facts (live API, 2026-07-06)

These were confirmed by hitting the live endpoints and drive the cost model:

- `/v1/leaderboard?user=<addr>&category=OVERALL&timePeriod=ALL` returns `pnl` + `vol` per
  wallet. **Leaderboard `pnl` is realized** — for Theo4 (rank 1) the sum of `realizedPnl`
  over closed positions ($22,053,934) equals leaderboard `pnl` ($22,053,933) to rounding.
  Headline PnL therefore shares the same basis as win rate.
- `/closed-positions` **caps at 50 rows per page regardless of the `limit` param**
  (raising `limit` to 500 is silently ignored). Offset pagination works. Fields
  `realizedPnl`, `totalBought`, `endDate`, `timestamp` are present.
- Resolved-position counts vary widely: Theo4 = 22, swisstony = 350+. Most wallets are
  small; the 2,500 cap (= 50 sequential calls) only bites rare hyper-active wallets.
- `/trades?taker=<addr>&limit=500` honors `limit=500`.

**Cost model (per curated wallet per refresh):** ~15–30 API calls typical, ~90 worst-case
whale. At hourly for 1,675 wallets ≈ 14 req/s; at 3-hourly for 10,000 ≈ 28 req/s. Feasible.

## 5. Data model

### 5.1 Window tables (new)

Five separate physical tables — one per window — as requested for read speed:

```
wallet_window_100, wallet_window_300, wallet_window_800, wallet_window_1500, wallet_window_2500
```

Each has identical shape, keyed by `(address, category)`:

| column          | type            | notes                                             |
|-----------------|-----------------|---------------------------------------------------|
| address         | VARCHAR(42) FK  | → tracked_wallets(address) ON DELETE CASCADE      |
| category        | VARCHAR(20)     | 'OVERALL', 'SPORTS', 'POLITICS', … (All = OVERALL)|
| pnl             | NUMERIC(18,2)   | Σ realizedPnl over last N resolved in category    |
| volume          | NUMERIC(18,2)   | Σ totalBought over last N resolved in category    |
| win_rate        | NUMERIC(5,4)    | winning_count / resolved_count                     |
| roi_pct         | NUMERIC(10,4)   | pnl / volume * 100                                 |
| resolved_count  | INTEGER         | "trades" column in UI (resolved positions)         |
| winning_count   | INTEGER         | "wins" column in UI                                |
| last_active     | TIMESTAMPTZ     | most recent `endDate` within the window            |
| computed_at     | TIMESTAMPTZ     | refresh timestamp                                  |

PK `(address, category)`. Index `(category, pnl DESC)` for leaderboard-style sorting.

> Note on collapse behavior (expected, not a bug): when a wallet has fewer than N resolved
> positions in a category, that window equals all-time for the category, so multiple windows
> show identical numbers. Windows only diverge for high-frequency resolved-market traders.

### 5.2 All-time per-category

`wallet_category_stats` already stores per-category all-time `total_pnl, total_volume,
win_rate, resolved_count, winning_count, roi_pct`. Extend it with `last_active` so the
"ALL TIME" row matches the window rows' column set. A `category='OVERALL'` row is added for
the All-Market tab. To resolve the pnl/volume ambiguity explicitly:
- **OVERALL all-time `pnl`/`volume`** = leaderboard headline (`website_pnl`/`website_volume`),
  falling back to computed when the wallet is not on any leaderboard.
- **OVERALL all-time `win_rate`/`roi_pct`/`resolved_count`/`winning_count`/`last_active`** =
  computed over all closed positions (capped at last 2,500), consistent with §6.2.
- **Per-category all-time** rows use closed-positions aggregates for that category
  (pnl = Σ realizedPnl, volume = Σ totalBought), i.e. not the leaderboard, since the
  leaderboard headline is overall-only.
- **All OVERALL/per-category window rows** use closed-positions aggregates for that
  (category, window): pnl = Σ realizedPnl over the last N resolved.

### 5.3 Deprecate old window table

`wallet_trade_window_stats` (keyed `(address, window_size)`, no category) is superseded by
the five per-category tables. Migration drops it after the new tables are populated.

### 5.4 `curated_wallet_trades`

Unchanged shape. Capture policy changes: store up to **2,500 raw fills** per curated wallet,
fetched as **full history** (not only since tracking start).

## 6. Worker changes (`src/workers/leaderboard_stats.py`)

### 6.1 Headline PnL/volume
Replace the `effective_pnl = website_pnl if website_pnl != 0 else total_pnl` sentinel with an
explicit source decision:
- If the wallet has a leaderboard entry (`website` object present) → headline pnl/volume =
  leaderboard `pnl`/`vol`; set `pnl_source = 'leaderboard'`.
- Else → headline pnl/volume = computed realized+unrealized / computed volume;
  `pnl_source = 'computed'`.
Store `pnl_source` on `tracked_wallets` so the UI/debugging can distinguish. `realized_pnl`
and `unrealized_pnl` continue to be stored raw and consistently (never overwritten by the
leaderboard value).

### 6.2 closed-positions fetch
Cap pagination at **2,500** resolved positions (`limit=50`, so ≤50 calls). Keep existing
retry/backoff. All-time win%/ROI is thus computed over "last 2,500 resolved" (documented
semantics); all-time pnl/volume come from the leaderboard.

### 6.3 Per-category windowing (new)
After fetching closed positions:
1. Sort by `endDate` desc.
2. Classify each closed position into a category (reuse `classify_tags` / conditionId→category
   mapping already used by `compute_category_stats`).
3. Group by category; also maintain an `OVERALL` group = all positions.
4. For each category group and each window N in [100,300,800,1500,2500]: take the first N,
   compute pnl/volume/win_rate/roi/resolved/wins/last_active, upsert into `wallet_window_N`.
All in-memory — **no extra API calls** beyond the closed-positions already fetched.

### 6.4 Refresh scheduling
Continuous worker, prioritizing recently-active curated wallets
(`last_trade_at DESC` / `last_indexed ASC NULLS FIRST`). Optional delta gate: skip full
window recompute if `last_trade_at` / resolved count is unchanged since `computed_at`. Target
a full curated pass within ~1 hour (1,675 wallets), degrading to ~3 hours at 10,000.

### 6.5 Retained
Alchemy deposits/withdrawals/balance, realized/unrealized calc, `curated_wallet_trades`
capture (raised to 2,500, full history), dormancy + curated-promotion logic — all kept.

## 7. API changes (`src/api/routers/leaderboard.py`)

Curated endpoint accepts `category` (default `OVERALL`) and `window` (default all-time):
- `window` empty → read `wallet_category_stats` for the category.
- `window` in {100,300,800,1500,2500} → read `wallet_window_<N>` for the category.
Return the full metric set for the resolved (category, window) cell: `pnl, volume, win_rate,
roi_pct, resolved_count (trades), winning_count (wins), last_active`. Sorting/filtering
(min/max pnl, roi, win rate) operate on the selected window's columns. Replaces the current
5-way `LEFT JOIN wallet_trade_window_stats … pnl` block.

## 8. Frontend changes (`frontend/src/app/wallets/curated/page.tsx`)

> The frontend uses a customized Next.js — read `node_modules/next/dist/docs/` before writing
> component code.

- Category tabs (existing) select `category`; window filter selects `window`.
- On change, refetch from the API; **every column** (pnl, volume, win%, roi, trades, wins,
  last active) renders the returned windowed values. Remove the client-side `getWindowPnl`
  swap (server now returns fully windowed rows).
- Add `volume` and `last active` columns; remove any status column.
- Header labels reflect the active window ("Last 100" etc.); "ALL TIME" when no window.

## 9. Migrations

1. Create `wallet_window_100/300/800/1500/2500` (`(address, category)` PK + index).
2. Add `last_active` to `wallet_category_stats`; ensure an `OVERALL` category row is produced.
3. Add `pnl_source` to `tracked_wallets`.
4. After backfill, drop `wallet_trade_window_stats`.

## 10. Testing

- **Unit:** per-category windowing given a fixture list of closed positions — correct
  slicing per category, correct pnl/win_rate/roi/last_active, OVERALL = union, window ≥
  resolved_count collapses to all-time.
- **Unit:** headline source selection (leaderboard present vs absent → `pnl_source`).
- **Integration:** worker writes all five tables + category stats for a seeded wallet;
  API returns the correct cell per (category, window); sorting respects the window.
- **Manual/live:** run the worker against a known whale, confirm numbers reconcile with the
  leaderboard headline and the closed-positions data (`verify` skill before completion).

## 11. Rollout

1. Migrations (additive first).
2. Worker: headline source + closed-positions cap + per-category windowing.
3. Backfill window tables for existing curated wallets.
4. API param support.
5. Frontend windowed columns.
6. Drop `wallet_trade_window_stats`.

## 12. Open risks

- Category classification accuracy for closed positions (depends on `classify_tags`).
- Storage: 5 tables × ~10 categories × up to 10k wallets ≈ up to 500k rows/table — fine for
  Postgres with the PK/index.
- Rate limits at 10k scale if the delta gate is not effective; mitigation is prioritization
  + cadence relaxation to ~3 hours.
