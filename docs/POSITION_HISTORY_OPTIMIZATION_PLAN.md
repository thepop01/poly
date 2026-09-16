# Position History Optimization & Rolling Incremental Sync Plan

## 1. Executive Summary & Launch Objective

* **Primary Launch Goal:** Enable high-speed, 100% mathematically exact metrics refresh across all **368,000 wallets** for production public launch.
* **The Core Problem:** 
  * `wallet_closed_positions_v2` is **68 GB** with **131.2 Million rows**.
  * **4,735 high-volume wallets** account for **42.4 Million rows** (up to 137,000 positions per wallet).
  * Polymarket's API caps closed positions at **50 per page**. Fetching 20,000+ positions from scratch requires **400+ HTTP calls per wallet**.
  * Re-fetching entire histories every 12-hour sync causes API rate limits (HTTP 429), worker stalls, socket timeouts, and database bloat.

---

## 2. Key Architectural Decisions

### A. Effective Resolution Timestamp Hierarchy: Resolution Date vs. Early Exit Date

Polymarket positions close in two distinct ways:
1. **Held to Resolution (Market Concluded):** The market resolved on date $T_{\text{resolved}}$ (e.g. August 5th). The canonical date is the **Market Concluded Date (`resolved_at` / `endDate`)**. 
   * *The Redemption Trap:* If the user claims/redeems payout 2 weeks later on August 21st, Polymarket's `closedAt` reflects the redemption claim date. Sorting by `closedAt` would falsely promote this 2-week-old trade to the top of recent trades. Using $T_{\text{resolved}}$ ensures chronological integrity.
2. **Early Exit (Sold Before Market Resolution):** The user actively traded out of the position for profit/loss before the market concluded (e.g. sold in May on a December-ending market).
   * Here, `endDate` is in the future (or not applicable to the exit), so the canonical date is the **Trade Close Date (`closed_at` / `lastUpdatedAt`)**.

#### Canonical SQL Ordering Expression:
```sql
ORDER BY COALESCE(
  CASE WHEN resolved_at IS NOT NULL AND resolved_at <= NOW() THEN resolved_at ELSE NULL END,
  CASE WHEN closed_at IS NOT NULL AND closed_at <= NOW() THEN closed_at ELSE NULL END,
  opened_at,
  '1970-01-01'::TIMESTAMPTZ
) DESC
```

This guarantees:
* Early exits are ordered by the exact day the trader sold out.
* Held-to-resolution trades are ordered by the exact day the market concluded (not when payout was claimed).
* Future phantom end dates (`endDate > NOW()`) never corrupt the sorting order.

---


### B. Full First-Time Backfill vs. Rolling Cumulative Incremental Sync

```
[ New Wallet Discovery ]
  └─► Fetch 100% Full History from Polymarket API
  └─► Sort all positions by endDate DESC
  └─► Keep Top 5,000 in wallet_closed_positions_v2
  └─► Positions 5,001..N: Aggregate into wallet_metrics_v2 (*_beyond_5k columns) & delete raw rows

[ Subsequent Incremental Backfills (e.g. 1 week later) ]
  └─► Fetch only NEW positions since last sync
  └─► Upsert new positions to wallet_closed_positions_v2 (DB count: 5,000 + M)
  └─► Slices rows ranked > 5,000 (the M oldest rows of the buffer)
  └─► CUMULATIVELY ADD overflow rows into *_beyond_5k columns (+Δ)
  └─► Delete overflow rows from wallet_closed_positions_v2 (DB count back to 5,000)
  └─► Calculate headline stats: Active 5k Recent + Cumulative *_beyond_5k Aggregates
```

---

## 3. Detailed Math: Cumulative Rolling Aggregator

When a wallet receives $M$ new settled trades during a weekly sync:

1. **New Raw Rows Added:** `wallet_closed_positions_v2` temporarily holds $5,000 + M$ rows.
2. **Identify Overflow Rows:** The $M$ oldest rows (ranked $> 5,000$ by `endDate DESC`) are extracted.
3. **Additive Accumulation:** We calculate the aggregate stats of those $M$ overflow rows ($\Delta$) and add them cumulatively to `wallet_metrics_v2`:
   $$\text{resolved\_count\_beyond\_5k}_{\text{new}} = \text{resolved\_count\_beyond\_5k}_{\text{old}} + \Delta_{\text{resolved}}$$
   $$\text{winning\_count\_beyond\_5k}_{\text{new}} = \text{winning\_count\_beyond\_5k}_{\text{old}} + \Delta_{\text{wins}}$$
   $$\text{total\_volume\_beyond\_5k}_{\text{new}} = \text{total\_volume\_beyond\_5k}_{\text{old}} + \Delta_{\text{volume}}$$
   $$\text{buys\_bucket\_beyond\_5k}_{\text{new}} = \text{buys\_bucket\_beyond\_5k}_{\text{old}} + \Delta_{\text{bucket\_buys}}$$
   $$\text{wins\_bucket\_beyond\_5k}_{\text{new}} = \text{wins\_bucket\_beyond\_5k}_{\text{old}} + \Delta_{\text{bucket\_wins}}$$
4. **Prune Overflow:** Delete the $M$ overflow rows from `wallet_closed_positions_v2`.
5. **Headline Metrics Calculation:**
   $$\text{Lifetime Resolved} = \text{recent\_5k\_resolved} + \text{resolved\_count\_beyond\_5k}$$
   $$\text{Lifetime Wins} = \text{recent\_5k\_wins} + \text{winning\_count\_beyond\_5k}$$
   $$\text{Lifetime Win Rate} = \frac{\text{Lifetime Wins}}{\text{Lifetime Resolved}} \times 100$$

> **Result:** 100% exact all-time win rate, exact price buckets, exact volume, and exact 100–5000 PnL windows forever, without ever needing to re-fetch full history again.

---

## 4. Database Schema Changes (`wallet_metrics_v2`)

```sql
ALTER TABLE wallet_metrics_v2 ADD COLUMN IF NOT EXISTS
  -- Headline cumulative aggregates for positions beyond rank 5,000
  resolved_count_beyond_5k       INT DEFAULT 0,
  winning_count_beyond_5k        INT DEFAULT 0,
  total_volume_beyond_5k         NUMERIC DEFAULT 0,
  avg_buy_price_beyond_5k        NUMERIC DEFAULT 0,
  closed_cost_total              NUMERIC DEFAULT 0,  -- SUM(avg_buy_price * total_bought) across all-time history

  -- Price bucket cumulative aggregates beyond rank 5,000
  buys_below_15c_beyond_5k       INT DEFAULT 0,
  wins_below_15c_beyond_5k       INT DEFAULT 0,
  losses_below_15c_beyond_5k     INT DEFAULT 0,
  buys_15_30c_beyond_5k          INT DEFAULT 0,
  wins_15_30c_beyond_5k          INT DEFAULT 0,
  losses_15_30c_beyond_5k        INT DEFAULT 0,
  buys_30_45c_beyond_5k          INT DEFAULT 0,
  wins_30_45c_beyond_5k          INT DEFAULT 0,
  losses_30_45c_beyond_5k        INT DEFAULT 0,
  buys_45_60c_beyond_5k          INT DEFAULT 0,
  wins_45_60c_beyond_5k          INT DEFAULT 0,
  losses_45_60c_beyond_5k        INT DEFAULT 0,
  buys_60_75c_beyond_5k          INT DEFAULT 0,
  wins_60_75c_beyond_5k          INT DEFAULT 0,
  losses_60_75c_beyond_5k        INT DEFAULT 0,
  buys_above_75c_beyond_5k       INT DEFAULT 0,
  wins_above_75c_beyond_5k       INT DEFAULT 0,
  losses_above_75c_beyond_5k     INT DEFAULT 0,

  -- Incremental sync & cutoff tracking
  pruned_min_closed_at     TIMESTAMPTZ,
  pruned_at                TIMESTAMPTZ;
```

---

## 5. Handling Category & Subcategory Stats

* **Table:** `category_stats_v2` is already a pre-aggregated summary table by `(address, category, subcategory, window_size)`.
* **Full History on First Backfill:** When a wallet is first synced, all historical positions are mapped via `classify_tags([title])` and their volume, PnL, wins, and resolved counts are inserted into `category_stats_v2`.
* **Incremental Updates:** When new positions are synced in subsequent cycles, their category metrics are simply added to the existing rows in `category_stats_v2`.
* **No Category Data Lost:** Because `category_stats_v2` stores summary aggregates, pruning raw rows from `wallet_closed_positions_v2` does not delete category historical performance.

---

## 6. Implementation Roadmap

### Step 1: Alembic Migration
Create migration `alembic/versions/XXXX_add_beyond_5k_position_aggregates.py` adding all cumulative `*_beyond_5k` columns and prune tracking columns to `wallet_metrics_v2`.

### Step 2: Update Worker Pruning & Aggregation Logic
In `src/workers/positions_winrate_backfill.py`:
1. Ensure all sorting uses `endDate` (Market Concluded Date) as canonical timestamp.
2. In `sync_redeemable_positions`, set `closed_at = resolved_at = _parse_end(p.get("endDate"))`.
3. In `upsert_closed_positions_v2`, ensure `ON CONFLICT` preserves the original `closed_at = endDate`.
4. Implement `prune_and_accumulate_closed_positions(conn, address, threshold=5000)`:
   * Slices rows beyond rank 5,000.
   * Calculates $\Delta$ aggregates for the slice.
   * Additively updates `wallet_metrics_v2` (`col = COALESCE(col, 0) + $delta`).
   * Deletes the overflow rows atomically in the same transaction.
5. In headline metrics calculation, merge `recent_5k + *_beyond_5k`.

### Step 3: One-Time Historical Pruning Script
Create `src/scripts/prune_and_aggregate_closed_positions.py`:
* Queries the **4,735 wallets** with $> 5,000$ positions in `wallet_closed_positions_v2`.
* Computes initial `*_beyond_5k` aggregates from rows ranked $> 5,000$.
* Writes initial `*_beyond_5k` values to `wallet_metrics_v2` and deletes raw rows $> 5,000$.
* Runs in concurrent batches with progress tracking and validation checks.

### Step 4: Storage Compaction
Run `VACUUM ANALYZE wallet_closed_positions_v2;` during low-traffic hours to reclaim ~35 GB of disk space.

---

## 7. Launch Verification & Backtest Plan

1. **Select 10 Whale Test Wallets** (e.g. `likebot` with 28k+ positions, `coinman2`, top leaderboard traders).
2. **Snapshot Pre-Prune Metrics:** Record current `win_rate`, `resolved_count`, `winning_count`, `category_stats_v2`, `pnl_100`..`pnl_5000`, and price bucket counts.
3. **Execute Pruning & Accumulation:** Run the migration script on the test wallets.
4. **Validate Exact Match:**
   * $\text{Pre-Prune Win Rate} == \text{Post-Prune Merged Win Rate}$ ($\pm 0.00\%$)
   * $\text{Pre-Prune PnL Windows (100–5000)} == \text{Post-Prune Windows}$
   * $\text{Category Breakdown} == \text{Pre-Prune Categories}$
5. **Simulate Incremental Refresh:** Run a standard incremental sync cycle on the test wallets to verify that new positions increment `*_old` properly and stats remain 100% stable.

---

## 8. API Pagination Mechanics & Data Scaling Rules

### A. Polymarket Data API Constraints & Paging
* **Closed Positions Endpoint:** `https://data-api.polymarket.com/closed-positions`
* **Hard Page Cap:** Maximum **50 items per request** (passing `limit=500` returns 50 items).
* **Pagination Parameters:** Always query with `limit=50&offset={offset}&sortBy=TIMESTAMP&sortDirection=DESC` to ensure chronological delivery.
* **Worker & API Cap:** Maximum capacity set to **200,000 positions per wallet** (`MAX_CLOSED = 200000`).
* **Multi-Page Loop Condition:** Loops until `len(page) < 50` or `offset >= 200000`.

### B. Currency & Decimals Specification
* **Raw Currency Format:** `wallet_closed_positions_v2` and Polymarket `/closed-positions` API return `realizedPnl`, `totalBought`, and `totalSold` in standard **US Dollars ($)**.
* **No Micro-USDC Division:** Never divide large values by `1,000,000` (which previously corrupted high-stake trades $> \$1\text{M}$).
* **Parity Guarantee:** Summing all rows from the paginated `/closed-positions` API directly equals the wallet's total realized closed PnL.

