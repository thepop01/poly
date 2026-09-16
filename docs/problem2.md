# Problem 2: Two-Sided Market Distortions, Complete-Set Minting, and Granular Position Accounting

---

## 1. Executive Summary

When analyzing high-volume Polymarket traders (especially institutional market makers, arbitrageurs, and complete-set splitters), standard naive database ingestion produces severe discrepancies across **Win Rate, PnL, Historical Windows, and Trade Counts**.

This document provides a comprehensive technical audit of:
1. **The 6 Core Data Problems** inherent in Polymarket's API architecture.
2. **Everything We Have Tried & Tested** across on-chain transactions, activity logs, and position ledgers.
3. **Suggested Permanent Solutions** to guarantee exact prices, true share counts, pure row-level win rates, and zero phantom metrics.
4. **Tasks Started But Not Finished** with exact progress statistics and current status.

> **2026-09-01 update:** The condition-level win aggregation and synthetic opposite-leg approach have been reversed. The canonical grain is again one `(condition_id, outcome)` row. A 249,545-record `/activity` backtest disproved subtracting `CONVERSION.size` as cash. A subsequent seven-wallet live backtest added pagination-completeness guards and a dry-run/transactional rebuild path; no fleet-wide mutation has been run.

> **Implementation status (2026-09-01):** **Code solution implemented; historical rollout in progress.** The position snapshot cap, closed-history cap recovery, evidence/eligibility gate, conservative Activity audit, category/metric eligibility reads, and shared API limiter are implemented. No row is deleted or excluded automatically. Existing divergent wallets remain pending source-specific backfill/audit, so this document must not claim their displayed historical PnL is already repaired.

> **Operational queue status (2026-09-01):** The initial all-wallet read-only integrity pass covered 428,215 metric wallets and found 258,620 internal mismatches. It also established that 238,449 wallets are hibernated/dormant. Dormant wallets are now excluded from the active recovery queue—not deleted—because their intentionally stale snapshots cannot be evaluated as current backfill failures. The active queue contains 189,766 wallets.

> **Active mismatch triage (2026-09-01):** The active-only scan found 134,818 internal discrepancies. 132,417 disagree in both materialized wallet metrics and root categories, indicating stale derived fields; 1,033 have zero eligible closed rows; and 8,198 have a metric or category delta of at least $10,000. These are priority tiers, not automatic evidence that a stored position row is false.

---

## 2. The 6 Core Data Problems Identified

### Problem 1: Phantom Losses on Expired Positions
* **The Glitch:** When a trader buys shares over time and partially sells before resolution, Polymarket's data API calculates `realizedPnl` on the expired leg using the **unadjusted peak position size** rather than net held cost.
* **Real Example:** On `BreakTheBank`, a $49.4k soccer bet was recorded as a **`-$688,828` loss** (14x more loss than cash spent).

### Problem 2: Win Rate Deflation & Per-Row Decoupling
* **The Glitch:** When a trader bets on both YES and NO in the same market (hedging or market-making), evaluating legs independently counts **1 Win + 1 Loss = 50.0% Win Rate**, even on breakeven or highly profitable trades.
* **User Requirement:** Every closed contract token row must be evaluated independently as a strict factual record of the bet (if `realized_pnl > 0` $\implies$ Win, if `realized_pnl < 0` $\implies$ Loss, with zero emotional weighting or grouping).

### Problem 3: Minting Phantom Profit (The Missing Losing Leg)
* **The Glitch:** When Complete Sets ($1.00 = 1 YES + 1 NO) are split, the winning leg produces a payout ($1.00/share), while the losing leg expires at $0.00. Because Polymarket's `/closed-positions` only returns settled payout legs, the expired losing leg is omitted, creating multi-million dollar fake profits.
* **Real Example:** `BreakTheBank` showed **`+$35.73M`** in DB profit on 300 winning legs with 0 matching losing legs.

### Problem 4: Collateral / Conversion Omission in Activity Feed
* **The Glitch:** Polymarket's `/activity` endpoint logs on-chain minting as `CONVERSION` with **`usdcSize = $0.00`** (hiding the $1.00/set cash outflow). Later, redemptions log `+$1.00/share` cash inflows.
* **Impact:** Counting redemptions without debiting minting collateral falsely treats return of principal as pure profit.

### Problem 5: Missing Expired Losing Positions in `/closed-positions`
* **The Glitch:** When a directional bet resolves against a user (expires at $0.00), the user never submits an on-chain `claimRewards()` transaction (payout is $0). Polymarket leaves these expired bets in `/positions` with `redeemable = True` and `currentValue = 0`, but **omits them completely from `/closed-positions`**.
* **Impact:** 402 real losing bets were missing from closed positions, causing `BreakTheBank` to show only 329 closed positions instead of his true **733 closed positions**.

### Problem 6: Missing Resolution Dates (`closed_at` NULL) Distorting Windows
* **The Glitch:** Expired losing positions from `/positions` store resolution timing under `endDate` and Unix `timestamp` instead of `closed_at`. When ingested without parsing, `closed_at` was `NULL`.
* **Impact:** Postgres `ORDER BY closed_at DESC NULLS LAST` pushed all 402 losses to the bottom of the sort, causing the latest 100 window (`pnl_100`) to pick old winning bets from July and show **`+$35.7M`** instead of the true August performance (**`-$1.62M`**).

---

## 3. Everything We Have Tried & Explored

Here is a chronological record of the technical investigations, audits, and implementations tested:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ATTEMPT 1: Raw Closed Positions Ledger (/closed-positions)                             │
│   • Result on BreakTheBank: +$35,734,920.15 (329 rows)                                 │
│   • Verdict: FAILED. Missing 402 expired losing positions and minting collateral.      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 2: Direct Activity Feed Net Cashflow (/activity)                               │
│   • Result on BreakTheBank: +$15,197,510.77 (50,342 transactions)                      │
│   • Historical verdict: FAILED. The proposed $12.11M conversion debit was later        │
│     disproved; CONVERSION.size is not a cash field (see Attempt 7).                     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 3: Subtracted Minting Collateral from Activity Feed                            │
│   • Formula: Redemptions + Sells - Buys - Mint Collateral                              │
│   • Result on BreakTheBank: +$3,092,881.90                                             │
│   • Verdict: FALSE CONVERGENCE. The number matched one leaderboard snapshot, but the    │
│     method treated token notional as cash and failed the 2026-09-01 full backtest.      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 4: Synthetic Opposite Leg Generation in Database                               │
│   • Generated 126 synthetic opposite losing legs for condition_ids with buy_p < 0.50.  │
│   • Result on BreakTheBank: +$4,862,865.19 (455 rows)                                  │
│   • Verdict: PARTIAL. Reduced phantom profit from $35.7M to $4.86M, but still missed   │
│     the genuine 402 expired $0 losing contracts sitting in /positions.                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 5: Full Ingestion of Genuine Expired Positions from /positions                 │
│   • Current live snapshot adds 401 resolved-but-unclaimed rows from /positions.         │
│   • Deduplicated strictly by (condition_id, outcome).                                  │
│   • Result on BreakTheBank: 332 closed + 401 redeemable = 733 position rows.           │
│   • Win Rate: 285 positive-PnL rows / 733 = 38.88% (448 zero/negative rows).            │
│   • Verdict: SUCCESS. Restored complete, authentic position ledger.                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 6: Resolution Timestamp & endDate Parsing for closed_at                        │
│   • Populated closed_at from on-chain Unix timestamp and endDate for all 733 rows.     │
│   • Result on BreakTheBank:                                                            │
│     - Window 100 (pnl_100): -$1,618,628.13 (Exact sum of latest 100 closed rows).      │
│     - Window 200 (pnl_200): -$4,922,521.31                                             │
│     - Window All (pnl_all): -$7,430,884.93 (Lifetime closed positions ledger).         │
│   • Verdict: SUCCESS. Progression windows now reflect pure chronological reality.      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 7: Full Sliding-Window /activity Cash + Open-Value Backtest (2026-09-01)        │
│   • Fetched 249,545 unique activity records without the static offset cutoff.           │
│   • Recorded cash PnL: +$1,720,229.20; current open value: +$907,920.86.                │
│   • Equity estimate: +$2,628,150.06 vs live pm_pnl +$2,638,694.37.                     │
│   • Residual: -$10,544.31 (0.40%).                                                      │
│   • Verdict: SUCCESS. CONVERSION.size is token notional and MUST NOT be debited as      │
│     cash without a corresponding verified USDC transfer.                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ATTEMPT 8: Seven-Wallet Global-Grain & Completeness Backtest (2026-09-01)              │
│   • Audited directional, two-outcome, complete-set, and zero-bought-heavy wallets.      │
│   • Position rows produced stable factual win rates but often did not equal account PnL.│
│   • Official category sums matched overall on some wallets and lagged on others.        │
│   • Found repeated/cached closed-position pages and the documented offset=100000 cap.   │
│   • Verdict: SUCCESS. Preserve two metric planes; repair only from complete snapshots.  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Suggested Permanent Solutions & Architectural Standards

To ensure 100% data integrity across all 430k wallets, the system must enforce these **4 Core Rules**:

### Rule 1: Two-Source Closed Position Ingestion Pipeline
To capture every settled trade and avoid missing expired losses:
1. **Source A (`/closed-positions`):** Ingests all settlement payout redemptions and manual closed sell orders.
2. **Source B (`/positions` where `currentValue == 0` and `redeemable == True`):** Ingests all resolved contracts that expired at $0.00.

### Rule 2: Strict Deduplication by `(condition_id, outcome)`
* If a trader has multiple fills on the **exact same winning/losing condition** (`condition_id` + `outcome`), combine them into **1 position row** with weighted `avg_buy_price` and aggregated `total_bought`.
* If a trader holds `Yes` and `No` on the same market, they must remain **2 distinct rows** so prices, share counts, and individual outcomes are never blurred.

### Rule 3: The Axiom of Maximum Loss
A losing position can **NEVER** lose more cash than was actually spent to acquire it:
$$\text{realized\_pnl} = \begin{cases} 0.0 & \text{if } \text{total\_bought} \le 0.01 \\ \max(\text{realized\_pnl}, -(\text{total\_bought} \times \text{avg\_buy\_price})) & \text{otherwise} \end{cases}$$

### Rule 4: Mandatory Resolution Date Population
For every position row, `closed_at` must be populated using:
$$\text{closed\_at} = \text{COALESCE}(\text{to\_timestamp}(\text{timestamp}), \text{to\_timestamp}(\text{endDate}), \text{NOW}())$$
This guarantees that **Historical 10-Window Progression (`pnl_100`, `pnl_200`, `pnl_all`)** is strictly chronological without `NULLS LAST` sorting distortions.

### Rule 5: Independent Win-Rate Grain
Every `(condition_id, outcome)` row is evaluated independently. Do not group outcomes into one market win/loss and do not synthesize an opposite outcome. Overall and category win rates must use the identical row population and `repaired_pnl > 0` win rule.

### Rule 6: Activity Cash Fields Only
For account-equity backtests, count signed `usdcSize` from TRADE, REDEEM, MAKER_REBATE, TAKER_REBATE, REWARD, and YIELD. A `CONVERSION` row with `usdcSize=0` is non-cash metadata; never substitute token `size` as a USDC debit without verified on-chain cash transfer evidence.

### Rule 7: Completeness Is a Verified State
Never infer completion from a successful HTTP status alone. A closed-position snapshot is incomplete if page 0 fails, any page in a concurrent batch fails, a page repeats after retries, or pagination reaches the documented offset ceiling without an empty/short terminal page. Incomplete snapshots may add newly observed rows incrementally but must not advance `closed_synced_at` or replace canonical history.

### Rule 8: Full Repairs Are Fetch-First and Atomic
The divergence roster is repaired by full-source replacement only when both `/closed-positions` and `/positions` are complete. Fetch and validate before deletion; then replace closed/open rows, sync redeemables, and recompute metrics in one transaction. Default execution is read-only and explicit `--apply` is required.

---

## 5. Frontend Presentation Standard

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. SNAPSHOT HEADER MINI-CARD ("Polymarket PnL"):                                       │
│    • Value: `stats.pm_pnl` (e.g. +$2.63M for BreakTheBank, +$23.63M for swisstony)     │
│    • Meaning: Official Polymarket whole-portfolio net equity (all deposits/withdrawals).│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. HISTORICAL 10-WINDOW PROGRESSION & TRADE ANALYTICS:                                 │
│    • Value: `stats.pnl_100`, `stats.pnl_200`, `stats.pnl_all`                          │
│    • Meaning: Pure Database Position Ledger of all closed & expired bets in DB.        │
│    • Window 10 Label: "All" (`pnl_all`), representing 100% of closed trades.           │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. ROW-LEVEL ACCURACY:                                                                 │
│    • Win Rate = (winning_count / resolved_count) * 100%                                │
│    • Price Buckets = Evaluated per individual contract token entry price.              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Tasks Started But Not Finished (Status & Exact Progress Stats)

Here is the complete audit of tasks that were initiated, their progress before stopping, and their current system state:

| Task / Worker | What Was Started | Progress When Stopped | Exact Stats | Current Status | Why Paused / Next Steps |
|---|---|:---:|---|:---:|---|
| **Divergence Reconcile Worker** (`reconcile_diverging_wallets.py`, removed) | Swept diverging wallets generating synthetic opposite legs (`1.0 - buy_p`) | **2,100 / 203,556 wallets (1.03%)** | Added **3,254,621 unproven synthetic legs** across 2,100 wallets | ⛔ **REMOVED** | The compatibility wrapper was removed after the canonical modular metrics path was established. Historical rows were not globally deleted because the old rows lack source provenance; deletion requires a separate safe audit. |
| **Genuine Expired Losses Backfill** | Ingesting resolved-but-unclaimed rows from Polymarket `/positions` | **Backtested; fleet apply not run** | Live `BreakTheBank`: **733 rows** (332 closed + 401 redeemable), 285 wins, **38.88%** | ✅ **GUARDED TOOL READY** | `repair_and_sync_wallet.py --divergence-file ...` is dry-run by default, rejects incomplete snapshots, and requires `--apply`. |
| **Resolution Date Backfill (`closed_at`)** | Backfilling `closed_at` timestamps from `endDate` and Unix epoch | **1 wallet (100% on BreakTheBank)** | Populated `closed_at` for all 733 rows, restoring `pnl_100: -$1.62M` | ⏸ **PAUSED** | Remaining closed positions across other wallets need a global SQL date backfill. |
| **Global Row-Level Metrics Sweep** ([`compute_core_metrics.py`](file:///d:/project/poly/src/workers/compute_core_metrics.py)) | Re-running Core Metrics, Category Stats, and Historical Windows with pure row-level logic (no grouping) | **Code fixed; fleet run not started** | Live BreakTheBank backtest: 285 wins / 448 non-wins = **38.88%** on 733 independent rows | ⏸ **READY FOR CONTROLLED ROLLOUT** | 42 focused tests pass. Apply only after each wallet passes the full-snapshot preflight; offset-ceiling wallets remain quarantined. |
