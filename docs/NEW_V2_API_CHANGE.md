# Polymarket Data API v2 — What Changed, Impact on Us, What Is Still Unsolved

*Date: 2026-09-16*
*Sources: Predictions Changelog Sep 4 2026 entry (`/v2` live), Migrating from v1, Aug 10 2026 activity/positions notes, plus `docs/problem.md`, `docs/problem2.md`, `docs/report.md`, `docs/learner.md`, `docs/CORE_LOGIC.md`, `docs/V2_DATA_API_AND_METRICS_MIGRATION_PLAN.md`.*
*Live base: `https://data-api.polymarket.com/v2`. v1 frozen, still serving under Legacy.*

---

## 1. What changed (v1 → v2)

### 1.1 Response contract
| Area | v1 | v2 |
|---|---|---|
| Envelope | bare `list` / object | `{ data: [...], pagination: { next_cursor } }` |
| Pagination | `limit` + `offset` (caps: positions ~10k, closed ~100k, activity ~5k) | opaque `next_cursor` until `null`, no `offset` |
| Casing | `camelCase` (`proxyWallet`, `conditionId`, `totalBought`) | `snake_case` (`proxy_wallet`, `condition_id`, `total_bought`); request params accept both |
| Market selector | `market=` | `condition=` / `condition_id` (max 20 ids per call), `event_id` carries over |
| Position lifecycle | 3 routes: `/positions`, `/closed-positions`, `/v1/market-positions` | one route `GET /v2/positions?status=OPEN\|REDEEMABLE\|CLOSED` with `redeemable`, `mergeable` flags per row |
| Money encoding | ambiguous (`totalBought` shares vs USD mixed) | explicit: bare fields = shares, `*_usdc` fields = USD, JSON numbers |
| Load signaling | `429` with ad-hoc backoff | `429` + `Retry-After` header (must honor) |
| Rate limits | undocumented per-endpoint | per-family table on Rate Limits page |

Route map (unchanged behavior, new path): `/positions`→`/v2/positions`, `/closed-positions`→`/v2/positions?status=CLOSED`, `/trades`→`/v2/trades`, `/activity`→`/v2/activity`, `/value`→`/v2/value`, `/holders`→`/v2/holders`, `/oi`→`/v2/oi`, `/live-volume`→`/v2/live-volume`, `/v1/leaderboard`→`/v2/leaderboard`, `/traded`→`/v2/user-stats`, `/v1/approvals`→`/v2/approvals`. Only `GET /v1/accounting/snapshot` has **no** v2 counterpart — keep calling v1.

### 1.2 New endpoints (v2 only)
* `GET /v2/user-pnl` — cumulative wallet PnL series.
* `GET /v2/user-stats` — profile stats (covers old `/traded` distinct-market count; unknown user → `data: null`, not error).
* `GET /v2/user-volume` — windowed wallet volume.
* `GET /v2/biggest-winners` — biggest-wins board.
* `GET /v2/prices-history` — replaces CLOB-hosted price history; three window forms (`interval`, `start`/`end`, `as_of`), second-based `bucket_seconds`, cursor paginated.
* `GET /v2/resolutions` — resolution lifecycle state.
* `GET /v2/status` — data freshness.
* `GET /v2/holders?include_pnl=true` — per-holder entry + PnL economics.
* Builder leaderboard + volume (with `builderCode`).

### 1.3 Aug 10 2026 changes (shipped on v1, inherited by v2 — must handle now)
* `REDEEM` rows are **per outcome**: `asset`, `outcome`, `outcomeIndex` identify the settled outcome, `size` = tokens burned for that outcome, `usdcSize` = that outcome's payout. Redeeming both sides returns **two rows**; losing leg `usdcSize = 0`. Sum `usdcSize` per transaction for total payout.
* Position fee-basis fields: optional `grossInitialValue` (remaining entry basis incl. attributed buy fees) + `entryFeesUsdc` (fee component). `initialValue` / `avgPrice` stay **fee-exclusive**: fee-exclusive basis = `grossInitialValue - entryFeesUsdc`. Omitted = unavailable, never 0.
* `GET /positions?includeArchived=true` returns archived-but-active markets; default excludes them.
* `icon` on activity/trades falls back market → event.

### 1.4 SDK / status
* TS SDK Data methods now use v2; official v2 support floor `>=0.10.0` (TS + Python).
* v1 frozen: bug fixes only, all new fields/endpoints land on v2.

---

## 2. How it impacts and helps us

Traced against `problem.md` (§1–§12), `problem2.md` (6 core problems + 8 rules), `report.md` (4 root causes, 3 clusters), `learner.md` (§1, §14, §20, §22).

### 2.1 Pagination truncation — biggest win
* Solves: `problem.md:218-223` (7.5k/30k ceiling, forced reconciliation pitfall), `problem2.md` Problem 5/6, `report.md` Root Cause D, `learner.md:99-109` (`/positions` 10.5k offset-10000 repeat), `learner.md:908-943` (deep-offset repeats, offset-100000 ceiling, activity 0–5000 bisection).
* Cursor (`next_cursor until null`, consistent feed while rows arrive) removes wrap-around detection, repeated-page guards, timestamp-window bisection, and the accounting-snapshot partition fallback as the *normal* path.
* Code to rewrite: `src/workers/wallet_trade_history.py:75-128,400-440,522-748`, `src/workers/leaderboard_stats.py:144-343`, `src/scripts/audit_position_activity_coverage.py:180-242`, `src/workers/activity_backfiller_worker.py`, `src/workers/activity_analyzer_worker.py`. End condition becomes `next_cursor is None`; `len(page) < limit`, `offset > 5000/100000` checks must go.

### 2.2 Two-source closed-position merge — simplified
* Solves: `problem2.md` Rule 1, `learner.md:580-583` (closed = redeemed/sold only; `/positions redeemable+currentValue==0` = expired $0 losers; BreakTheBank 329 vs true 733).
* `v2/positions?status=` + row flags (`redeemable`, `mergeable`) make concluded-but-unclaimed vs redeemed explicit in one feed. Our `is_redeemable` sync (`positions_open_backfill.py`, `h1i2j3k4l5m6` migration) stays valid but the second fetch disappears.
* `includeArchived` must be set explicitly or archived whales silently lose rows.

### 2.3 Mint / conversion basis — restatement, not magic
* Helps: `problem.md:5-94` ($12.93M phantom loss, `totalBought=0` + `avgPrice=0.50` + `cashPnl=-(size×price)`), `report.md` Root Causes A–C, Cluster 2 mint-bot explosion (up to +$1.69B over-credit on `classified`), `learner.md:1059-1076` (`$1/k` conversion basis post Sept-7 Goldsky offload, event-level reconciliation).
* v2 gives restated cost basis + explicit per-row `total_pnl = realized + unrealized` + event-level metadata (`V2_DATA_API_AND_METRICS_MIGRATION_PLAN.md:21`). Anything fetched **pre-Sept-7 is stale by definition** and must be refetched — do not fleet-recompute legacy rows (plan §2 decision, still correct).
* Our Axiom of Maximum Loss (`CORE_LOGIC.md:107-109`, `src/pnl/rules.py:68-76`) and `remaining_cost = min(initialValue, totalBought×avgPrice)` (`CORE_LOGIC.md:99-105`) **stay** as guards; v2 reduces how often they fire, it does not replace them.

### 2.4 Fee basis + REDEEM split — correctness fixes we must adopt
* `grossInitialValue - entryFeesUsdc` gives the true remaining basis our `initialValue`-only math was missing; treating omitted as `None` matches the Never Assume rule (`learner.md:643-648`).
* Per-outcome `REDEEM` fixes Attempt 2/3 cashflow math (`problem2.md:57-73`, `learner.md:895-906`): aggregate `sum(usdcSize)` per `transactionHash`, keep both legs. Single-row assumption double-counts or drops the $0 leg. Affects `activity_backfiller_worker.py`, `activity_analyzer_worker.py`, `scripts/backtest_activity_pnl.py`.

### 2.5 Shares vs USD + 429 handling — small, high-leverage
* Explicit shares vs `*_usdc` ends the volume bug (`problem.md:105-109`, `positions_metrics_compute.py:117,158,233` summing `total_bought` as USD).
* Honoring `Retry-After` replaces fixed `sleep 0.5×/2×` in `src/utils/polymarket_rate_limit.py:25-45`, `wallet_trade_history.py:675-678,764-783`, `leaderboard_stats.py:197-213`. Rename buckets to v2 families.

### 2.6 New reads replace our workarounds
| Instead of … | Use … |
|---|---|
| Supabase `wallet_pnl` ledger anchor (`problem.md:218-223`) | `/v2/user-pnl` |
| `/traded` distinct-market count | `/v2/user-stats` (`data: null` = unknown) |
| Turnover vs entry confusion (`problem.md:147-159`) | `/v2/user-volume` |
| Empty `markets_v2.winning_outcome` join (`problem.md:98-101`) | `/v2/resolutions` |
| Gamma `condition_id` mismatch (`learner.md:118-123`) | `/v2/prices-history` |
| `*_synced_at` completeness heuristics | `/v2/status` |
| Holder PnL inference | `/v2/holders?include_pnl=true` |
| Curated discovery scans | `/v2/biggest-winners`, builder leaderboard/volume |

`src/pnl/ledger.py:211-238` already dual-aliases camel/snake — ready. `src/pnl/rules.py:42-76` is camelCase-only — must extend or v2 rows parse as 0.

---

## 3. What is still NOT solved — analysis

1. **Position-sum vs leaderboard parity.** v2 per-row `total_pnl` does not promise `Σ(total_pnl over open+closed) == leaderboard PnL`. Collateral yield, rebates, mid-trade cash, unredeemed escrow (`report.md:149-151`, `learner.md:822-825`), and netted split/merge arb leave a legitimate gap (median 106.9% relative error on 12-wallet cohort, `learner.md:650-655`). Keep the dual-engine split (`CORE_LOGIC.md:112-117`): `pm_*` = headline truth, ledger = win-rate/category/window analytics. Never `COALESCE` or scale one to the other.
2. **P2P / transfer cost basis.** v2 open question 3 in migration plan §5 still stands: transfers prove shares (`verified_transfer_in`), not purchase cost. No v2 field turns a transfer amount into basis. Keep lineage as provenance-only (`learner.md:39-49,79-85`).
3. **Pre-Sept-7 + August-glitch history.** Restatement + Aug 7/24/31 settlement corrections (migration plan §1) only help on refetch. Stored rows keep stale `$0.50` basis and missing settlements until re-ingested. Fleet-wide recompute before refetch just bakes the rot in.
4. **CTF multi-leg economics.** `$1/k` + event metadata reduce Cluster-2 blowups but row-grain summation of a 10-outcome mint still needs event-level pairing for true market PnL. Keep independent `(condition_id, outcome)` win grain (`problem2.md:137`, `CORE_LOGIC.md:74-83`) and never synthesize `1 - buy_p` legs (`learner.md:877-880`).
5. **Eligibility / provenance debt.** 3.25M legacy synthetic legs lack provenance (`problem2.md:175-180`); `metrics_eligible` gate (`m6n7o8p9q0r1`) still needs evidence-backed audits. v2 does not clean old rows.
6. **Snapshot dependency.** `/v1/accounting/snapshot` (complete `(conditionId, asset)` inventory for capped wallets, `CORE_LOGIC.md:84-89`) has no v2 counterpart. Keep the v1 call + market-partitioned recovery; do not delete that path.
7. **Missing adapter.** Migration plan claims `src/pnl/v2_adapter.py` + Phase-1 complete — file does not exist (verified 2026-09-16). Required before any fleet work: envelope/cursor/alias normalizer → `normalize_closed_row`, persisting `event_id/event_slug`, `source_total_pnl`, fee basis, `mergeable`, `outcome_index` (see §4).

---

## 4. DB / code changes needed (summary — full plan in chat 2026-09-16)

*New revision, all additive/nullable, no rewrites:*
* `markets_v2`: `+ event_id TEXT`, `+ is_archived BOOL DEFAULT FALSE`, `+ resolution_status TEXT`, `+ archived_at TIMESTAMPTZ` (`event_slug` already exists).
* `wallet_positions_v2` / `wallet_closed_positions_v2`: `+ source_total_pnl NUMERIC`, `+ gross_initial_value NUMERIC`, `+ entry_fees_usdc NUMERIC`, `+ is_mergeable BOOL`, `+ outcome_index INT`, `+ event_id TEXT`; plus `+ is_redeemable BOOL` on the open table (closed already has it).
* `wallet_activity_events_v2`: `+ outcome_index INT` (grain already supports 2-rows/tx).
* `wallet_metrics_v2`: `+ v2_synced_at TIMESTAMPTZ`, `+ v2_api_version TEXT DEFAULT 'v1'`; `wallet_activity_scan_state_v2`: `+ next_cursor TEXT`, `+ retry_after_until TIMESTAMPTZ`; `data_api_rate_limit_buckets`: `+ retry_after_until`, v2 family seeds.
* New: `wallet_pnl_series_v2`, `market_price_history_v2`, `market_resolutions_v2`, `wallet_holder_economics_v2`, `builder_stats_v2`.
* Code: build `src/pnl/v2_adapter.py`; port the 5 fetchers above to cursor + `condition` (≤20) + `status`; fix REDEEM aggregation, fee basis, `Retry-After`, `rules.py` snake_case; bump SDK `>=0.10.0`.

*Rollout: canary 10 → 100 → 2500 read-only diff → refetch post-Sept-7 active fleet → `backfill_canonical_metrics --active-only` → 10/10 invariant verify → flip `v2_api_version`.*
