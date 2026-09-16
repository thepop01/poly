# Architecture Suggestions & Performance Optimization Roadmap

This document outlines architectural improvements and optimization strategies to eliminate full-database sweeps and transition PolyTracker to an **Incremental, Event-Driven, and Delta-Computed Pipeline**.

---

## 1. The Core Challenge: Full-Database Sweeps

Currently, the compute pipeline processes **428,211 wallets** across tens of millions of position rows:
* **The Inefficiency:** On any given day, only **~1,500 to 5,000 wallets** execute new trades or have markets conclude. Running a full batch scan across all 428k wallets wastes 98%+ of database I/O and CPU cycles.
* **The Whale Bottleneck:** For high-volume accounts like `swisstony` (50,000+ positions) or `RN1` (90,000+ positions), scanning and aggregating the full historical ledger takes 1–2 seconds per whale.

---

## 2. Recommended Optimization Strategies

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   EVENT-DRIVEN ARCHITECTURE PIPELINE                                     │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘

   [ Polygon EVM Trade Tracker ]  ──┐
   [ Closed Positions Fetcher  ]  ──┼──► Redis / Postgres `dirty_wallets` Queue ──► Targeted Compute Worker
   [ Redeemable Payout Tracker ]  ──┘      (Only 1,000 – 3,000 active wallets)        (Sub-second processing)
```

---

### **Strategy A: The "Dirty Wallet" Event Queue (Highest Priority)**

Instead of scanning all wallets on a fixed timer, transition to **Reactive Invalidation**:

1. **Trigger Points:**
   Whenever any of the following ingestion workers updates data for a wallet, it pushes the wallet address into a Redis Set (or PostgreSQL dirty table):
   * `positions_closed_backfill.py` (when a new trade settlement is written).
   * `positions_open_backfill.py` (when an open position is concluded/redeemed).
   * `trade_tracker.py` (when an on-chain `OrderFilled` event occurs).
2. **Compute Consumer:**
   The compute workers (`compute_core_metrics`, `compute_category_stats`, `compute_historical_windows`) pull directly from `dirty_wallets_queue`:
   ```python
   # Redis Example:
   dirty_wallets = await redis.spop("dirty_wallets_queue", count=100)
   ```
3. **Impact:**
   * **99% reduction in compute load:** Computes only the ~2,000 actively changing wallets per day.
   * **Near real-time updates (<3s latency):** A trader's win rate and PnL update immediately upon trade execution.

---

### **Strategy B: Staleness Watermark Gating (SQL-Layer Filter)**

If scheduled batch jobs are executed, gate the query directly at the database layer using timestamp comparisons:

```sql
SELECT address FROM wallet_metrics_v2
WHERE (
    closed_synced_at > computed_at OR 
    open_synced_at   > computed_at OR 
    last_trade_at    > computed_at OR
    computed_at IS NULL
)
ORDER BY COALESCE(pm_volume, total_volume, 0) DESC;
```

* **How it works:** PostgreSQL checks indexed timestamp columns and skips 420k+ untouched rows in milliseconds.
* **Prerequisite Index:** `CREATE INDEX idx_metrics_staleness ON wallet_metrics_v2 (computed_at, closed_synced_at, open_synced_at, last_trade_at);`

---

### **Strategy C: Delta Accumulator Pattern (For Whales with 50k+ Rows)**

For accounts with tens of thousands of historical positions, avoid re-aggregating the full history from scratch on every single bet.

1. **Base Snapshot Storage (`wallet_metrics_v2`):**
   * Store historical checkpoint metrics: `base_pnl`, `base_wins`, `base_resolved`, `base_volume`, and `last_processed_closed_at`.
2. **Incremental Delta Query:**
   When 2 new markets resolve, only query records newer than the checkpoint:
   ```sql
   SELECT condition_id, outcome, realized_pnl, total_bought, avg_buy_price
   FROM wallet_closed_positions_v2
   WHERE address = $1 AND closed_at > $2;
   ```
3. **Delta Merging:**
   $$\text{Total Wins} = \text{base\_wins} + \sum \text{new\_wins}$$
   $$\text{Total Resolved} = \text{base\_resolved} + \text{count}(\text{new\_markets})$$
   $$\text{Total Volume} = \text{base\_volume} + \sum \text{new\_usd\_volume}$$
4. **Impact:** Reduces per-whale compute latency from **`2,000ms → 1.5ms`**.

---

### **Strategy D: Adaptive Tier Cadence & Dormancy Freezing**

Align computational frequency with wallet activity profiles:

| Wallet Tier / Status | Criteria | Compute Frequency |
|---|---|:---:|
| **Curated & Whales** | PnL > $10k, Active Daily | **Real-time / Every 5 mins** |
| **Standard Active** | Traded within 30 days | **Every 6–12 hours** |
| **Low Balance / Inactive** | Balance < $1k, Low volume | **Once every 24–48 hours** |
| **Hibernating / Dormant** | Inactive > 30 days | **Frozen (0 compute cycles)** until a new EVM event awakens the wallet |

---

## 3. Implementation Phases

| Phase | Milestone | Expected Latency Reduction |
|---|---|:---:|
| **Phase 1** | Implement **SQL Staleness Gating** across all compute workers | 45 mins → 2 mins |
| **Phase 2** | Add **Redis / PostgreSQL Dirty Queue** for reactive compute triggers | 2 mins → 5 seconds |
| **Phase 3** | Implement **Delta Accumulators** for 5,000+ position whale accounts | 1.5s per whale → 2ms |
| **Phase 4** | Apply **Adaptive Tier Scheduling** in the Master Orchestrator | Complete resource optimization |
