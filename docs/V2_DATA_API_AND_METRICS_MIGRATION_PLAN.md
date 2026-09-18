# Polymarket v2 Data API & Canonical Metrics Migration Plan

**Date:** September 10, 2026  
**Status:** Approved Architectural Blueprint  
**Reference Document:** `docs/learner.md` (Section 22)

---

## 1. Executive Summary & Core Insights

Polymarket engineering provided direct architectural clarification on position lifecycle, neg-risk conversions, and historical ledger corrections:

1. **Neg-Risk Conversion Mechanism:** In multi-outcome events, converting `NO` shares on one question burns those `NO` shares and mints `YES` shares across all other questions in that event. The `/activity` feed records only one `CONVERSION` row on the source question with no token ID, and minted `YES` position legs generate **no trade fill rows**.
2. **True Average Cost Basis ($1/k$):**
   - Trade fills: valued at fill price.
   - Conversion mints: valued at $\$1/k$ ($\$1$ divided by $k$ questions in the event, e.g. $\$0.3333$ for 3-way, $\$0.0588$ for 17-way Exact Score).
   - Splits: valued at $\$0.50$ (or $\$1/k$).
   - Buy fees: assessed in shares, raising the effective acquisition price ($\text{cash paid} / \text{net shares}$).
3. **Goldsky Deprecation & Sept 7 Restatement:** On Sept 7, 2026, Polymarket took PnL calculation in-house from 3rd-party Goldsky, restating conversion cost bases from $\$0.50$ to $\$1/k$.
4. **August Ledger Glitch:** Markets resolving on August 7, 24, and 31 had missing settlements and missed fills on Polymarket's legacy ledger. Upstream fixes are being applied.
5. **Upcoming v2 Data API (This Week):** Polymarket is releasing a v2 Data API with explicit per-row `total_pnl` (`realized_pnl + unrealized_pnl`) and event-level reconciliation metadata.

---

## 2. Core Strategic Decision

### **Decision: Do Not Run Fleet-Wide Metric Recomputations on Legacy Raw Data**
* **Rationale:** Recomputing metrics across all 54,000+ active wallets today would mean computing derived analytics on top of raw position rows that carry legacy pre-Sept 7 cost bases, missing mints, and August settlement gaps.
* **Approach:**
  - **Interim (Now):** Keep already backfilled active wallets consistent, harden our schemas, refine frontend/API dual-domain displays, and prepare the v2 ingestion pipeline.
  - **Launch (When v2 drops this week):** Ingest clean v2 positions with restated $1/k$ cost basis and corrected settlements, then run atomic canonical metric recomputation over verified clean source data.

---

## 3. Deep Dive: Event-Level vs. Market-Level Reconciliation

### What is an "Event" vs. a "Market"?
* **Event (`event_id` / `event_slug`):** The overarching real-world contest (e.g., `spain-vs-argentina-final` or `premier-league-winner-2026`).
* **Market (Question / `condition_id`):** An individual sub-question within that event:
  * Market A: "Will Argentina win?" (YES / NO)
  * Market B: "Will Spain win?" (YES / NO)
  * Market C: "Will it be a Draw?" (YES / NO)

```
                       ┌────────────────────────────────────────┐
                       │   EVENT: Spain vs Argentina Final      │
                       └───────────────────┬────────────────────┘
                                           │
         ┌─────────────────────────────────┼────────────────────────────────┐
         ▼                                 ▼                                ▼
┌──────────────────┐             ┌──────────────────┐             ┌──────────────────┐
│  Market A (Arg)  │             │ Market B (Spain) │             │  Market C (Draw) │
│    YES / NO      │             │    YES / NO      │             │    YES / NO      │
└──────────────────┘             └──────────────────┘             └──────────────────┘
```

### Why "Market-Level Reconciliation" Fails:
If you audit Market B ("Will Spain win?"):
* `/positions` shows: **1,392,932 YES shares**.
* `/activity` fills show: **99,999 shares bought**.
* **False Error:** 1,292,933 shares seem "missing" or "unaccounted for" if looking only inside Market B's silo.

### How "Event-Level Reconciliation" Works:
1. The trader bought **1,292,932 NO shares** on Market A (Argentina).
2. The trader clicked **Convert**:
   * Smart contract **burned** 1,292,932 `NO` shares on Market A.
   * Smart contract **minted** 1,292,932 `YES` shares on Market B (Spain) AND 1,292,932 `YES` shares on Market C (Draw).
3. Activity feed logged:
   * `BUY` 1,292,932 NO on Market A
   * `CONVERSION` on Market A
   * *Zero BUY rows on Market B or Market C.*
4. **Event Balance Sheet:**
   $$\text{Total Capital Outflow} = \text{Cost of Market A NO} + \text{Cost of Market B YES}$$
   $$\text{Total Shares Minted on Event} = 1,292,932 \text{ (Spain YES)} + 1,292,932 \text{ (Draw YES)}$$
   $$\text{Net Event Variance} = \$0.00 \quad \text{(Exact Match)}$$

---

## 4. Implementation Phases

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: INTERIM READINESS (NOW)                                              │
│ • Lock DB Schema for v2 Ingestion (`event_id`, `total_pnl`, $1/k$ factor)     │
│ • Enforce API / Frontend Dual-Domain Separation (Official `pm_*` vs DB Stats) │
│ • Submit Technical Integration Questions to Polymarket Team                   │
└───────────────────────────────────────┬───────────────────────────────────────┘
                                        │ (When v2 API releases this week)
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: UPSTREAM INGESTION (v2 DATA API LAUNCH)                              │
│ • Fetch restated positions from v2 endpoint for active fleet (~54k wallets)   │
│ • Ingest corrected $1/k$ cost basis, fixed August settlements, and `total_pnl`│
└───────────────────────────────────────┬───────────────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: FLEET CANONICAL RECOMPUTATION & VERIFICATION                         │
│ • Execute `backfill_canonical_metrics.py --active-only --concurrency 25`      │
│ • Atomically recalculate Core Metrics, 3-Tier Categories, and 10 Windows      │
│ • Verify 10/10 Invariants across all active wallets (`verify_canonical_metrics`)│
└───────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Interim Readiness (Current Sprint)
1. **Frontend & API Contract Hardening:**
   - Clearly separate official snapshot fields (`pm_pnl`, `pm_volume`, `pm_rank`, `pm_synced_at`) from internal canonical stats (`total_pnl`, `win_rate`, `resolved_count`, categories, windows).
   - Eliminate confusing cross-metric fallbacks (e.g. `COALESCE(pm_pnl, total_pnl)`).
   - Show internal timestamp `computed_at` alongside `pm_synced_at`.
2. **Schema Preparation for v2 Data:**
   - Ensure `wallet_closed_positions_v2` and `wallet_open_positions_v2` support:
     - `total_pnl` (explicit `realized_pnl + unrealized_pnl`)
     - `event_id` / `event_slug`
     - `k_outcomes` / conversion provenance tags

### Phase 2: Upstream v2 Data Ingestion (On Release)
1. Ingest clean v2 position records across the active fleet (~54,000 wallets).
2. Bounded keyset fetching with durable checkpointing (`artifacts/v2-ingest.checkpoint.json`).

### Phase 3: Canonical Recomputation & Audit
1. Run `src/scripts/backfill_canonical_metrics.py --active-only --concurrency 25`.
2. Recompute core metrics, category stats, and historical windows under PostgreSQL transaction-scoped advisory locks.
3. Run `src/scripts/verify_canonical_metrics.py` requiring 100% compliance across all 10 accounting invariants:
   1. Internal total PnL == sum of eligible ledger contributions.
   2. Root category PnL sum == internal total PnL.
   3. Subcategory PnL == sum of child league leaves.
   4. Winning count $\le$ resolved count.
   5. Win rate == $(\text{winning count} / \text{resolved count}) \times 100$.
   6. Rolling trade windows match exact newest-$N$ canonical slices.
   7. Price bucket partitions satisfy $\text{buys} = \text{wins} + \text{losses}$.
   8. Official Polymarket snapshots remain uncorrupted.
   9. Flagged-eligible positions remain included; explicit exclusions excluded.
   10. Position sorting tie-breaks deterministically by `(null_ca, ts, condition_id, outcome, asset_token_id)`.

---

## 5. Technical Questions for Polymarket Developer

1. **Shortcut for Activity vs. Position Reconciliation:**
   * Is there an event-level aggregation endpoint (e.g. lifetime volume/mints/settlement totals per event per wallet) so we don’t have to scrape and replay full lifetime activity histories just to audit position PnL?
2. **Backfill Readiness & Dirty Reads:**
   * When v2 drops, will historical data for all resolved markets already be fully restated with the $\$1/k$ basis and the August settlement corrections applied in-place, or will background migrations still be in flight?
3. **P2P / ERC-1155 Transfers Cost Basis:**
   * For positions acquired via direct on-chain P2P transfers, how will v2 treat the cost basis and `avg_price` in position rows (carried as $\$0.00$, marked-to-market at transfer block, or excluded from realized PnL)?
4. **Leaderboard / Account PnL vs. Position Sum Parity:**
   * In v2, will $\sum(\text{total\_pnl})$ over all open + closed positions strictly match the official leaderboard PnL for a wallet, or do account-level adjustments (collateral yield, cash balance adjustments) legitimately keep them different?
