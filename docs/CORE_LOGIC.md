# Core Logic and Rules
*Last Updated: 2026-09-04*

This document outlines the core business logic, computational rules, and worker architecture for the Polymarket Analytics Platform.

For day-to-day operation, start with the [Operations Runbook](rule.md). It contains the exact commands, phase gates, capacity limits, and recovery rules; this document remains the authoritative definition of metric logic.

## AI Research Hub analytical definitions

- **Strict win-rate comparison:** “More than 70% win rate” means `win_rate > 70`, never `>= 70`. The `gte` comparator exists only for explicit requests.
- **Default evidence floor:** minimum 20 resolved positions. Every response displays the floor and each wallet's `resolved_count`; an explicit user request overrides it.
- **Category scope:** category, subcategory, and league filters use `category_stats_v2` with `window_size = 0` unless a historical window is explicitly requested.
- **Open position:** `wallet_positions_v2.current_value > 0` AND the stored row is not resolved (`COALESCE(is_resolved, FALSE) = FALSE`).
- **Exact/all coverage:** “all of them” requires `distinct_wallet_count = input_result_set.row_count` (coverage exactly 100%). “Most” is never substituted silently.
- **Eligible history:** historical same-market/same-outcome analysis uses only `wallet_closed_positions_v2.metrics_eligible = TRUE`; open rows join only when explicitly requested, and each row carries its source.
- **Outcome labels:** consensus groups by the market's stored outcome label. Binary markets may summarize as YES/NO; multi-outcome markets retain actual labels. Historical overlap is descriptive and never labels wallets coordinated/copied/collusive.
- **No fabrication:** monetary and win-rate values come from database fields only. The model explains values but never invents, rescales, or repairs them. Missing database fields render as em dash (`—`).
- **Chat-scoped open positions:** Positions shown in the Research Hub dock are strictly read-only and derived from `wallet_positions_v2` joined via `research_result_members` for wallet entities persisted in the active authenticated chat (`COALESCE(current_value, 0) > 0` AND `COALESCE(is_resolved, FALSE) = FALSE`). Cross-chat or cross-owner wallets are excluded. These chat-derived research positions are **not connected-wallet live positions** and must never be presented as a live account portfolio.
- **Mock trading ticket boundary:** The right-hand trading panel in the Research Hub is strictly a frontend UI prototype/mock ticket. It makes no network requests, does not connect to any exchange, CLOB, or execution broker, does not sign transactions, and places no live orders. Displayed mock prices, balances, expiration dates, and estimated returns are illustrative only and not authoritative financial quotes.
- **Floating panel geometry & persistence:**
  - Panel geometry (`x`, `y`, `width`, `height`) and `z_index` are persisted per panel within its parent **workspace**, not per chat.
  - Frontmost activation ranks are workspace-scoped: when a user clicks or moves a panel, `bring_to_front: true` atomically increments `z_index` above the workspace's highest rank; ranks compact when exceeding 1,000,000.
  - Backend persistence validates `x >= 0`, `y >= 0`, `y + height <= 100,000`, minimum size 320×240, and maximum size 4096×4096. Horizontal `stageWidth` clamping (`x + width <= stageWidth`) is frontend responsive behavior, not a backend persistence invariant.
  - Geometry is preserved during analytical upserts: `upsert_panel` does not overwrite existing `layout` JSONB column values, so a new chat result updates content/provenance without resetting workspace layout.
  - Responsive fallback: When viewport width < 768px or stage width < 640px, the canvas falls back to standard stacked layout without overwriting stored desktop coordinates; the frontend clamps horizontal placement to the available stage.


---

## 1. Curated Wallet Promotion / Demotion Criteria

A wallet is **promoted** to Curated (`tier = 'CURATED'` on `wallets_v2`) when it meets:
- **Total PnL** $> \$10,000$
- **AND** ($\text{ROI} > 30\%$ $\lor$ $\text{Win Rate} > 70\%$)

**Demotion & Tier Normalization**:
- Curated wallets that no longer meet the threshold are auto-demoted during stats refresher passes.
- **Custom Wallets (`source = 'custom'`)**: Custom/user-added wallets do NOT automatically default to `CURATED` tier. They are inserted as standard candidate entries (`source = 'custom'`) and follow the exact same automated tier rules (`NEW`, `STANDARD`, `LOW_BALANCE`, `CURATED`, `HIBERNATED`) based on their capital, activity, PnL, ROI, and win rate.

---

## 2. Wallet Tier State Machine (v2) & Total Capital

Every wallet on `wallets_v2` has exactly one `tier`, plus an orthogonal `is_dormant` flag.
Tier classification evaluates **Total Capital** ($\text{USDC Balance} + \text{Open Position Value}$) and **Activity (30-day window)**:

| Tier | Condition |
| :--- | :--- |
| `LOW_BALANCE` | $\text{Total Capital} < \$1,000$ (including $\$0$ balance wallets) |
| `NEW` | $\text{Total Capital} \ge \$1,000$, never traded (`last_trade_at IS NULL`) |
| `STANDARD` | $\text{Total Capital} \ge \$1,000$, has traded within 30 days |
| `CURATED` | Meets curation performance criteria (Total PnL $> \$10k$ AND ROI $> 30\%$ or Win Rate $> 70\%$) |
| `HIBERNATED` | Wallet inactive for $> 30$ days (`is_dormant = TRUE`) |
| `UNCLASSIFIED` | Queued for initial vetting |

### Zero-Balance & Zero-Capital Rules
The `DEAD` tier has been retired. Zero-balance / zero-capital wallets are classified based on recent trading activity:
- **Active 0-Balance** (Traded within last 30 days): `tier = 'LOW_BALANCE'`, `is_dormant = FALSE`. Displays under Low Balance.
- **Inactive 0-Balance** (No trade in last 30 days or never traded): `tier = 'LOW_BALANCE'`, `is_dormant = TRUE`. Displays under Hibernated.

### Dormancy Rule
- `is_dormant = TRUE` whenever `last_trade_at < NOW() - 30 days` or when a zero-balance / new wallet has no trading activity.
- When a hibernated wallet trades again (`last_trade_at` updated), `is_dormant` flips to `FALSE`. If the wallet was previously curated (`tier = 'PREVIOUSLY_CURATED'`), it automatically restores to `CURATED`.

### Refresh Cadence & Batch Scheduling
- **Position-source refresh:** Open and closed source workers refresh every wallet tier, including hibernated wallets, when the respective source timestamp is missing or older than **48 hours**. Derived metrics retain their own source-completeness rules and must not infer a successful source refresh merely from queue selection.
- **Hibernated Wallets (`is_dormant = TRUE`)**: Position source workers still refresh dormant rows when their source is missing or older than 48 hours. The last-activity sweeper also scans dormant wallets and wakes them only when `/activity` reports a recent trade; it never assumes activity from a position refresh or a missing response.
- **Tier priority ordering** in all three workers' batch queries: CURATED/CUSTOM → STANDARD → NEW → LOW_BALANCE → others. LOW_BALANCE wallets are included in backfill (no tier filter).

---

### Position Resolution & True Market Win Rate Calculation

A **position row** in `wallet_closed_positions_v2` is `(wallet, condition_id, outcome)` — all fills on the same outcome collapse into one contract row.

#### 1. Independent Position-Row Architecture (2026-09-01)
The canonical analytics grain is one `(wallet, condition_id, outcome)` contract row. YES and NO (or multiple categorical outcomes) in the same market remain separate factual positions.
- **Never group outcomes to compute win rate.** Grouping changes the denominator and hides genuine winning and losing positions.
- **Never generate an opposite leg.** `1 - avg_buy_price` is not proof that the wallet bought or minted that leg.
- Resolved-but-unclaimed positions synced from `/positions` (`is_redeemable=TRUE`) are included in overall and category statistics. The flag describes settlement state; it does not make the row synthetic.
- **Position win formula:**
  $$\text{is\_win} = (\text{repaired\_position\_pnl} > 0)$$

#### Complete current-position retrieval

- `/positions` has a maximum addressable offset of 10,000 with 500 rows per page, so direct pagination exposes at most 10,500 rows. A repeated offset-10,000 page at offset 10,500 is truncation, not proof of completion.
- For a capped wallet, use `/v1/accounting/snapshot` as the complete `(conditionId, asset)` inventory, then fetch `/positions` in bounded `market` partitions. This preserves Polymarket's `initialValue`, `cashPnl`, and other cost-basis fields that the snapshot CSV does not contain.
- Accounting snapshots can lag live state. A snapshot key missing from live `/positions` may be removed from the expected inventory only when wallet-scoped `/closed-positions?market=...` proves that exact asset exited.
- Any failed or unmatched partition makes `positions_complete=FALSE`. Incomplete results must never prune stored rows or advance `open_synced_at`.

#### Additive category hierarchy

- Root category PnL is the sum of every independent position row assigned to that category.
- Displayed subcategories aggregate all of their league rows. Selecting one league as the representative subcategory row is forbidden because it makes children non-additive.
- Known sports event-slug prefixes provide the most reliable local sport/league classification. A Sports row still lacking a defensible subcategory is stored and displayed as `Unclassified Sports`; it is never silently omitted.
- Exact `eventSlug` metadata from wallet-scoped Data API position responses is persisted so subsequent category computations do not need to guess from titles.
  Zero and negative-PnL rows are non-wins. Overall and category denominators count the same resolved rows.

#### 2. Resolved Open / Partial-Sell PnL
- **The Historical Flaw:** When a winning bet is held to market resolution without being sold early on the orderbook, `avg_sell_price` is `$0.00` (because no secondary sell occurred). Naive legacy checks like `avg_sell_price >= 0.95` failed, falsely stamping +$500k winning payouts as losses.
- `realizedPnl` contains PnL from shares sold before resolution; `initialValue` is the cost basis still held. Subtracting `totalBought × avgPrice` charges already-sold shares twice.
- **The rule:** 
  $$\text{remaining\_cost}=\min(\text{initialValue},\ \text{totalBought}\times\text{avgPrice})$$
  $$\text{position\_pnl}=\text{realizedPnl}+\text{currentValue}-\text{remaining\_cost}$$
- If `totalBought = 0`, no CLOB purchase cost is assumed. Mint/conversion collateral requires actual activity or on-chain evidence; it must not be fabricated from position size.

#### 3. The Universal Maximum Cash Loss Cap Axiom
A position row in `wallet_closed_positions_v2` can **never lose more cash than was actually spent to acquire it**:
$$\text{realized\_pnl} = \begin{cases} 0.0 & \text{if } \text{total\_bought} \le 0.01 \text{ (pure minted shares)} \\ \max(\text{realized\_pnl}, -(\text{total\_bought} \times \text{avg\_buy\_price})) & \text{otherwise} \end{cases}$$
*Eliminates tens of millions in phantom REST API liquidation losses across all wallets.*

#### 4. Dual-Engine Architecture
- **Macro Level (Headline Lifetime Account PnL & Equity Curves):** Anchored directly to official Polymarket leaderboard `pm_pnl` (cash-flow based collateral equity).
- **Micro Level (Granular Analytics):** Category win rates (`category_stats_v2`), price-bucket odds performance, and rolling position windows (`pnl_100`..`pnl_5000`) derive from the sanitized, unscaled position-row ledger.
- `total_pnl` and root-category PnL are position-ledger metrics; the snapshot card is `pm_pnl`. They are not scaled to match.
- A 2026-09-01 BreakTheBank backtest reconciled recorded cash plus current open value to within 0.40% of live `pm_pnl`. `CONVERSION.size` was proven unsuitable as a cash debit; it is token notional unless a real USDC transfer establishes otherwise.
- Polymarket also exposes official all-time PnL by root category, but category snapshots can lag the overall snapshot and did not add to overall PnL on every audited wallet. They may be stored/reported as diagnostics; they must not overwrite or scale `category_stats_v2.pnl`.
- **Activity provenance audit:** `/activity` carries `conditionId`, `asset`, `outcome`, `type`, side, size, USDC amount, timestamp, and transaction hash. Use it as the evidence feed for a position-row audit, not as a replacement PnL formula. Its `offset` ceiling is 5,000, so a complete-history audit must split `start`/`end` timestamp windows before comparing rows. A label mismatch alone is not proof of a bad row: normalize only demonstrably equivalent labels; require a matching asset or independent purchase evidence before any ledger deletion.
- **Complementary-sibling rule:** A complementary signature requires a distinct sibling outcome or asset in the same market. The audited row itself must be excluded from that comparison; a standalone 50-cent row cannot prove an opposite fabricated leg.
- **Eligibility gate:** Every stored closed row is initially `metrics_eligible=TRUE`. A row may become ineligible only through an evidence-backed audit decision; it is retained with its reason and timestamp, but excluded from normal position responses, overall PnL, category PnL, win rate, and windows. Numeric complementary-leg patterns alone are review candidates, never automatic exclusions.
- **Application gate:** `apply_position_eligibility.py` defaults to dry-run and accepts only `excluded_proven` decisions from one audit UUID. On explicit `--apply`, it toggles rows and recomputes core/category/window metrics in one transaction, rolling back if the eligible ledger and recomputed `total_pnl` differ.
- **Audit persistence and source limits:** Worker 3 (`activity_backfiller_worker.py`) fetches the complete Activity window, stages every row under one immutable `pending_snapshot_id`, and completes paginated incoming/outgoing CTF ERC-1155 lineage-transfer history before analysis; it does not prune. Worker 4 (`activity_analyzer_worker.py`) reads exactly that snapshot, writes compact lifecycle aggregates at `(address, condition_id, outcome)` grain plus deduplicated contradiction/lifecycle evidence, and only after the audit transaction succeeds prunes `wallet_activity_events_v2` to the newest 500 distinct hot events per wallet. This ordering is mandatory: the 500-row cache is not a complete analysis source. High-divergence full snapshots are verified and archived as ZSTD Parquet before pruning. `wallet_activity_scan_state_v2` stores pending Activity and lineage-completeness state, timestamp/hash watermark, and completion state; Worker 4 will not classify a snapshot until both sources are complete. A transfer supports a row only when its token ID equals the row's `source_asset`; it proves incoming shares, not purchase cost, so it is recorded as `verified_transfer_in` and never changes canonical PnL eligibility automatically. Both production Activity workers select only non-dormant wallets meeting `>= $10k` divergence or `>= $1k and >=10%`; Worker 3 runs bounded 150-wallet batches with a 15-minute idle interval, while Worker 4 runs bounded 500-wallet analyses. Wallet concurrency is 100, and `ACTIVITY_HTTP_CONCURRENCY` defaults to 50 page requests so each wallet's 11-page probes cannot create thousands of simultaneous sockets. Reconciliation remains four-way (`direct_activity_buy`, `activity_same_leg_nontrade`, `activity_outcome_differs`, or `activity_absent`) with BUY/SELL/REDEEM/SPLIT/MERGE/CONVERSION/reward/rebate/yield facts.
- **Deep closed-history recovery:** The normal address-wide `/closed-positions` pagination stops at offset `100000` and remains incomplete at that boundary. An explicit recovery mode may enumerate all Activity windows (splitting any window that fills offset `5000`), take only the discovered `conditionId` set, and query closed positions per condition. Only the closed-positions response supplies position PnL; Activity is discovery/evidence only. The normal scheduled worker must not enable this expensive mode implicitly.
- **Deep-history application:** `backfill_deep_closed_history.py <address>` is fetch-only by default and prints the row count plus completeness. `--apply` is refused unless the full discovery/retrieval process completed; it then upserts (never deletes), advances `closed_synced_at`, and recomputes canonical core/category/window metrics in one transaction.
- **Integrity roster semantics:** The scan reports every selected metric wallet, including wallets with zero eligible ledger rows. Unknown historical cap status is `null`, not `false`. Escalation is based on an internal metric/ledger or root-category/ledger mismatch (or explicit source evidence), never merely an official `pm_pnl` comparison.
- **Global scan rollout:** Run `python -m src.scripts.run_wallet_integrity_scan --all --limit 5000 --output backtest_cache/integrity_scan_active.json`. Hibernated wallets are excluded by default because their historical source snapshots are intentionally stale; use `--include-dormant` only for a separate archival audit. The scan uses address keyset batches rather than one unbounded ledger aggregation and writes exact cumulative progress to `.status.json`. Review the highest internal deltas first; then perform Activity/snapshot recovery per active wallet. Do not use the scan itself to change eligibility or metrics.
- **Activity escalation thresholds:** `activity_backfiller_worker.py` queues a wallet when `abs(total_pnl - pm_pnl) >= 10000`, or when the absolute difference is at least `$1,000` and is at least 10% of `max(abs(pm_pnl), 1000)`. `activity_analyzer_worker.py` consumes only staged snapshots. Both use bounded periodic batches. Activity reconciliation is evidence collection, not a PnL override.
- **Last-activity recovery:** `last_trade_sweeper.py` queries the latest `/activity` event for every wallet, including hibernated rows, when its sweep timestamp is missing or older than three hours. A returned timestamp within 30 days wakes the wallet; an absent or old timestamp leaves it hibernated. This recovery worker is independent of position refresh and exists because local retained trades are not a complete last-activity source.

---

## 4. 10-Step Sample Size Window PnLs

The platform pre-computes PnL metrics across **10 sample size windows** for all wallets:

`100`, `200`, `300`, `500`, `750`, `1000`, `1500`, `2000`, `3500`, `5000+`

- **Per-Position Chronological Ordering:** Windows slice resolved `(condition_id, outcome)` rows ordered by `closed_at DESC`.
- Slices `pnl_100` through `pnl_5000` sum unscaled `realized_pnl` across the last $N$ resolved position rows, including concluded-but-unclaimed rows.
- Powers the interactive **Sample Range Step Slider** on `/wallets` and the **Historical 10-Window Trade PnL Progression** spline chart on `/wallet/[address]`.
- Pre-computed as columns `pnl_100` through `pnl_5000` in `wallet_metrics_v2`.
- Powers the interactive **Sample Range Step Slider** on `/wallets` and the **Historical 10-Window Trade PnL Progression** spline chart on `/wallet/[address]`.

---

## 5. Trade & Activity Storage Across All Wallets (`wallet_activity_v2`)

- **Table**: `wallet_activity_v2` stores all real-time trade execution logs and deposit events for **ALL wallets** (Curated, Standard, Low Balance, New).
- **Populated By**: `trade_tracker.py` (polling Polygon EVM `ORDER_FILLED` logs every 15s) and `deposit_tracker.py` (polling pUSD mints every 60s).
- **Powers**: The live activity feed on `/feed`, individual wallet trade activity timelines on `/wallets`, user trade notifications, and alpha call generation.
- **Retention**: Pruned to **24 hours** every 6 hours. VACUUM runs after each prune for immediate space reclamation.

## 5a. Trade History Storage (`wallet_trades_v2`)

- **Table**: `wallet_trades_v2` stores historical market trades per wallet from the Polymarket Data API.
- **Populated By**: `polymarket_trade_backfiller.py` (batch backfill).
- **Retention Rule**: Every wallet retains at most **600 newest CLOB trade rows**. A successful insert ranks rows by `traded_at DESC` and removes only rows older than that cap; there is no time-based trade deletion.
- **Lineage Exception**: Lineage wallets (inherited_positions, internal_funded, funded_by, transferred_positions_count>0) route their complete CLOB trade history to `wallet_lineage_trades_v2`, which has no retention cap. Canonical P2P rows in `wallet_position_transfers_v2` are materialized into the same table as both `TRANSFER_IN` and `TRANSFER_OUT` by supervised Worker 17; it is resumable by source ID and the real-time tracker writes new rows immediately.

## 5b. Lineage Trade & Transfer Storage (`wallet_lineage_trades_v2`)

- **Table**: `wallet_lineage_trades_v2` is a unified lineage table storing P2P transfers, internal funding, and full CLOB trade fields from lineage wallets. CLOB rows use `event_type='TRADE'` and an idempotent `(wallet_address, tx_hash, log_index)` key.
- **No retention limits** — all data preserved indefinitely.
- **Event Types**: TRANSFER_IN, TRANSFER_OUT (from `wallet_position_transfers_v2`), DEPOSIT, WITHDRAWAL (from `wallet_internal_funding_v2`).
- **Source Tables**: `wallet_position_transfers_v2` (ERC-1155 P2P position transfers) and `wallet_internal_funding_v2` (wallet-to-wallet USDC funding).

## 5c. Storage Summary

| Table | Purpose | Retention | Writer |
|-------|---------|-----------|--------|
| `wallet_activity_v2` | Live feed (trades, deposits) | **24 hours** | trade_tracker, deposit_tracker |
| `wallet_trades_v2` | Market trade history (non-lineage) | **600 newest per wallet** | backfiller, trade workers |
| `wallet_lineage_trades_v2` | Lineage CLOB trades, transfers, deposits | Indefinite | backfiller, position_and_funding_tracker |
| `wallet_positions_v2` | Open positions | Indefinite (stale rows pruned per sync) | positions_open_backfill (Worker 2) |
| `wallet_closed_positions_v2` | Closed/resolved + redeemable-synced positions | **Top 5,000 recent per wallet** (older positions aggregated into `wallet_metrics_v2.*_beyond_5k`) | positions_closed_backfill (Worker 1), redeemable sync via Worker 2 |

---

## 6. Backfill Worker Architecture (3 Standalone Position Workers + Supervised Service Workers)

### The 3 Standalone Position Backfill Workers

1. **Standalone Closed Positions Fetcher** (`src/workers/positions_closed_backfill.py`)
   - Fetches closed positions from Polymarket API (configurable `CONCURRENCY = 100`, pool maximum at least `140`) and stores raw rows in `wallet_closed_positions_v2`. **No metric computation.** The shared limiter still bounds the combined Data API rate.
   - Sets `closed_synced_at` on each pass; source staleness gate: `closed_synced_at IS NULL OR closed_synced_at < NOW() - 48 hours`, including hibernated wallets.
   - A fetch is complete only after a real empty/short page or a known canonical row on an incremental pass. Failed pages, repeated/cache-corrupted pages, partial concurrent batches, and reaching the documented offset ceiling (`100000`) return `is_complete=FALSE`; such a pass cannot advance `closed_synced_at`.
   - Launch wrapper: `launch_closed_backfill.py` (~3.3 wallets/s).


2. **Worker 2: Open Positions & Redeemable Sync** (`src/workers/positions_open_backfill.py`)
   - Fetches open positions + portfolio value at configurable `CONCURRENCY = 100` (pool maximum at least `140`), detects concluded-but-not-redeemed positions and syncs them into `wallet_closed_positions_v2` (`is_redeemable=TRUE`), upserts open positions to `wallet_positions_v2`, prunes stale open rows. The shared limiter still bounds the combined Data API rate.
   - Writes open-side metrics: `position_value`, `balance`, `parlay_open_count/value`, `redeemable_count/winning_count`; sets `open_synced_at`; source staleness gate: `open_synced_at < NOW() - 48 hours`, including hibernated wallets.

3. **Worker 3: Metrics Computation** (`src/workers/positions_metrics_compute.py`)
   - Reads ALL stored closed positions from `wallet_closed_positions_v2` (including Worker 2's synced redeemable rows) and computes: win_rate, resolved_count, winning_count, price-bucket stats, 10 PnL windows, parlay metrics, category stats, ROI, total PnL/volume → writes `wallet_metrics_v2` + `category_stats_v2`.
   - Sets `computed_at`; staleness gate: `computed_at < NOW() - 84 hours` **OR** `closed_synced_at > computed_at` **OR** `open_synced_at > computed_at` (the latter two conditions are essential — without them, wallets whose data was refreshed after the last compute were never reprocessed).
   - Uses database-only computation (`CONCURRENCY = 150`) and selects only non-dormant wallets. It must never be used to infer that source history is complete; it synchronizes derived metrics to the eligible local ledger after source evidence has been reviewed.

**Ownership rule:** `resolved_count`/`winning_count`/`win_rate` are computed by **Worker 3 only**, from the raw table (so they include redeemable-synced positions). Worker 1 does not touch metrics.

**Backend schema rule:** API queries must select only persisted metric columns. `wallet_metrics_v2` does not have `avg_position_size`; leaderboard responses return `max_trade_size = NULL` until an evidence-backed stored metric exists. Never substitute another average or a default merely to satisfy a UI field.

**Repair rule:** Historical unproven rows are removed only by an evidence-backed full snapshot rebuild. `repair_and_sync_wallet.py` fetches complete `/closed-positions` and `/positions` snapshots before any write, defaults to dry-run, refuses incomplete or implausibly empty replacements, and performs the delete/reinsert/metric recompute in one transaction. A failure rolls back to the prior rows. Wallets whose history exceeds the API offset ceiling remain quarantined instead of being presented as complete.

### Support Workers & Real-Time Sync
- **Leaderboard Discovery Sync** (`poly_leaderboard_sync.py`): Daily 14:00 UTC sync of top Polymarket leaderboards; discovers new active wallets, updates `pm_pnl`/`pm_volume`/`pm_rank`.
- **Trade Tracker / Sweeper** (`trade_tracker.py` every 15s, `last_trade_sweeper.py`): Live feed polling, feed prune to 24h, `last_trade_at` maintenance.
- **P2P Transfer & Funding Tracker** (`position_and_funding_tracker.py`): Real-time EVM log scanner for ERC-1155 position transfers and USDC wallet funding.
- *(Note: `capital_metrics_backfill.py` retired on 2026-08-22 as ROI is derived autonomously from official leaderboard metrics).*

> Legacy reference: the original monolithic worker `positions_winrate_backfill.py` is retained but superseded by Workers 1–3 above.
