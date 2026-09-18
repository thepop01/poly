# Polymarket v2 Data API — Reconciliation & Backfill Plan

Plan of record for migrating the PnL pipeline onto the Polymarket v2 Data API, replacing inferred cost-basis repairs with source-provided basis, and re-baselining the ~9k >10% divergence roster.

<aside>
⚠️

Two questions to Polymarket are still open (P2P transfer cost basis, leaderboard vs position PnL parity). Phases 0–3 do not depend on them. Phase 4 does. Do not block on answers.

</aside>

## Guiding principles

1. **v2 is the source of cost basis.** Stop deriving it. Every existing repair rule becomes fallback-only for pre-Sept-7 rows and logs loudly when it fires.
2. **Reconcile at event grain, not market grain.** A `CONVERSION` on any question of an event authorizes minted legs across all sibling questions.
3. **Positions is the PnL source; activity is evidence.** Never backfill activity fleet-wide to compute PnL.
4. **Never force a match.** `pm_pnl` minus position PnL is a stored, decomposed residual — not an error to be scaled away.
5. **Refetch, don't recompute.** Pre-Sept-7 rows carry a 0.50 conversion basis instead of 1/k. Recomputing bakes the error in.

---

## Phase 0 — Blockers (do first, nothing else can start)

- [ ]  **Build `src/pnl/v2_adapter.py`.** Does not exist today despite the migration plan claiming Phase 1 complete. Responsibilities: envelope/cursor normalization, `status=OPEN|REDEEMABLE|CLOSED`, `condition` batching (≤20 ids), field aliasing, persisting `event_id`, `source_total_pnl`, `entry_cost_usdc`, `total_cost_usdc`, `entry_fees_usdc`, `mergeable`, `outcome_index`.
- [ ]  **Extend `src/pnl/rules.py` to snake_case.** It is camelCase-only (3.1KB), so every v2 row currently parses as 0. This is a silent-zero bug, not a crash.
- [ ]  **Alembic migration: `event_id`** on `markets_v2`, `wallet_positions_v2`, `wallet_closed_positions_v2`, plus the new cost columns and provenance columns (Phase 3). Additive only, nullable, backfilled after.
- [ ]  **Honor `Retry-After`** in `src/utils/polymarket_rate_limit.py` instead of fixed sleeps.
- [ ]  **Fix REDEEM aggregation**: per-outcome rows since Aug 10, two rows per tx when both sides redeemed, losing leg `usdcSize = 0`. Sum by `transactionHash`.

**Exit gate:** adapter round-trips a real v2 positions page for one known wallet and reproduces position PnL to the cent.

---

## Phase 1 — Row ledger with hard identity checks

Enforce on ingest. A failing row is **quarantined, not repaired**.

| Invariant | Meaning |
| --- | --- |
| `total_cost_usdc == entry_cost_usdc + entry_fees_usdc` | gross = net + fees |
| `total_pnl == realized_pnl + unrealized_pnl` | row internally consistent |
| `avg_price ≈ cost / total_size` | pin down net vs gross first (open question 1) |
| `current_size <= total_size` | size sanity |

Derive rather than store guesses:

```
settled_size   = total_size - current_size      # sold + redeemed + converted away
remaining_cost = current_size * avg_price        # replaces min(initialValue, totalBought*avgPrice)
current_value  = unrealized_pnl + remaining_cost
```

- [ ]  Implement invariants + quarantine table with failure reason.
- [ ]  Replace `CORE_LOGIC.md` §3 `remaining_cost` formula with `current_size * avg_price` (the old `min(initialValue, ...)` double-charged already-sold shares).
- [ ]  **Demote repair rules to fallback**, gated on `fetched_at < 2026-09-07`:
    - zero-cost ingestion guard (`total_bought <= 0.01` → `realized_pnl = 0`)
    - Universal Maximum Cash Loss Cap
    - synthetic `shares × 1.00` unredeemed-winner credit
    - Every firing emits a data-quality event with wallet, row, rule name.
- [ ]  **Purge the 3.25M synthetic `1 - buy_p` opposite legs** from the removed reconcile script. These are provably fabricated — the opposite leg was usually minted, not bought.
- [ ]  **Remove `total_pnl` anchoring to `pm_pnl`.** `ARCHITECTURE_AND_WORKERS.md` still documents `compute_core_metrics.py` as anchoring to `pm_pnl`; verify it's actually gone from code and not just from `leaderboard_stats.py:1063`.

**Exit gate:** for a 20-wallet cohort, `Σ total_pnl (OPEN + CLOSED)` matches v2 exactly. Regression test pinned on the known value: wallet `esennt` = **1,754,036.82**.

---

## Phase 2 — Residual as a first-class number

Three quantities, never scaled into each other:

1. `position_pnl = Σ total_pnl (OPEN + CLOSED)` — must match v2 exactly. This is the regression test.
2. `pm_pnl` — leaderboard cash-equity delta. Display only.
3. `residual = pm_pnl - position_pnl` — **stored column**, then decomposed.
- [ ]  Add `residual`, `residual_explained_*`, `unexplained_residual` to `wallet_metrics_v2`.
- [ ]  Decompose residual into named buckets from `/activity` types (reward, rebate, yield) and on-chain lineage. Remainder stays as `unexplained_residual`.
- [ ]  **Re-baseline the escalation trigger.** `activity_backfiller_worker.py` currently escalates on `abs(total_pnl - pm_pnl) >= 10000` or `>= $1k and >= 10%` — a bare `pm_pnl` comparison that `CORE_LOGIC.md` explicitly forbids. New trigger: Phase-1 identity failure **or** large `unexplained_residual`.
- [ ]  **Quarantine the Polymarket-side ledger bug.** Markets resolving **Aug 7, Aug 24, Aug 31** had settlement not applied and some fills missed, corrupting their leaderboard *and* the `total_size`/`avg_price` they served. `current_size` unaffected. Flag affected wallets, exclude from the divergence roster, re-fetch after their scheduled correction lands.

**Exit gate:** the ~9k roster is re-classified into (a) real Phase-1 failures, (b) Gap-1 account-level residual — expected and fine, (c) Aug 7/24/31 quarantine, (d) pre-Sept-7 stale basis pending refetch. Expect most of the 9k to fall into (b) and (d).

---

## Phase 3 — Provenance flags at event grain

Per row, reconstruct how shares were acquired:

`fills_size`, `conversion_mint_size`, `split_size`, `transfer_in_size`, and the shortfall `unattributed_size = total_size - Σ(rest)`.

- [ ]  **Re-grain the activity audit from market to `event_id`.** A `CONVERSION` on any sibling question authorizes minted legs across the whole event. Today's four-way classes (`direct_activity_buy`, `activity_same_leg_nontrade`, `activity_outcome_differs`, `activity_absent`) treat the *expected* state of a minted leg as suspicious — the "Spain 1,392,932 shares vs 99,999 fills" case is exactly this false positive.
- [ ]  **Audit `metrics_eligible = FALSE` rows.** If any audit ran on `activity_absent` or `activity_outcome_differs`, it excluded legitimate conversion-minted rows. Review every exclusion and its recorded evidence; restore unjustified ones.
- [ ]  Add `cost_basis_confidence` (`high` / `low`). Set `low` when `transfer_in_size > 0` or `unattributed_size > 0`.
- [ ]  **Low-confidence rows stay in position PnL** (they're real positions) but are **excluded from ROI, win rate, and price-bucket analytics**, and surfaced separately in the UI.

**Exit gate:** on a sample of known neg-risk conversion wallets, `unattributed_size ≈ 0` and no minted leg is flagged as a contradiction.

---

## Phase 4 — Backfill execution (tiered)

v2 gives cursor/keyset pagination, so the constraint is throughput, not design. Reframing activity as *evidence* rather than *PnL source* removes most of the cost.

| Tier | Scope | Source | Cost |
| --- | --- | --- | --- |
| 1 | **All wallets** | `/v2/positions`, cursor-paginated, both statuses | Cheap — this is the entire PnL ledger |
| 2 | Phase-1 failures + large `unexplained_residual` | Full `/activity`, `start`/`end` partitioned | Bound to low thousands of wallets, not 361k |
| 3 | `cost_basis_confidence = 'low'` rows only | On-chain ERC-1155 lineage | Smallest cohort |

Two things make the one-time cost survivable:

- **Partition activity by time window, not offset.** Windows parallelize; offsets don't. Polymarket explicitly recommended `start`/`end` control.
- **Persist the cursor as a per-wallet watermark**, so the expensive crawl happens exactly once and everything after is a delta.
- [ ]  Tier 1 sweep on the active fleet (post-Sept-7 data only).
- [ ]  Do **not** fleet-recompute pre-Sept-7 rows — refetch them. They carry 0.50 conversion basis instead of 1/k (on a 17-way exact-score event that's an ~8.5x overstated cost basis).
- [ ]  Keep `/v1/accounting/snapshot` — no v2 counterpart, still the only complete inventory for offset-capped wallets.
- [ ]  Deep-history recovery stays opt-in and explicit; never enabled implicitly by the scheduled worker.

---

## Open questions to Polymarket

Send these; 2 and 3 are what turn "next best" into "as good as it gets."

1. Is `avg_price` net or gross of `entry_fees_usdc` — `entry_cost_usdc / total_size` or `total_cost_usdc / total_size`?
2. **P2P/ERC-1155 transfers (unanswered):** what is `avg_price` / `entry_cost_usdc` on a transferred-in position — `0`, transfer-block mark, or excluded from PnL? Is there a field identifying acquisition type?
3. **Leaderboard parity (unanswered):** should `SUM(total_pnl)` equal leaderboard PnL, or are rebates / rewards / collateral yield / cash adjustments legitimately outside it? If outside, is there an endpoint for those account-level items?
4. Resolved-but-unredeemed (`redeemable = true`): do those rows return under OPEN or CLOSED, and does `unrealized_pnl` mark them at $1.00 or last trade price? Decides whether OPEN + CLOSED double-counts or drops them.
5. Does a v2 `CONVERSION` activity row carry the event id and the minted token legs, or is it still one row on the source question with no token id?

---

## Why there is no perfect solution

Every field in the v2 positions row is **position-scoped**. Nothing in it is account-scoped. Two gaps are therefore structurally irreducible:

- **Gap 1 — account-level cash items.** Maker rebates, liquidity rewards, collateral yield, referral credits, gas subsidies, direct USDC in/out. The leaderboard is a cash-equity delta; position PnL is a contract-level sum. No arrangement of the ten fields produces one from the other. Polymarket's wording was careful: "the sum of `total_pnl` over OPEN plus CLOSED is your **position PnL**."
- **Gap 2 — acquisitions with no price.** A transferred-in token has real size but no meaningful acquisition price for the receiving wallet. `avg_price = 0` inflates PnL; a transfer-block mark invents a cost never paid; exclusion breaks size reconciliation. All three are conventions, not facts.

The achievable target is an **exactly-reconciling row ledger plus an explicitly decomposed residual** — which is what Phases 1–3 build.

---

## Verification status

| Item | Status |
| --- | --- |
| Docs reviewed (`problem.md`, `problem2.md`, `report.md`, `CORE_LOGIC.md`, `ARCHITECTURE_AND_WORKERS.md`, `NEW_V2_API_CHANGE.md`) | Passed |
| `src/pnl/v2_adapter.py` absent — confirmed against repo tree | Passed |
| `rules.py` camelCase-only silent-zero risk | Not run (needs file read) |
| `compute_core_metrics.py` still anchoring to `pm_pnl` | Not run (needs file read) |
| Any code changes | Not run — no commits made |