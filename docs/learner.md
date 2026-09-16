# Learner Log — Polymarket Analytics Platform

*Last Updated: 2026-09-04*

### Position sync must persist market metadata, not just positions (2026-09-04)

**What went wrong:** Neither position backfiller wrote `markets_v2` — 38% of opens and 15% of eligible closed rows joined to nothing and collapsed into OTHER/blank. The payloads already carried `title`/`eventSlug`; they were read and dropped.

**Fix:** Shared `src/workers/market_metadata.py::upsert_position_markets`, called by both open and closed sync per wallet. Pure title-classifier taxonomy (zero API calls); the conflict clause only fills OTHER/blank slots, never overwrites curated values (mirrors the legacy winrate guard). Gamma series enrichment of the stored slugs stays offline. Covered by `tests/test_market_metadata.py` (create/preserve/upgrade/skip). This stops regrowth; the existing backlog still drains via value-ranked backfill.

### Value-ranked backfill beats blind order by 40x (2026-09-04)

**What went wrong:** The missing-markets backfill processed markets in arbitrary DB order: 30k attempts yielded ~350 inserts (~1%) because the backlog tail is dead markets. Throughput tuning was irrelevant — yield was the constraint.

**Fix:** Enumerate by position value (`SUM(current_value)` for opens, `SUM(ABS(realized_pnl))` for closed) descending. First 5k value-ranked chunk: **2,253 inserts (45%) linking $15.66M of open position value in 5 minutes**, with modest 429s at concurrency 20. Lesson: when the backlog is mostly dust, ordering dominates every other optimization; measure hit rate per chunk and stop when it decays.

### Backfill concurrency: measure the knee, the APIs set the ceiling (2026-09-04)

**What went wrong:** Raising the missing-markets backfill from 10 to 200 concurrent workers changed nothing (same ~25s per 500 markets). A sweep with `scripts/bench_backfill_concurrency.py` (exact production pipeline, no writes) showed why: throughput scales to ~20 workers, then the APIs throttle — 40 workers drew 117× 429s per 250 markets for only 1.8× speed, 80 was *slower* than 40 (thrash), and `would_insert` was 0 across every slice because the live head was already drained and the tail is dead markets.

**Fix:** Default the script to `--concurrency 20` (peak 429-free band, polite to the shared limiter buckets live workers use), count 429s in `STATS` and log them per batch, and dedupe the two holder picks (often the same wallet). Rule of thumb: when raising concurrency stops helping, the ceiling is server-side — measure with the bench script instead of guessing, and spend the budget on ordering (value-ranked) rather than workers.

### League taxonomy must come from Gamma series, not just tags (2026-09-04)

**What went wrong:** The Wallets page league filter showed only IPL for Cricket while Polymarket lists dozens of leagues. League values came only from a small tag map (`LEAGUE_MAP` knew 4 cricket leagues) plus title regexes, so everything else stored blank. Gamma event payloads already carry the answer in `series` (e.g. "JCL T20", "Indian Premier League") — the fetchers read `tags` and ignored `series` entirely.

**Fix:** `extract_series_league()` canonicalizes the series title through the tag map ("Indian Premier League" → IPL) and keeps unknown series raw. Both market-resolution paths (`gamma_market_cache` live path, `backfill_gamma_categories` fleet path) use it as a league fallback for SPORTS, and the title classifier learned IPL/T20-World-Cup/Ashes rules. A guard refuses leagues from another subcategory's taxonomy (caught 26 miscategorized markets, e.g. NCAA Football tags on Cricket-stored rows). `backfill_league_series.py` fills blanks only (never overwrites) and recomputes only wallets touching updated markets; `recompute_cricket_wallets.py` resumes from a scratch progress file. Category stat recomputes are per-wallet idempotent, so a killed run leaves recomputed wallets consistent and stale ones merely outdated — never corrupt.

### Research Hub: normalize result sets, keep SQL set-based, scope refs by chat (2026-09-04)

**Result sets are normalized, not embedded in prompts:** the model receives compact summaries plus opaque result-set IDs (last 30 messages, last 20 summaries, member payloads excluded). Follow-ups (“those wallets”) resolve to the most recent compatible result in the same chat, with explicit label matches beating recency. This keeps prompts small and makes “all of them” verifiable against the stored row count.

**Tool SQL is set-based:** wallet collections resolve once through a `research_result_members → research_result_sets → research_chats` CTE joined to position tables — never one query per wallet. Query-plan tests assert no non-CTE subplans and index-assisted position access for a 100-wallet set. On 150M+ row tables, prefer `CREATE INDEX CONCURRENTLY` outside the migration transaction; a transactional multi-statement migration will stall the whole upgrade and wedge later DDL behind its locks.

**Stream errors become events after headers are sent:** once NDJSON streaming starts the status code is fixed, so every failure path (unknown tool, timeout, disconnect, provider error) maps to one terminal `run.failed` with a stable client-safe code. Provider exceptions and SQL text stay in server logs with run/chat/hashed-owner IDs only.

**Result references are always scoped through chat ownership:** every analytics entry point re-checks `research_chats.owner_id` before touching position tables, repository mutations join through `research_chats` in a single statement, and cross-owner IDs return 404 — never 403 — so existence is not revealed.

### Lineage is provenance, not cost basis (2026-09-02)

**What went wrong:** A position without a `/activity` BUY can have arrived through an ERC-1155 P2P transfer. Treating it as an unexplained or fabricated purchase loses real provenance; treating the transfer amount as a purchase cost fabricates PnL.

**Fix:** Worker 3 now backfills complete incoming/outgoing CTF ERC-1155 transfer history before Worker 4 analyzes its pending Activity snapshot. `audit_position_activity_coverage.py` only accepts a transfer when its exact token ID matches the position row's `source_asset`; it records transfer shares/count/time and `verified_transfer_in`, but leaves cost basis unknown and metrics unchanged. Wallet-level USDC funding is deliberately excluded from position-grain acquisition proof. `t3u4v5w6x7` and `u4v5w6x7y8` make transaction log index, event type, and asset part of lineage identity so distinct same-transaction outcome-token events are retained.

### Canonical transfer evidence must reach the lineage ledger (2026-09-02)

**What went wrong:** The original lineage migration copied transfers only at migration time. The live P2P tracker continued filling `wallet_position_transfers_v2`, leaving `wallet_lineage_trades_v2` empty.

**Fix:** `backfill_lineage_trade_ledger.py` materializes the canonical table into the lineage ledger in resumable source-ID batches, and `position_and_funding_tracker.py` writes both incoming and outgoing ledger records when it observes a new transfer. The ledger is now complete accounting evidence, while the canonical transfer table remains the exact source for position-grain matching.

### Position refresh concurrency and scope (2026-09-02)

**What went wrong:** Position workers excluded hibernated wallets and used an 84-hour source freshness window. Increasing task count without increasing connection-pool headroom can starve the shared endpoint limiter, causing apparent throughput gains to turn into timeouts.

**Fix:** Open and closed backfillers now include every wallet tier at a 48-hour source freshness boundary. They default to configurable 100-way task concurrency (double the prior value), 1,000-wallet batches, and pools with at least 140 connections. This leaves capacity for the separate 100-way Activity workers; the shared PostgreSQL rate limiter is deliberately unchanged and remains the actual request ceiling.

**Scheduling note:** Worker 3’s complete-history Activity batches are intentionally bounded but now wait 15 minutes rather than six hours between cycles. Long inter-batch sleeps can dominate a large divergence queue even when API and database capacity are otherwise available.

### Dormancy cannot exclude its own recovery source (2026-09-02)

**What went wrong:** `last_trade_sweeper.py` only scanned active wallets. Once an outdated or null `last_trade_at` moved a wallet to hibernated, the sweeper could never inspect its newer `/activity` event and wake it.

**Fix:** The sweeper now includes hibernated wallets and prioritizes never-swept rows. It only wakes a wallet from a real Activity timestamp within the 30-day dormancy window; it never assumes activity from a position refresh, deposit, or missing response.

### Repository hygiene (2026-09-02)

Generated evidence is useful locally but is not source code. Runtime output belongs under `logs/`; one-off diagnostics, backtests, exports, generated reports, and temporary wallet evidence belong under `scratch/`. Both locations are Git-ignored. Keeping the root restricted to configuration and entry points makes it clear which files are maintained and prevents accidental commits of multi-gigabyte caches or one-off investigation scripts.

This is the team's learning journal. It captures hard-won lessons from live debugging sessions: what the right approach is, what the wrong approach was, what we tried that didn't work, and exactly how we fixed it. Read this before touching win-rate, PnL, or backfill code.

## Operating rule

The canonical procedure is [docs/rule.md](rule.md). Follow its phase ordering and completeness gates before changing metric code: refresh source positions, stage Activity and lineage evidence, analyze the exact staged snapshot, then compute derived metrics. Preserve contradictory rows as evidence and never force local PnL or win rate to match Polymarket.

### Drain active Activity work without amplifying database pressure

Worker 3 previously slept for the full 15-minute interval after every batch, even when more divergence wallets were queued. That made the lineage gate look stalled. The loop now waits only 10 seconds after a non-empty batch and keeps the longer delay when no candidates exist. Lineage HTTP fan-out is 30 by default (configurable via `LINEAGE_HTTP_CONCURRENCY`); wallet concurrency remains 100 because increasing it further caused database connection timeouts.

### Historical lineage scans are optional provenance, not an analysis gate (2026-09-03)

The Alchemy transfer scan must paginate a wallet's complete ERC-1155 CTF history in both directions, including transfers unrelated to a disputed position. It is too slow and provider-limited to run as a prerequisite for every Activity audit. Polymarket `/activity` documents trade, redeem, split/merge, rewards/rebates, conversion, deposit/withdrawal, and yield events—but not P2P token transfers. Historical lineage workers are therefore paused. Worker 4 analyzes a complete staged Activity snapshot without `lineage_baseline_complete`; any existing exact-token transfer evidence remains optional provenance and cannot change cost basis or canonical metrics.

### Full Activity snapshots require bounded database fan-out (2026-09-03)

Some whales have hundreds of thousands of stored Activity events. Launching 100 full-snapshot reads at once saturated PostgreSQL with `ClientWrite` and tuple-lock waits. Worker 4 therefore uses 20 concurrent wallets and 100-wallet batches by default; increasing it requires checking active database waits, not merely CPU usage.

**Sections:** 1–5 cover the win-rate/PnL/backfill deep-dive (likebot, coinman2, etc.). Section 6 is the early-session bug log (percentage-scale, curation, timestamps, combo parlays, orchestration). Section 7 covers inherited-capital ROI. Section 8 covers trade retention, lineage separation, and storage cleanup. Section 9 covers the total_pnl overwrite bug and ROI formula fix using the Polymarket activity API.

## 10. Incremental Activity Evidence (2026-09-02)

**What went wrong:** Persisting every `/activity` payload in the hot PostgreSQL table scales poorly, and treating a same-leg SELL/REDEEM as proof of a BUY can invent acquisition cost and distort win rate.

**Fix:** Migration `r1s2t3u4v5` adds position-grain lifecycle aggregates, a timestamp plus event-hash watermark, deduplicated exception-event storage, Activity-only market state, and archive manifests. The audit worker processes the complete baseline (or a 24-hour-overlapped incremental window), stores compact BUY/SELL/REDEEM/SPLIT/MERGE/CONVERSION/reward/rebate/yield facts, keeps only the newest 500 raw hot events per wallet, and retains raw evidence only for contradictory/lifecycle markets. `lifecycle_without_acquisition` remains review-only until a BUY, transfer, conversion, or accounting snapshot proves the origin. Wallets are escalated at `$10,000` absolute divergence, or `$1,000` plus a 10% protected-relative divergence; high-divergence snapshots are verified before Parquet archiving. None of this changes canonical PnL eligibility automatically.

---

## 1. The Polymarket Data API — Hard Truths

### 1.1 `/positions` wraps at its hard pagination ceiling
**Right way:** Treat a repeat below the ceiling as an end marker, but treat a full offset-10,000 page as capped. Recover capped inventories through the accounting snapshot plus market-partitioned `/positions` calls.
**Wrong way:** Loop until an empty page — you'll get an infinite loop / duplicate data.
**What actually happens:** The endpoint returns up to **500 records/page**, documents `offset <= 10000`, and repeats the offset-10,000 page for later offsets. Therefore 10,500 is the maximum directly addressable tail, not an open-position limit and not evidence that the wallet owns exactly 10,500 positions.
**Example:** Likebot stored 10,500 `/positions` rows, while its accounting snapshot contained 26,404 distinct current token balances—26,403 priced at zero. Four other capped wallets showed the same offset-10,500 → offset-10,000 repeat.
**Fix:** Fetch the accounting snapshot's complete `(conditionId, asset)` inventory, partition those condition IDs through `/positions?market=...`, and require exact key reconciliation. Because snapshots may lag live state, accept a missing key only when wallet-scoped `/closed-positions` proves it exited. If any key remains unresolved, return `positions_complete=FALSE` and do not prune or advance the sync timestamp.

### 1.1.1 `/closed-positions` is larger, not unlimited
- The documented maximum offset is 100,000 with a maximum page size of 50, making 100,050 rows addressable per query.
- This endpoint represents exited positions. Resolved-but-unclaimed losing tokens can remain in `/positions`; they are not necessarily present in `/closed-positions` yet.

### 1.2 `/closed-positions` caps at 50/page but DOES end cleanly
- Page size is **50** (not 500 like `/positions`).
- Returns `[]` at the true end — no wrap-around here. Verified with 28,616 real closed positions for likebot.
- 429 handling: backoff 2s, give up after 3 consecutive errors.

### 1.3 `/trades` becomes garbage at high offsets
- `https://data-api.polymarket.com/trades` returns valid dict rows for early offsets but **non-dict garbage at high offsets**. Guard with `isinstance(data[0], dict)` checks — do not crash on it.
- The likebot wallet had 10,500 valid trades before going garbage.

### 1.4 Gamma API condition_id mismatch
**Wrong way:** Trust Gamma `markets?condition_id={cid}` to look up a market for a data-api condition_id.
**What actually happens:** Gamma returns a **DIFFERENT market** for data-api condition_ids. Example: data-api cid `0xdc997d8aea...` → Gamma returns "Xi Jinping out before 2027?" with a completely different cid `0xa467b14d...`.
**Fix:** Do not use Gamma to verify win/loss resolution of data-api positions. Use the position's own `curPrice` / `currentValue` fields as ground truth. `check_market_resolution()` is effectively unreliable for this.

### 1.5 Leaderboard API — the ONLY reliable PnL source
- **Working endpoint:** `https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=ALL&orderBy=PNL&limit=50&offset=N`
- `category=ALL` is **invalid** (400). Must be `OVERALL` (or `SPORTS`, `POLITICS`, `CRYPTO`, `ESPORTS`, `CULTURE`, `TECH`, `FINANCE`, `ECONOMICS`, `WEATHER`, `MENTIONS`).
- Query a single wallet: `.../v1/leaderboard?user={addr}&category=OVERALL&timePeriod=ALL` — returns the wallet's official `pnl`, `vol`, `rank`, `userName`. Verified: likebot rank 1838, pnl +$107,508.26, vol $25.5M.
- **`proxyWallet=` does NOT filter** — it returns rank 1 regardless. `fetch_category_pnl()` in `leaderboard_stats.py` uses it and is silently broken for category filtering; only use the `user=` form.
- **This official `pnl` is the source of truth.** The Polymarket website and our `pm_pnl` column both derive from it.

---

## 2. Win Rate — Correct Determination

### 2.1 The rules (current, correct)
- **Closed positions** (`/closed-positions`): WIN if `realizedPnl > 0` **OR** `avgSellPrice >= 0.95` **OR** `curPrice >= 0.95`.
  - The `realizedPnl > 0` branch is what correctly catches **"buy @0.30, sell @0.70"** — the user makes $0.40 profit, `curPrice` may be only 0.70, but it's still a WIN. `curPrice >= 0.95` is only a secondary catch for positions where PnL rounded to 0 (e.g. tiny $9 buy at 0.52).
- **Redeemable open positions** (`/positions`, `redeemable=True` = market concluded, payout unclaimed): WIN **only if `currentValue > 0`**.
  - `currentValue = 0` → the market concluded AGAINST the wallet → LOSS, **even if partial sells earlier produced positive `realizedPnl`**.
- Win rate = wins / resolved, both 0–100 scale.

### 2.2 The bug we fixed: synthetic entries were re-classified
**What went wrong:** `sync_redeemable_positions` computes the strict `currentValue > 0` win, but then builds a synthetic closed entry carrying `realizedPnl = total_pnl` (which includes partial-sell profit). The closed-positions loop re-ran the loose `realized_pnl > 0 OR sell >= 0.95 OR cur >= 0.95` rule on it, flipping a concluded-against LOSS into a WIN.
**Impact measured:** coinman2 had **78 false wins**, WagerWizard **3 false wins**.
**Fix:** Synthetic entries carry `"is_redeemable": is_win`; the closed loop checks `if cp.get("is_redeemable") is not None: is_win = bool(...)` and skips the loose heuristic. Applied to both the main loop (`positions_winrate_backfill.py`) and the parlay win count.

### 2.3 Don't trust `realizedPnl` magnitude, trust the price fields
- Closed-position `realizedPnl` sums to +$4.78M for likebot, but **Polymarket's official PnL is only +$107.5k**. The closed-positions `realizedPnl` counts full $1 redemption payouts on winners while the offsetting losing side sits in the *redeemable* bucket.
- Netting the 947 both-sides markets gives **-$11.6k (~0)** — the true market-maker signature. The +$4.79M "profit" comes entirely from 26,722 single-side entries whose losing counterpart is in the redeemable pile.
- **Lesson: position-level `realizedPnl` is NOT the wallet's net PnL.** For net PnL, use the official leaderboard API value.

### 2.4 Micro-USDC scaling (`_parse_realized_pnl`)
- `totalBought > 1,000,000` means the API returned micro-USDC → divide `realizedPnl` by 1e6.
- `totalBought == 0` and `|realizedPnl| > 1,000,000` → also scale.
- Otherwise leave a genuinely large win untouched (e.g. +$100k on a $100 parlay stake).

---

## 3. Backfilling — What We Learned

### 3.1 The wrap-around bug
Already covered in 1.1. **Always** verify a wallet's real unique position count against the official Polymarket site before trusting a backfill.

### 3.2 Redeemable positions are synced as closed
- Open positions with `redeemable=True` (market concluded) are written into `wallet_closed_positions_v2` with `is_redeemable=TRUE, resolved_at=endDate` so they persist across backfill cycles.
- Their `closed_at` = market conclusion date (`endDate`), NOT `datetime.now()`.
- When the user claims the payout, the position appears in `/closed-positions` and `upsert_closed_positions_v2` flips `is_redeemable=FALSE` (real settlement).
- `wallet_positions_v2` stores `is_resolved=TRUE` for open positions with `redeemable=True`.
- `wallet_metrics_v2` tracks `redeemable_count`/`redeemable_winning_count` separately from `resolved_count`/`winning_count`.

### 3.3 `endDate` parsing crash
**What went wrong:** `sync_redeemable_positions` had its own `datetime.fromisoformat()` parsing that choked on a naive `datetime(1970, 1, 1, 0, 0)` endDate → `asyncpg DataError` on the timestamptz bind. Crashed the whole coinman2 backfill.
**Fix:** Use the robust `_parse_end()` helper everywhere (handles epoch dates, naive tz, future dates). In `sync_redeemable_positions`, replaced the inline parse with `closed_at = _parse_end(p.get("endDate")) or datetime.now(tz=timezone.utc)`.

### 3.4 Caps (current, intentional)
- Positions / closed: **75,000** (`MAX_POSITIONS` in `leaderboard_stats.py` + `wallet_trade_history.py`, `MAX_CLOSED`/`max_closed` in both). Raised from 30,000 on 2026-08-18 — high-volume wallets (e.g. 10,500 open positions for likebot, 60k+ closed for whales) were truncating at 30k. Closed fetch has a 600s deadline and a `complete` flag.
- **Closed-positions API hard cap:** the `/closed-positions` endpoint stops at **30,000** total (offset 30,000 → 0 rows) — this is the probe-verified ceiling. The plan document references a ~7,500 ceiling in §10.C.5 ("truncates after ~7,500 recent positions") — this was an earlier observation for wallets with multi-year histories and has been resolved: the true API ceiling is 30,000 rows, not 7,500. `MAX_CLOSED=75000` never actually fetches 75k closed. The **open** `/positions` endpoint returns full pages past offset 30k (verified 500/page at offset 35,000), so the 75k cap matters for `fetch_positions` and redeemable sync.
- **Closed-position pagination MUST use `sortBy=TIMESTAMP&sortDirection=DESC`:** concurrent paging without a stable sort produced wildly wrong counts across runs (likebot: 28,616 → 13,850 → 150). `fetch_closed_positions` now pages concurrently (5 pages/batch, `asyncio.gather`), retries each page 3× on timeout/429, sleeps 0.05s between batches, aborts after 3 consecutive failures — verified stable 28,616 ×3 runs.
- **Force re-backfill for truncated wallets:** `force_backfill_over5k.py` (repo root) re-runs `process_wallet_backfill` directly on the 1,003 active wallets with ≥5,000 stored closed positions, bypassing the `computed_at` staleness gate. Run detached (`cmd /c "start /min cmd /c ""cd /d D:\project\poly && python -u force_backfill_over5k.py > backfill_out.log 2> backfill_err.log"""`) — each big wallet takes 1–15 min. `WALLET_TIMEOUT` in `positions_winrate_backfill.py` raised 30 → 300s for the 75k fetch.
- Trades: **600 newest CLOB trades for normal wallets.** `polymarket_trade_backfiller.py` fetches enough recent pages to select the newest 600 and, after a successful normal-wallet write, evicts only older rows beyond that cap. Lineage trade, transfer, and funding history is uncapped. This replaces the former 3,500-row and 15-day retention rules.

### 3.5 Verification pattern (do this after every backfill)
1. Fetch open + closed via the same functions.
2. Check `curPrice` distribution of closed positions: `{0.0: X, 1.0: Y}`. `curPrice=1` = winners, `curPrice=0` = losers.
3. Confirm wins from `curPrice >= 0.95` (e.g. 27,641) vs `realizedPnl > 0` (27,668 for likebot) — expect small drift (~30 positions) from tiny-size rounding.
4. Confirm DB `winning_count` / `resolved_count` match the recomputation.

---

## 4. PnL — Sources and Reconciliation

| Source | Meaning | Trust level |
|---|---|---|
| `pm_pnl` / `pm_volume` / `pm_rank` | Polymarket official leaderboard sync (`poly_leaderboard_sync.py`) | ✅ **Source of truth** |
| Leaderboard API `?user=` | Official per-wallet `pnl`/`vol`/`rank` | ✅ Highest |
| `total_pnl` (computed) | Sum of closed `realizedPnl` + redeemable cash PnL | ❌ Not net PnL |
| Polymarket-tools.com claim | 1.3M gain / 1.1M loss = 200k profit | ❌ Doesn't reconcile with any source |

- `pm_pnl` matches the official API value (likebot: 107,864.90 DB vs 107,508.26 API; small drift from sync timing).
- `pm_rank` can be stale — likebot's DB rank was 316 but the live leaderboard shows 1838. Re-sync periodically.

---

## 5. Methodology Notes

- The likebot wallet is a market maker (holds BOTH Up and Down sides of the same market — 947 markets with both outcomes). These are **legit, NOT duplicates**. Don't dedupe by `(condition_id, outcome)` count per market blindly.
- All 10,500 likebot open positions have `currentValue=0` / `curPrice=0` → all are concluded losses (user hasn't redeemed).
- Trade-level cash flow (buy cost - sell proceeds) is incomplete because the trades API caps data (10,500 trades for likebot vs 28,616 closed positions) — don't use it as a PnL substitute.
- Win rate "too high" suspicion: closed-positions API is biased toward entries the wallet redeemed/sold (winners) while losing counterparts sit in redeemable/open. A 70% position-level win rate for a market maker is plausible per-position even though net PnL is small.

---

## 6. Early-Session Bug Log (start of this session)

These were the first bugs fixed before the win-rate deep-dive. They cluster around ONE root cause — **the 0–100 vs 0–1 percentage scale** — plus a few storage/worker bugs.

### 6.1 Win rate / percentage SCALE bug (the big one)
**What went wrong:** `win_rate` was computed as a **fraction (0–1)** in `leaderboard_stats.py` (`win_rate = winning_count / resolved_count`), while the frontend and DB convention is **0–100**. Worse, the frontend `tool.ts` had extra `* 100` multiplications in several places (`formatPercent` helpers) AND manual `(stats.win_rate * 100).toFixed(1)%` in `wallet/[address]/page.tsx` — so win rates were double/triple-scaled (e.g. 70% → 70 → 7000%).
**Fix:**
- Backend now emits 0–100: `win_rate = winning_count / resolved_count * 100.0` (`leaderboard_stats.py`), and `stats['win_rate'] = stats['win_rate_all'] * 100`.
- New frontend `formatPercent()` in `frontend/src/utils/format.ts` does **NOT** multiply — it just formats the 0–100 value (backend is canonical). All `* 100` calls on win_rate removed from the wallet page.
- API filters updated from fraction to 0–100: `win_rate > 0.70` → `win_rate >= 70` in `src/api/routers/leaderboard.py` and `src/api/routers/wallets.py`.
- `formatPriceCents()` added with a **guard against rounding up to 100¢** (`99.9¢` cap) — prices are fractions (0–1), win rates are 0–100. Keep these two scales straight.

### 6.2 Curation thresholds rewritten to match 0–100 scale
**What went wrong:** `stats_refresher.py` compared `win_rate > 70` (0–100) against a field that was still stored as a fraction in some paths, and the old rule required `total_pnl > 10k AND (roi>30 OR win_rate>70)`.
**Fix (current rules):** `CURATED_MIN_WIN_RATE = 70.0`, `CURATED_MIN_ROI = 30.0`, plus new `CURATED_MIN_BALANCE = 5_000.0`:
- Promote (any of):
  - `win_rate >= 70 AND resolved_count >= 3 AND pnl >= 0`, OR
  - `roi_pct >= 30 AND pnl > 0`, OR
  - `balance >= $5,000 AND pnl >= 0`.
- Demote if all of the above fail; custom wallets (`wallet_sources_v2.source = 'custom'`) are never auto-demoted.

### 6.3 `timeAgo()` mishandled numeric timestamps
**What went wrong:** `timeAgo()` did `new Date(value)` and for a numeric seconds timestamp (e.g. `1750000000`) produced a 1970 date → "Just now" forever / wrong relative time.
**Fix:** Handle numbers: `value < 1e11 ? value * 1000 : value` (seconds→ms), and detect numeric *strings* (`^\d{9,10}$` → seconds, `^\d{12,13}$` → ms). Also added minutes-level granularity (`m ago`).

### 6.4 `closed_at` upsert could NULL out existing data
**What went wrong:** Upsert of redeemable positions used `closed_at=EXCLUDED.closed_at`, overwriting an existing `closed_at` with `NULL`/newer values.
**Fix:** `closed_at=COALESCE(wallet_closed_positions_v2.closed_at, EXCLUDED.closed_at)` — keep the first-known close date.

### 6.5 `_parse_end` naive-datetime comparison
**What went wrong:** `_parse_end` compared `datetime.fromisoformat(cleaned)` (which may be **naive**) against tz-aware `now()`, and it let future dates through (Polymarket `endDate` is a *deadline* like 2027-12-31, not a settlement date).
**Fix:** Force tz-aware: `if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)`; reject `year <= 1970` and any date `> now`. Rejects "phantom" future endDates. (`positions_winrate_backfill.py:65-89`)

### 6.6 Combo parlay activity: `realizedPnl` was just `usdcSize`
**What went wrong:** `fetch_combo_activity` set `realizedPnl = usdcSize` (the redemption payout) for closed combos — treating the whole payout as profit, ignoring entry cost. Open combos used `currentValue = usdcSize`.
**Fix:** Track BUY and REDEEM events per condition_id; for closed combos compute `entry_cost = price * size` (fallback: `usdcSize`), `realized_pnl = payout - entry_cost`. For open combos, `current_value = entry_price * size` when `usdcSize` is 0. Pages the activity feed (`max_pages`) instead of single-page.

### 6.7 Worker orchestration: wrong entrypoint + no health check
**What went wrong:** Orchestrator imported `run_positions_winrate_backfill` which no longer existed (renamed `main_loop`), so Worker 1 crashed on startup; workers silently died with no restart.
**Fix:** Import `main_loop as run_positions_winrate_backfill`; added a **master watchdog** (`watchdog_monitor`) that pings every 30s and cancels+respaws any worker silent > 360s; worker heartbeats tracked in `WORKER_HEARTBEATS`. Now 13 workers supervised.

### 6.8 Leaderboard API cache
**What went wrong:** `cachetools.TTLCache` dependency / an unbounded dict cache caused issues in `leaderboard_v2.py`.
**Fix:** Replaced with a small `SimpleTTLCache` (dict of `(value, ts)`, evicts oldest past `maxsize=300`, TTL 300s).

### 6.9 CORS & error-leaking hardening
- `allow_origins=["*"]` → read from `ALLOWED_ORIGINS` env (default `http://localhost:3000,http://127.0.0.1:3000`).
- Postgres error handler no longer leaks `str(exc)` to clients (`details: None`).

### 6.10 Position fetch caps (see 3.4 for final values)
Originally `MAX_POSITIONS = 5000` / `MAX_CLOSED = 5000`. The `/positions` wrap-around bug (1.1) made 5,000 look like 60k+; after the fix, caps were raised to **30,000**, then to **75,000** on 2026-08-18 when whale wallets (likebot 10.5k open, several wallets 50–85k resolved after redeemable sync) still hit the 30k ceiling. Trade caps stay at 3,500 (user directive).

## 7. ROI for Inherited (Transferred-Position) Wallets — SUPERSEDED BY SECTION 9

> **Note:** The inherited-capital ROI approach described below was superseded by the simpler `roi = pnl / volume * 100` formula (Section 9). The deposit tracking was unreliable (Alchemy ~30% accurate, activity API 500-record limit), so we removed all deposit/withdrawal/inherited capital complexity from the ROI calculation.

### 7.1 The problem
Wallets that receive positions via **P2P on-chain transfer** (P2P transfer tracked in `wallet_position_transfers_v2`, tagged `funding_source='inherited_positions'`/`'internal_funded'` and `funded_by`) often have **zero organic deposits and zero peak capital**. `roi_pct = pnl / cap_base` with `cap_base < $10` fell back to `pnl / total_volume` — which is a **profit margin, not a return on capital**. Example: bwgringo made +$95k on ~$0 invested but showed 6.3% "ROI" (= pnl/volume); Gustav4 made +$59k but showed 0.46%.

### 7.2 The right fix — inherited capital
For inherited wallets, treat the **cost basis of the positions they hold/hold-and-sold** as *additional* deployed capital:
- closed: `SUM(avg_buy_price * total_bought)` over `wallet_closed_positions_v2`
- open: `SUM(avg_price * size)` over `wallet_positions_v2`

This is the *value the wallet actually received*. Because transferred shares are **ERC-1155 outcome tokens — never USDC** — they never appear in `deposits`/`peak_capital` (which only track USDC flows), so their cost basis is genuinely **additive**: `cap_base = max(peak_capital, deposits, inferred_cap) + inherited_capital`.

**Verified results (pure-inherited wallets, organic capital ~$0):**
| Wallet | pnl | old roi (pnl/vol) | inherited cap | new roi |
|---|---|---|---|---|
| bwgringo | +$95,546 | 6.33% | $529,073 | **18.1%** |
| Gustav4 | +$59,736 | 0.46% | $983,627 | **6.1%** |
| Kainvest | +$125,661 | 3.83% | $1,037,993 | **12.1%** |

**Verified results (mixed wallets — deposits AND transfers, before/after):**
| Wallet | deposits | inherited cap | pnl | old roi (max only) | new roi (+inherited) |
|---|---|---|---|---|---|
| wr0ngw4yb3tt0r | $69.1M | $121.6M | −$4.18M | −1.82% | **−2.60%** |
| Djdjdjekekek | $61.9M | $32.6M | −$0.83M | −1.11% | **−0.88%** |

### 7.3 Implementation details
- **Where:** `positions_winrate_backfill.py` (~line 650) and `src/scripts/audit_and_recalc_metrics.py` STEP 3 — both use the same capital-base logic.
- **Trigger condition:** the wallet is flagged inherited (`funding_source IN ('internal_funded','inherited_positions')` OR `transferred_positions_count > 0` OR `funded_by IS NOT NULL`). Inherited capital is then **added** to the organic base (`max(peak, dep, inferred)`) for ALL such wallets — including mixed wallets that also have real deposits. The inherited branch is *additive*, not a fallback.
- **Internal USDC funding is NOT added separately:** Alchemy `deposits` already counts every non-exchange USDC inflow (private wallets + CEXes; only the 4 CTF contracts in `EXCLUDED_EXCHANGE_ADDRESSES` are excluded). Wallet-to-wallet USDC funding is therefore already inside `deposits`/`peak_capital`; adding `wallet_internal_funding_v2` again would double-count. That table is also polluted with settlement-proxy flows (`0x4d97dcd97e`, the CTF_CONTRACT, is in Alchemy's exclude list but NOT in the tracker's `EXCHANGE_CONTRACTS` — 488k funding rows / $43.9M are settlement payouts).
- **Sender side (wallet that transferred positions OUT):** the transfer tracker only tags the *recipient* (`transferred_positions_count+1`, `funded_by`); the sender keeps `cap = max(peak, dep, inferred)` (their real deployed USDC) and is NOT flagged inherited from sending. Transferred positions vanish from the sender's `/positions` API response, and the sender's win/loss credit transfers to the recipient when the market resolves — no double-count on the resolution side.
- **Stale-position pruning (bug fix):** the backfill only upserts open positions, so a sender that re-transferred inherited positions kept stale rows in `wallet_positions_v2` → its `SUM(avg_price*size)` inherited capital was double-counted against the recipient's. Verified on `0xe1111800...` (itself inherited, sent positions on to wr0ngw4yb3tt0r): **327 stale rows / $43,180 cost basis**. Fix: `prune_stale_open_positions_v2` deletes rows the API no longer returns after each backfill (guarded — only when the fetch is complete: non-empty AND below the 75,000-position cap). Pruned 247 rows on verification. Note: asyncpg `conn.execute()` returns a **str** command tag, not a cursor — the original `cur.rowcount` raised `AttributeError`; fixed by parsing the returned tag (`int(tag.split()[-1])`).
- **Fallback chain preserved:** if cap still `< $10` → `total_volume` → `balance` → `roi_pct = NULL`.
- **Clamp preserved:** `roi_pct` clamped to `[-100, 10000]`.

### 7.4 What we tried that didn't work
- Decoding `token_id` from `wallet_position_transfers_v2` back to `(condition_id, outcome)` and joining to positions. The CTF token id does **not** map cleanly (Polymarket transfers tokens that don't match any stored `condition_id` for the receiving wallet) — abandoned in favor of using the receiving wallet's own position cost basis.
- Using `transferred_positions_count` alone — it's a count of transfer *events*, not dollar value; a single 8,000-share transfer counts as "1".

---

## 8. Trade Retention, Lineage Separation & Storage Cleanup (2026-08-20)

### 8.1 The storage problem
**What happened:** `wallet_trades_v2` ballooned to **84 GB / 118M rows**. The Docker VHDX hit **452 GB** (500 GB disk full). PostgreSQL's `DELETE` does NOT immediately reclaim disk — it marks rows as "dead" and PostgreSQL needs a `VACUUM` to physically remove them. The VHDX (virtual disk) also doesn't auto-shrink — needs `diskpart compact` from Windows.

**Root cause:** No retention policy on trades. Every trade from every wallet was kept forever.

### 8.2 What we did — Trade retention rules (superseded state)
- The original incident response used a 500-row plus 15-day rule. The current rule is documented in §20.18: `wallet_trades_v2` retains the newest **600** normal-wallet CLOB trades only; lineage trade/transfer/funding history is uncapped.
- `wallet_activity_v2` remains the short-lived live feed. Long-running Activity provenance uses the separate incremental evidence tables and 500-event hot cache added in §10.

### 8.3 Lineage separation
**What are lineage wallets?** Wallets that received positions via P2P transfer, internal funding, or inheritance (`funding_source IN ('internal_funded', 'inherited_positions')` OR `transferred_positions_count > 0` OR `funded_by IS NOT NULL`).

**New table `wallet_lineage_trades_v2`:** Unified lineage table combining:
- `TRANSFER_IN` / `TRANSFER_OUT` — from `wallet_position_transfers_v2` (ERC-1155 P2P position transfers)
- `DEPOSIT` / `WITHDRAWAL` — from `wallet_internal_funding_v2` (wallet-to-wallet USDC funding)

**Why separate?** Lineage wallets can have massive trade histories from inherited positions. Applying the 500/30d cap would lose important transfer/provenance data.

### 8.4 VACUUM and VHDX compaction
**Lesson learned:** After deleting data, you must:
1. **`VACUUM <table>`** — PostgreSQL physically removes dead tuples (needs autocommit, can't run inside a transaction)
2. **`diskpart compact`** — Windows shrinks the VHDX file (requires Docker Desktop stopped + `wsl --shutdown`)

**Gotcha:** VACUUM requires shared memory. Default Docker `shm_size` (64 MB) is too small. Fixed: added `shm_size: '256mb'` and `shared_buffers=256MB` to `docker-compose.yml`.

### 8.5 One-time cleanup results
| Action | Rows deleted | Space freed |
|--------|-------------|-------------|
| 500-trade cap prune | 72,928,838 | ~40 GB (table: 84→44 GB) |
| 30-day retention prune | 31,927,434 | pending VACUUM |
| 24h feed prune | 288,540 | 414 MB (immediate via VACUUM) |
| VHDX compact (first) | — | 452→200 GB |
| VHDX compact (after prune) | — | 200→242 GB (dead tuples still in VM) |

### 8.6 Key files
| File | What changed |
|------|-------------|
| `polymarket_trade_backfiller.py` | Routes lineage trades to `wallet_lineage_trades_v2`; enforces 500+30d cap per wallet; global 30-day prune + VACUUM after each batch |
| `trade_tracker.py` | Feed prune 3d→1d; added post-prune VACUUM (autocommit connection) |
| `positions_winrate_backfill.py` | `limit_per_host` increased from 30→60 (CONCURRENCY×4); `batch_size` for closed positions increased from 5→8 |
| `docker-compose.yml` | Added `shm_size: '256mb'`, `shared_buffers=256MB` |
| `alembic/versions/j3k4l5m6n7o8` | Creates `wallet_lineage_trades_v2`, populates from transfers + funding |
| `alembic/versions/i2j3k4l5m6n7` | Adds trade index for pruning |

### 8.7 What we tried that didn't work
- **Alembic migration for bulk DELETE:** Running a `ROW_NUMBER() OVER ()` DELETE on 118M rows inside a single Alembic transaction timed out after 1 hour and locked the DB. Fix: ran the DELETE as a separate Python script (`prune_trades.py`) in batches of 500 wallets, which completed in ~31 minutes.
- **`diskpart compact` without detaching VHDX:** Failed with "virtual disk is already attached." Fix: detach first via `diskpart`, then compact.
- **`batch_size=10` for closed-position fetching:** Caused API throttling, speed dropped from 0.6 to 0.2 wallets/s. Fix: reverted to `batch_size=8` (moderate improvement without throttling).
- **VACUUM inside a transaction:** `VACUUM` cannot run inside a transaction block. asyncpg pool connections are transactional. Fix: use `await asyncpg.connect(DB_URL)` for a raw autocommit connection.

---

## 9. The `total_pnl` Overwrite Bug & ROI Formula Fix (2026-08-20) — FIXED

### 9.1 The `total_pnl` variable overwrite bug — FIXED

**What went wrong:** In `positions_winrate_backfill.py`, line 433 inside the `sync_redeemable_positions` loop:

```python
total_pnl = realized_pnl + cash_pnl  # BUG: overwrites wallet-level total_pnl!
```

The variable `total_pnl` was set at line 373 from the leaderboard API (`total_pnl = website["pnl"] if website else None`). But the redeemable-position loop reused the **same variable name** for each position's individual PnL. After the loop, `total_pnl` = the **last redeemable position's PnL**, not the wallet's actual all-time PnL.

**Impact measured:**

| Wallet | API PnL | DB total_pnl (before fix) | Reason |
|--------|---------|---------------------------|--------|
| ferrariChampions2026 | $2,765,614 | **-$486** | Last of 10,470 redeemable positions |
| jtwyslljy | $2,363,358 | **$5,020** | Single redeemable position |

This cascaded into wrong `roi_pct` (ROI = `total_pnl / cap_base * 100`), wrong leaderboard display, wrong curation tier.

**Fix:** Renamed to `redeemable_pnl` so it doesn't clobber the wallet-level `total_pnl`:

```python
redeemable_pnl = realized_pnl + cash_pnl  # fixed
```

And updated the synthetic entry: `"realizedPnl": str(redeemable_pnl)`.

**Lesson:** Never reuse a wallet-level accumulator variable inside a per-position loop. Use distinct names (`redeemable_pnl`, `pos_pnl`, etc.).

### 9.2 Deposits/withdrawals tracking was fundamentally broken — FIXED

**What happened:** `capital_metrics_backfill.py` uses Alchemy's `alchemy_getAssetTransfers` to track USDC deposits/withdrawals. This only captures **on-chain USDC transfers from/to the zero address** (CEX withdrawals, bridge deposits). It **misses**:

- Deposits from intermediate wallets (CEX → intermediate wallet → Polymarket)
- Position transfers that carry value but no USDC
- Platform-level deposits that don't match on-chain USDC flows

**Verified against Polymarket's own activity tool** (`activity.polymarket-tools.com/api/activity`):

| Wallet | Deposits (Alchemy/DB) | Deposits (Polymarket API) | Gap |
|--------|----------------------|--------------------------|-----|
| jtwyslljy | $3,188,038 | **$8,331,400** | -$5.14M (38% captured) |
| ferrariChampions | $619,803 | **$2,580,547** | -$1.96M (24% captured) |

Withdrawals are similarly off:
| Wallet | Withdrawals (DB) | Withdrawals (API) | Gap |
|--------|------------------|-------------------|-----|
| jtwyslljy | $659,711 | **$9,999,000** | -$9.34M (7% captured) |
| ferrariChampions | $852,984 | **$2,590,203** | -$1.74M (33% captured) |

**Example — jtwyslljy wallet:**
- Alchemy shows **zero** on-chain USDC deposits (never received USDC from zero address)
- The wallet was funded entirely through **11 position transfers** from parent `0xe111180000d...`
- But Polymarket's platform tracks **216 deposits** ($8.33M) and **284 withdrawals** ($10.0M)
- Net capital: **-$1.67M** (user withdrew more than deposited)

**Why it matters:** ROI calculations using `deposits` or `peak_capital` are unreliable. The inherited-capital fix (Section 7) partially addresses this for position-transfer wallets, but the underlying deposit tracking is only ~30% accurate.

### 9.3 The Polymarket activity tool API (now integrated)

**Endpoint:** `POST https://activity.polymarket-tools.com/api/activity`

**Request body:**
```json
{
  "wallets": ["0x..."],
  "filters": {
    "types": ["DEPOSIT", "WITHDRAWAL", "TRADE", "REDEEM"],
    "side": "ALL",
    "timeRange": "ALL_TIME",
    "sortDirection": "DESC"
  }
}
```

**Response:**
```json
{
  "activity": [...],   // up to 500 records (hard limit)
  "totalPnl": 2362553.8
}
```

**Activity types:** `TRADE`, `DEPOSIT`, `WITHDRAWAL`, `REDEEM`, `SPLIT`, `MERGE`, `REWARD`, `CONVERSION`, `YIELD`, `MAKER_REBATE`

**Limitations:**
- 500-record hard limit per request
- When filtering multiple types (e.g., TRADE + DEPOSIT), the 500-record window includes trades, pushing older deposits out
- For accurate deposit/withdrawal totals, filter to only `DEPOSIT` + `WITHDRAWAL` types

### 9.4 The fix — ROI = pnl / volume * 100

After discovering that both Alchemy deposits (~30% accurate) and the Polymarket activity API (500-record limit) provide unreliable deposit data, we simplified the ROI formula:

**New formula (all workers):**
```
roi_pct = (pnl / volume) * 100
```

Where:
- `pnl` = `pm_pnl` from leaderboard API (source of truth)
- `volume` = `total_volume` from leaderboard API (source of truth)

This removes all deposit/withdrawal/inherited capital complexity. No dependency on Alchemy or the activity API for ROI calculation.

### 9.5 Key files
| File | What changed |
|------|-------------|
| `positions_winrate_backfill.py:433` | **FIXED** — `total_pnl` → `redeemable_pnl` in redeemable loop |
| `positions_winrate_backfill.py:670+` | ROI = `pnl / volume * 100` (removed deposit/inherited capital logic) |
| `capital_metrics_backfill.py` | ROI = `pnl / volume * 100`; still updates deposits/withdrawals from activity API |
| `leaderboard_stats.py:675` | ROI = `pnl / volume * 100` (was `pnl / peak_capital`) |
| `wallet_trade_history.py:334` | `fetch_website_pnl()` — leaderboard API, the correct PnL source |

---

## 10. Position History Beyond-5k Optimization & Canonical Timestamps (2026-08-22)

### 10.1 The Storage & Sync Challenge
- `wallet_closed_positions_v2` grew to **68 GB / 131.2M rows**, with 32% of data belonging to just 4,735 high-volume wallets.
- Re-fetching complete 20k+ histories at 50 records/page took 400+ HTTP requests per wallet on every cycle, causing worker rate limits and lag.

### 10.2 The Solution: 5,000 Active Buffer + Cumulative `*_beyond_5k` Aggregates
- **Initial Backfill:** Full 100% history is fetched to establish complete all-time stats. Positions ranked $> 5000$ by `endDate` are aggregated into dedicated `*_beyond_5k` columns in `wallet_metrics_v2` and deleted from raw storage.
- **Incremental Syncs:** Workers only fetch new positions since the last sync. When stored rows exceed 5,000, newly overflowed rows are additively accumulated into `*_beyond_5k` and deleted from PostgreSQL.
- **Headline Math:**
  $$\text{All-Time Wins} = \text{recent\_5k\_wins} + \text{winning\_count\_beyond\_5k}$$
  $$\text{All-Time Resolved} = \text{recent\_5k\_resolved} + \text{resolved\_count\_beyond\_5k}$$
  $$\text{All-Time Win Rate} = \frac{\text{All-Time Wins}}{\text{All-Time Resolved}} \times 100$$

### 10.3 Canonical Resolution Date (`endDate`) vs. Redemption Date
- **What went wrong:** When a user redeemed a winning trade on Aug 21 for a market that resolved on Aug 5, sorting by Polymarket's `closedAt` / `lastUpdatedAt` treated it as an Aug 21 trade, pushing it to the top of recent trades and corrupting `pnl_100` / `pnl_500`.
- **Fix:** We enforce **Market Concluded Date (`endDate`)** as the primary resolution timestamp for all held-to-resolution trades. For early exits (sold before market conclusion), the actual trade close date is used.

---

## 11. Comprehensive System Audit & Bug Fixes (2026-08-26)

### 11.1 Watchdog False Supervise Task Termination
- **What went wrong:** `src/orchestrator.py` updated heartbeats before and after `await task_func()`. Continuous workers like `main_loop` run infinite `while True` loops that never exit `await task_func()`, causing the master watchdog to see silence after 360 seconds and cancel/respawn healthy workers every 6 minutes mid-cycle.
- **Fix:** Added a background heartbeat ticker per running task in `supervise_task` and exported `touch_heartbeat(name)` so workers actively signal progress to the watchdog.

### 11.2 Dust Position Win-Rate Inflation
- **What went wrong:** In `src/workers/leaderboard_stats.py`, dust-price positions (`cur_price < 0.03`) evaluated `if cur_val > 0: winning_count += 1`. Active markets trading near zero ($0.01) with non-zero dust value were classified as wins instead of losses.
- **Fix:** Gated `winning_count += 1` strictly on `redeemable=True`. Any active position trading below $0.03 without `redeemable=True` is recorded exclusively as a loss.

### 11.3 `is_redeemable` Synthetic Flag Overwrite
- **What went wrong:** In `src/workers/positions_winrate_backfill.py`, synthetic redeemable entries inserted with `is_redeemable=TRUE` into `wallet_closed_positions_v2` were passed to `upsert_closed_positions_v2` in the same pass, where `ON CONFLICT` forced `is_redeemable=FALSE`, breaking claimed vs. unclaimed tracking.
- **Fix:** Filtered `real_closed = [cp for cp in closed_positions if not cp.get("is_redeemable")]` before calling `upsert_closed_positions_v2`.

### 11.4 `last_trade_at` Dormancy Regression from 15-Day Trade Pruning
- **What went wrong:** `wallet_trades_v2` retains trades for only **15 days** (code: `polymarket_trade_backfiller.py:219,367`, `INTERVAL '15 days'`). Querying `max(traded_at)` returns `NULL` for wallets whose last trade occurred >15 days ago. Writing `NULL` overwrote valid historical `last_trade_at` dates and incorrectly flagged wallets.
- **Fix:** Used `GREATEST(COALESCE(last_trade_at, $2), $2)` so `last_trade_at` never regresses or gets wiped by trade table retention pruning.

### 11.5 Stale Position Pruning on Partial / Errored API Fetches
- **What went wrong:** If `fetch_positions` encountered an HTTP timeout or 429 error mid-pagination, `prune_stale_open_positions_v2` deleted valid open positions because the partial list lacked the remaining rows.
- **Fix:** `fetch_positions` now returns `(positions, is_complete)`. Stale position pruning only executes when `is_complete == True` and the list is within expected caps.

### 11.6 WebSocket Broadcast JSON Serialization Crash
- **What went wrong:** In `src/api/routers/ws.py`, `start_db_poll_broadcaster` queried `wallet_activity_v2` returning raw Python `datetime` objects. Passing them directly to `send_json` triggered unhandled `TypeError: Object of type datetime is not JSON serializable` crashes.
- **Fix:** Converted timestamps to `.isoformat()` strings and serialized messages safely using `json.dumps(message, default=str)`.

### 11.7 Historical 10-Window Progression Property Name Mismatch & Missing Numbers
- **What went wrong:** In `frontend/src/app/wallet/[address]/page.tsx`, `pnlWindows` was mapped to non-existent property names (`stats?.pnl_window_10`, `stats?.pnl_window_25`, `stats?.pnl_window_50`, etc.) instead of the database column names stored in `wallet_metrics_v2` (`pnl_100`, `pnl_200`, `pnl_300`, `pnl_500`, `pnl_750`, `pnl_1000`, `pnl_1500`, `pnl_2000`, `pnl_3500`, `pnl_5000`). Because every window value was undefined/null, `HistoricalProgressionChart.tsx` fell back to a hardcoded multiplier against `$274.6k` for the SVG curve while rendering `—` (dash) for the actual labels below.
- **Fix:** Corrected the property mapping in `page.tsx` to `stats?.pnl_100` through `stats?.pnl_5000`, fixed `standardLabels` in `HistoricalProgressionChart.tsx`, and ensured numbers and deltas render accurately for all windows.

### 11.8 Multi-Tier Category Hierarchy & Aggregation Structure
- **What went wrong:** When displaying `category_stats_v2` in the wallet profile table with separate `Category`, `Subcategory`, and `League` columns, root category rows appeared to have "missing data" (`—`) in the Subcategory and League cells.
- **Fix:** Clarified and documented the hierarchical roll-up structure: Root Category rows (e.g. `SPORTS` total: 200 resolved) represent the cumulative aggregate of all trades across that category, while Subcategory rows (e.g. `SPORTS` -> `MMA`: 62 resolved) represent specific subsets. Uncategorized or non-league markets contribute to their parent roll-up without creating standalone sub-rows.

### 11.9 Sports Team, Prop & League Classification Gap
- **What went wrong:** `classify_tags` in `src/utils/category_classifier.py` only matched generic keywords (e.g. `sports`, `baseball`), failing to recognize specific team names (Cardinals, Cubs, Red Sox, Dodgers, Vikings, Browns, Bears, Fever, Sky, Aces), player props (Home Runs, Strikeouts, Passing Yards, Touchdowns), or combat terms (`UFC 330`, `Fight Night`, `O/U Rounds`). This caused sports bets to fall back to `subcategory="Sports"` or `subcategory=""` and `league=""` (or into `OTHER`), leaving the Subcategory and League columns empty.
- **Fix:** Built `classify_market_title` with comprehensive dictionaries covering all MLB, NFL, NBA, WNBA, NHL, MMA/UFC, Soccer, and Esports leagues/teams/props. Upgraded `gamma_market_cache.py` to auto-refine markets from titles, and added `DELETE FROM category_stats_v2 WHERE address = $1` before writing fresh category roll-ups.

### 11.10 Closed Parlay Entry Cost & Closing Date Integration
- **What went wrong:** For redeemed winning multi-leg parlay payouts, Polymarket's position API reports `avgPrice = 0` (or `None`) because the shares were converted to $1.00 payout tokens upon market resolution. Because `avgPrice <= 0`, `entryCost` computed as `0` and rendered as `—` (dash) for Avg Entry and Invested in the Closed Parlays table. Additionally, the Closed Parlays table was missing a resolution Date column.
- **Fix:** Added fallback inference: when `avgPrice` is omitted/0 on a won parlay, `entryCost` is computed as `tokens - realizedPnl` and `avgPrice` is derived from `entryCost / tokens` (or `$0 / 1.0` for 100% free/reward payouts). Included the `Date` (closing/settlement timestamp) column in `/parlays` API and added interactive date sorting in the Closed Parlays table.

### 11.11 Category Win Rates Multi-Scope Selector (All / Positions / Parlays)
- **What went wrong:** The Category Win Rates table previously displayed only a single combined list of all trades without allowing the trader to isolate performance between single-market positions and multi-leg parlays.
- **Fix:** Added a segmented sub-filter toggle (`All`, `Positions`, `Parlays`) to dynamically aggregate category statistics across single positions only, multi-leg parlays only, or the combined totals.

---

## 12. High-Performance Backfill & Metrics Compute Optimizations (2026-08-27)

### 12.1 Removal of Hidden Network Fallbacks in Offline Compute Worker (Worker 3)
- **What went wrong:** `src/workers/positions_metrics_compute.py` was designed as an offline local database worker, but had two hidden HTTP network calls:
  1. `fetch_website_pnl` was called for every wallet to get Polymarket leaderboard PnL.
  2. When `total_volume` was 0 (or empty), `fetch_all_trades` was invoked, firing paginated HTTP requests to Polymarket's trade API with rate limits and timeouts.
  3. Dynamic `from src.utils.category_classifier import classify_market_title` was executed inside the inner loop for every position row.
- **Impact:** Compute speed collapsed from 75 wallets/sec down to 0.7–9 wallets/sec as it processed standard/low-balance wallets.
- **Fix:** 
  - Completely removed `fetch_all_trades` and `fetch_website_pnl` from Worker 3. Total PnL and volume are read directly from `wallet_metrics_v2` (populated by Worker 4 / leaderboard sync) or computed from local database sums.
  - Moved title classification imports to the top level.
  - Converted category statistics inserts to bulk `executemany` statements.
  - Raised `CONCURRENCY = 80` with a dedicated `max_size = 110` connection pool.

### 12.2 Polymarket `/value` Fast-Path & Alchemy RPC Semaphore Unblocking (Worker 4 & Stats Refresher)
- **What went wrong:** For wallets with $0 balance (which represent ~80% of Polymarket wallets without active open bets), balance fetching fell back to `alchemy_get_token_balances`. Because Alchemy requests were gated on a single-key semaphore (`_alchemy_sem`), all concurrent worker threads blocked in a serialized queue, capping throughput at ~4.5 wallets/sec.
- **Fix:** Implemented the **Polymarket `/value` fast-path** in `stats_refresher.py` and `pnl_balance_refetch.py`. Only fallback to on-chain Alchemy RPC when network connection errors occur on the `/value` endpoint. Throughput jumped from 4.5 wallets/s to **~63+ wallets/s** (500 wallets per 7.9s).

### 12.3 Rolling Window PnL Recency Fix (`pnl_100` ... `pnl_3500`)
- **What went wrong:** Concluded redeemable positions (`is_redeemable = TRUE`) have their `closed_at` timestamp set to the market's resolution `endDate` (often recent). When rolling windows sorted all closed positions by `closed_at DESC`, these resolution events floated to the top of recent windows regardless of when the bet was placed, flooding `pnl_100` through `pnl_3500` with historical market resolution losses.
- **Fix:** Filtered `non_redeemable_closed = [cp for cp in closed_rows if not cp.get("is_redeemable")]` before sorting and slicing `pnl_100` through `pnl_3500`. Redeemable positions continue to be counted toward all-time global win rate and lifetime `pnl_5000`.

### 12.4 Closed Positions Backfill Page 0 Fast-Path (Worker 2)
- **What went wrong:** Speculative multi-page batching was firing 120+ open HTTP connections simultaneously per batch on Polymarket's `/closed-positions` API, triggering throttling and slowing Worker 2 down to 2.6 wallets/s.
- **Fix:** Implemented Page 0 fast-path in `fetch_closed_positions` (`src/workers/wallet_trade_history.py`). For 95%+ of active wallets during incremental sync, encountering known keys stops fetching in 1 single HTTP request. Concurrency increased to 35, boosting throughput to **32–38 wallets/s**.

---

## 13. Polymarket Data Lifecycle, Field Mapping & Pure Database PnL (2026-08-27)

### 13.1 Polymarket Position Lifecycle Architecture & PnL Reconciliation
- **What went wrong:** When comparing wallet PnL between our database and Polymarket's website (e.g. BreakTheBank wallet `0xf0318c32136c2db7fec88b84869aee6a1106c80c`), Polymarket displayed **$45.3M profit / $42.2M loss** and a leaderboard PnL of **+$3.09M**, while our database position summation resulted in **-$9.36M**.
- **Root Cause & Architectural Discovery:**
  1. **`/closed-positions` Endpoint (Only Redeemed Winners & Manual Exits):** Polymarket only moves positions into `/closed-positions` when an on-chain transaction closes them (i.e. winning positions redeemed for $1.00 or positions manually sold early). For BreakTheBank, this contained **315 rows** (268 winners with **+$39.38M profit** and 44 manual sales with **-$4.14M loss**).
  2. **`/positions` Endpoint (Expired Zero-Value Losers):** When a bet loses (market resolves to $0.00), there is $0.00 to redeem, so traders never submit on-chain redemptions. Polymarket leaves these expired positions in `/positions` indefinitely with `curPrice = 0.0` and `redeemable = true`. For BreakTheBank, there were **362 expired losing positions** totaling **-$41.93M loss**.
  3. **Why Our System Combines Them:** If our database only synced `/closed-positions`, every wallet would show an artificially inflated 90%+ win rate. Our workers (`positions_winrate_backfill.py` & `positions_open_backfill.py`) combine both sets into `wallet_closed_positions_v2`.
  4. **Why Account Leaderboard PnL is +$3.09M while Settled Position Sum is -$9.36M:** The Leaderboard measures **account-level collateral equity** ($\text{Deposits} - \text{Withdrawals} + \text{Cash} + \text{Portfolio Value}$), which captures cash gained from orderbook trading before settlement, whereas static position sums only tally initial purchase cost vs settlement outcome.

### 13.2 Polymarket Data API `totalBought: 0` Field Mapping Bug
- **What went wrong:** For positions acquired through complete set splits or CLOB limit orders, Polymarket's API returns `totalBought: 0` (or partial values), while `size` (shares) and `initialValue` (dollars spent) are populated.
- **Impact:** Backfill workers mapped `total_bought = p.get("totalBought")`, causing `total_bought = 0` to be stored on **137 rows** for BreakTheBank (and ~2M rows across the DB). Calculating `total_bought * avg_buy_price` yielded `$0.00`, undercounting capital spent on losses from **$46.76M down to $34.35M**.
- **Fix:**
  1. Updated `positions_winrate_backfill.py` and `positions_open_backfill.py` to use:
     ```python
     total_bought = bought_val if bought_val > 0 else size_val
     if total_bought == 0 and initial_val > 0 and avg_price > 0:
         total_bought = initial_val / avg_price
     ```
  2. Created `src/scripts/repair_position_fields.py` to update all legacy rows in `wallet_closed_positions_v2` with accurate share counts derived from `ABS(realized_pnl) / avg_buy_price`.

### 13.3 Polymarket Redirect Links 404 Fallback Elimination
- **What went wrong:** In `frontend/src/app/wallet/[address]/page.tsx`, `MarketTitleCell` fell back to `https://polymarket.com/market/{conditionId}` whenever event slugs were missing. Polymarket has no `/market/` route, causing external links to return **404 Not Found**.
- **Fix:**
  - Standardized valid event slugs to `https://polymarket.com/event/{slug}`.
  - Eliminated the broken `/market/{conditionId}` fallback.
  - Added clean fallback to Polymarket search: `https://polymarket.com?_q={encodeURIComponent(title)}`.
  - Linked generic titles (e.g. multi-leg parlays) directly to `https://polymarket.com`.

### 13.4 Closed Positions Sub-Filtering (`All`, `Only Closed`, `Open but Concluded`)
- **What went wrong:** Traders could not differentiate between bets that were actively sold/redeemed vs bets that expired at zero value and remained unredeemed.
- **Fix:**
  - Added `is_redeemable` flag to the `/api/v2/wallets/{address}/closed-positions` endpoint.
  - Added a status dropdown in the Closed Positions tab (`All (Closed + Concluded)`, `Only Closed (Redeemed/Sold)`, and `Open but Concluded (Zero-Value/Unredeemed)`).
  - Updated `sortedClosedPositions` to filter reactively across both Category and Sub-Filter.

### 13.5 Database-Pure PnL Computation
- **What went wrong:** `positions_metrics_compute.py` previously read `pm_pnl` from `wallet_metrics_v2` and used it as a fallback for `total_pnl` and `pnl_5000`, creating a mismatch where the 5000+ window showed +$3.09M while earlier windows showed -$10.57M.
- **Fix:**
  - Configured `total_pnl` and all rolling windows (`pnl_100` ... `pnl_5000`) in `positions_metrics_compute.py` and `win_rate_compute.py` to compute **100% strictly from database closed position rows**.
  - Retained `pm_pnl` exclusively as the Polymarket Leaderboard metric in `wallet_metrics_v2` to be displayed in the **Leaderboard Snapshot** KPI card.

### 13.6 Gamma API Singular Parameter (`condition_id`) & Missing Endpoint Constant Fix
- **What went wrong:** In `src/api/routers/wallets_v2.py`, `_fill_missing_titles_outcomes` attempted to resolve missing market titles by querying `f"{GAMMA_API}/markets?condition_ids={c}"`. Gamma API returns **0 results** when querying `condition_ids` (plural), requiring `condition_id` (singular). Furthermore, `GAMMA_API` was not defined as a constant in `wallets_v2.py`, causing unresolved condition IDs to render as `—` (dash) in position tables.
- **Fix:** Defined `GAMMA_API = "https://gamma-api.polymarket.com"` and updated resolution queries to `f"{GAMMA_API}/markets?condition_id={cid}"` with parallel concurrency (`asyncio.Semaphore(15)`), auto-upserting resolved titles and `event_slug` into `markets_v2`.

### 13.7 Table Layout Distortion on Pagination Fix
- **What went wrong:** Position tables rendered using dynamic browser column sizing (`table-auto`). When navigating to pages where titles were short or missing (`—`), the browser dynamically shrank the `Market` column and stretched other columns across the viewport, causing visible visual jumping and layout distortion on page changes.
- **Fix:** Converted all position tables (Open Positions, Closed Positions, Open Parlays, Closed Parlays) to `table-fixed` with explicit percentage column widths (`w-[36%]`, `w-[42%]`, `w-[10%]`, etc.) and updated `MarketTitleCell` with `w-full min-w-0 flex-1` for stable, consistent column rendering across all pages.

### 13.8 Closed Positions Sorting & PnL Field Harmonization

## 14. `problem.md` Audit — Confirmed Still-Live Bugs & the "Never Assume" Rule (2026-08-28)

### 14.1 What was verified against live code (not just the report)
`problem.md` documents a **-$11.97M discrepancy** for wallet `0xf0318c32...` (BreakTheBank): our DB showed `-$8.90M` lifetime PnL while Polymarket leaderboard, Supabase, the Polymarket-tools activity API, and the **on-chain USDC cash ledger** (deposits − withdrawals + balance + open value = **+$3.09M**) all agree on a positive result. Before writing a fix plan we re-checked every claim in `problem.md` against the actual code (not the report's line numbers, which had drifted) to avoid fixing something already fixed or missing something newly introduced:

| `problem.md` claim | Verified? | Current location |
|---|---|---|
| §1.1 `avg_buy_price` defaults to `0.50` on missing price | ✅ Root cause identified | The `avg_buy_price ≈ 0.50` rows are Polymarket's own mint-cost estimate: when tokens are acquired via complete-set split (not CLOB purchase), the API returns `avgPrice: 0.50` as the theoretical $0.50-per-side cost. This is now recognized by `is_synthetic_mint` in `src/pnl/rules.py:31-36`, which detects `0.4995 ≤ avgPrice ≤ 0.5005` with `totalSold == 0`. The function is used by `synthetic_legs_to_drop` to pair complementary outcomes and drop orphan synthetic legs. The open question is resolved: the 0.50 is not a default fallback in ingestion code — it is Polymarket's upstream estimate for minted positions. |
| §1.2 `cash_pnl` wipes prior `realizedPnl` on $0 expiry | ✅ Still live | `positions_open_backfill.py:117-121` / `positions_winrate_backfill.py:` equivalent — `is_win = cur_val > 0; ... total_pnl = cash_pnl if cash_pnl != 0 else (-initial_val ...)`. For the 3 audited wallets (2026-08-28 session) we found **zero** redeemable rows with `total_sold > 0`, meaning this specific bug did not fire for them — but the logic is still wrong in general and must be fixed for any wallet where it does apply. |
| §1.3 redeemable win requires `sell_p >= 0.95` | ✅ Still live, confirmed structurally broken | `positions_metrics_compute.py:135-136` — `if cp.get("is_redeemable"): is_win = sell_p >= 0.95`. Unredeemed positions have `avg_sell_price = 0` by definition (nothing was sold) — this condition can only be satisfied by accident (e.g. a partial sell before the residual expired), meaning **the vast majority of true redeemable wins are being counted as losses.** |
| §2.1 volume sums `total_bought` (tokens) not `total_bought*avg_buy_price` (USD) | ✅ Still live | `positions_metrics_compute.py:117,158,233` |
| §3.1 `withdrawals` defaults to `$0.0` on API failure | ⚠️ Not re-verified this session | `capital_metrics_backfill.py` — worker still exists but is **decommissioned from `orchestrator.py`** (see CORE_LOGIC.md §6, retired 2026-08-22) since ROI no longer depends on deposits/withdrawals. Low priority unless deposit/withdrawal display is reinstated. |
| §3.2 `funding_source='inherited_positions'` overrides real CEX deposits | ⚠️ Not re-verified this session | `position_and_funding_tracker.py` — needs a dedicated pass; do not assume still broken without checking current logic. |
| §4.1 redeemable `closed_at` bunches multi-month bets into the resolution month | ✅ Partially fixed already | `positions_metrics_compute.py` §12.3 excludes `is_redeemable=TRUE` rows from rolling windows `pnl_100`..`pnl_3500` (fixed 2026-08-27) but **`pnl_5000`/`total_pnl`/lifetime win-rate still include them at `resolved_at=endDate`**, so month-by-month breakdowns (like the one in `problem.md` §1) will still show this bunching. This is a display/reporting nuance, not a lifetime-PnL bug. |

### 14.2 The "Never Assume" principle — how it applies to every fix below
Per explicit user direction: **calculations must never substitute a guessed/default value for missing upstream data.** When Polymarket's API omits a required field (`avgPrice`, `totalBought`, `realizedPnl`, `avgSellPrice`, etc.):
- **Do not** hardcode a fallback constant (`0.50`, `1.0`, etc.) that has no basis in the actual trade.
- **Do** try to derive the true value from other fields already present on the same record when the derivation is mathematically exact (e.g. `avg_buy_price = initialValue / size` when both are present and `size > 0` — this is arithmetic, not a guess).
- **Do** exclude the row from PnL/volume/win-rate aggregates and mark it (e.g. `data_quality_flag = 'missing_avg_price'`) if no exact derivation is possible, rather than silently injecting a wrong number.
- **Do** log/count how many rows per wallet fall into the "flagged" bucket so operators can see data completeness at a glance, instead of a confident-looking-but-wrong number.

### 14.3 Why `total_pnl` and `pm_pnl` can never be reconciled to the cent
Section 13.1 already documented the two-endpoint architecture (`/closed-positions` = redeemed/sold; `/positions` with `redeemable=true` = expired zero-value unclaimed). Section 14 adds: even after every bug above is fixed, **position-level summation will still not equal the leaderboard's cash-flow PnL**, because:
- The leaderboard/on-chain formula captures money that moved through the wallet's **collateral balance** (CLOB maker/taker spread capture, rebates, mid-trade cash sitting uninvested) that never shows up as a discrete "position."
- Position-level PnL only exists for rows Polymarket chose to expose via `/closed-positions` or `/positions`; any positions fully netted out before ever appearing in either endpoint (e.g. instantaneous split/merge arbitrage) leave no row to sum.
- **Empirical bound (measured 2026-08-31):** Across 12 directional wallets in the baseline cohort, the median relative error between reconciled `total_pnl` and `pm_pnl` is **106.9%**, with 5 of 12 wallets within 20%. The largest residual is swisstony at -$23.69M (truncated history). This confirms that position-level summation cannot converge to leaderboard PnL for wallets with complete-set minting or historical truncation.
- **Decision:** `pm_pnl` remains the sole source of truth for any user-facing lifetime PnL number (already the display fix applied 2026-08-28, see CHANGELOG). `total_pnl` is retained only as an internal/diagnostic figure and should be labeled as such anywhere it's shown, never as "PnL" without qualification.

## 15. PnL Data Integrity, CTF Minting Mechanics, Latency & UI Crash Resolution (2026-08-28)

### 15.1 Complete-Set Minting & The Redeemable Phantom Loss Bug ($12.93M Excess)

#### The Two-System Architecture on Polymarket
To understand why `totalBought = 0` occurs on high-volume wallets like `0xf0318c32136c2db7fec88b84869aee6a1106c80c` (BreakTheBank):
```
┌──────────────────────────────────────────────────────────┐
│ SYSTEM 1: Polygon Smart Contract (The Blockchain)        │
│ • Handles raw tokens (ERC-1155) & collateral (USDC)      │
│ • When you deposit $1, it mints 1 YES + 1 NO tokens      │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼ Tokens exist in wallet
┌──────────────────────────────────────────────────────────┐
│ SYSTEM 2: The CLOB (Central Limit Order Book)            │
│ • Polymarket's exchange software (orders, bids, asks)    │
│ • Only records when you click "BUY" or "SELL" on the UI  │
│ • Tracks: `totalBought`, `totalSold`, `avgBuyPrice`      │
└──────────────────────────────────────────────────────────┘
```

#### Step-by-Step Blockchain Lifecycle:
1. **Step 1: Direct Contract Mint (Bypasses the CLOB):**
   - An arbitrageur/whale deposits `$1,000,000 USDC` directly to the **Conditional Token Contract (CTF)** on Polygon (`splitPosition`).
   - Contract mints **1,000,000 YES** and **1,000,000 NO** tokens to the wallet.
   - **CLOB Record:** The CLOB orderbook logs **0 trades** (no match occurred on exchange).
2. **Step 2: Selling YES on CLOB:**
   - Trader sells 1,000,000 YES at `$0.52` on CLOB, receiving **`$520,000 USDC`** cash proceeds.
   - Recorded in `/closed-positions` as an exit.
3. **Step 3: Residual NO Tokens Expire at $0.00:**
   - 1,000,000 NO tokens remain in the wallet. The trader never bought them on the CLOB:
     $$\mathbf{totalBought = 0}, \quad \mathbf{n\_trades = 0}$$
   - When YES wins, NO expires worthless ($0.00). The trader never submits an on-chain redemption ($0 payout), leaving it in `/positions` with `redeemable=true` and `curPrice=0.0`.

#### How Polymarket's `/positions` API Constructs JSON:
```json
{
  "conditionId": "0x8eb933...",
  "outcome": "Yes",
  "size": 2020266.83,         // On-chain token balance
  "totalBought": 0,           // CLOB trade history
  "avgPrice": 0.50,           // Estimated mint cost
  "initialValue": 1010133.42,
  "cashPnl": -1010133.42      // Theoretical portfolio drawdown: -(size * avgPrice)
}
```

#### The Double-Counted Ingestion Bug:
The trader spent **$1.00** on the pair, sold YES for **$0.52**, and NO expired at **$0.00**.
* **True Economic Result:** Net cash loss of **`-$0.48` per pair** ($480k total cash loss).
* **Old Database Flaw:** Our backfill counted the YES trade sale, then took NO's `cashPnl: -$1,010,133.42` and added another -$1.01M loss into `wallet_closed_positions_v2`! Across 364 positions on `0xf031...`, this injected **$12.93 Million** in phantom losses ($8.49M on 21 zero-bought positions + $4.44M on 12 mixed positions).

#### The Fix & Mathematical Proof:
In `src/workers/positions_open_backfill.py` and `src/workers/positions_winrate_backfill.py`:
- Actual orderbook outlay: `actual_bought = total_bought if total_bought > 0 else 0.0`
- Capped losses at actual cash outlay: `actual_cost = actual_bought * avg_price`
- Set `total_pnl = realized_pnl - actual_cost` (where `actual_cost = $0.00` for unbought tokens).
- Tagged rows in `data_quality_flag` (`minted_shares`, `mixed_minted_shares`).

$$\begin{aligned}
\text{Net Position PnL} &= \text{PM Closed Realized PnL (\$35.25M)} - \text{Actual CLOB Losses (\$31.80M)} - \text{Zero-Bought Realized (\$0.30M)} \\
&= \mathbf{+\$3,145,543.77} \quad (\text{matches On-Chain Cash Ledger } \mathbf{+\$3.09M} \text{ within 1.6\%})
\end{aligned}$$

### 15.2 Ground-Truth Win Detection Unification
- **What went wrong:** `positions_metrics_compute.py` checked `avg_sell_price >= 0.95` for redeemables (impossible for unredeemed expired tokens where `avg_sell_price = 0`), and `win_rate_compute.py` had a bug where `is_win = bool(is_redeemable)` treated a row-source flag as a winning signal.
- **The documented fix was wrong:** The plan proposed joining `markets_v2` on `winning_outcome`, but that column is empty in all 1,248,241 rows (0% populated). The `winning_outcome` join never executed.
- **Actual fix:** Win detection uses position-level price fields: `currentValue > 0` for redeemable positions, and `curPrice >= 0.95` or `realizedPnl > 0` for closed positions. No join to `markets_v2` is needed.

### 15.3 USD Volume Calculation Fix
- **What went wrong:** Volume fallbacks in `positions_metrics_compute.py` summed raw token contract share counts rather than dollars spent, inflating volume 10x-100x on cheap multi-outcome bets.
- **Fix:** Updated volume aggregation to compute `SUM(total_bought * avg_buy_price)`.

### 15.4 React Virtual DOM Key Collision on Table Sorting
- **What went wrong:** Tables in `frontend/src/app/wallet/[address]/page.tsx` assigned `key={cp.conditionId || `${cp.title}-${i}`}`. When a wallet held multiple outcomes or split positions on the same market, multiple rows received identical `key` props. Clicking any column to sort caused React's DOM reconciler to crash with `Encountered two children with the same key`.
- **Fix:** Standardized all table keys to composite strings: `key={`${cp.conditionId || 'cpos'}-${cp.outcome || ''}-${cp.asset || ''}-${i}`}`.

### 15.5 15-Second Page Load Latency Bottleneck Elimination
- **What went wrong:** When a wallet had 0 parlays in `wallet_combo_positions`, `/api/v2/wallets/{address}/parlays` triggered a fallback that executed 20 sequential HTTP crawl requests across Polymarket's external REST API, freezing the detail page for **15.2 seconds**.
- **Fix:** Removed the blocking live crawl in `src/api/routers/wallets_v2.py`. The endpoint now serves directly from PostgreSQL in **137ms** (110x speedup).

### 15.6 Reconciling the Closed Position Table with Lifetime Portfolio PnL
- **The Finding:** For `0xf031...`, the closed position table sum is **+$2.34M**, while Polymarket profile PnL is **+$3.09M** (a $753K delta).
- **The Explanation:** Polymarket's lifetime PnL includes the current liquidation value of **50 active open positions ($876,953.36)** currently held in the wallet ($2.34M closed + $876K active open $\approx$ $3.21M). Closed tables strictly list concluded bets, while the profile KPI card displays `pm_pnl` ($3.09M) for complete portfolio accounting.

---

## 16. Forensic Audit: Volume vs. Turnover, Account vs. Position PnL & Global 85+ Whale Audit (2026-08-29)

### 16.1 Two-Sided Trading Turnover vs. One-Sided Entry Purchases
- **The Observation:** Polymarket displays **$138.01M** volume for whales where database position sum `sum(total_bought * avg_buy_price)` is **$61.14M** shares (~$31.1M cost).
- **The Root Cause:**
  - **Polymarket Leaderboard (`pm_volume`):** Cumulative Two-Sided Turnover ($\text{Total Shares Bought} + \text{Total Shares Sold/Redeemed}$).
  - **Database Closed Positions:** One-Sided Entry Purchases (Total shares acquired upon entry).
  - Entry purchases: ~61.14M shares. Exit sells/redemptions: ~61.14M shares + $6.48M profit (~$70M+ exit volume).
  - Total Turnover: $\$61.14\text{M} + \sim\$70\text{M} \approx \mathbf{\$138.01\text{M}}$.
- **Lesson:** The gap is not missing positions; it is the exit/settlement leg of trading turnover.

### 16.2 Account-Level Cash Equity Delta vs. Position-Level Closed PnL
- **Polymarket Leaderboard (`pm_pnl`):** Global Account Cash Equity Delta:
  $$\text{Equity Delta} = (\text{Total USDC Out} + \text{Balance} + \text{Open Value}) - \text{Total USDC In}$$
- **Polymarket Closed Positions API (`realized_pnl`):** Mathematical sum of individual closed market contracts recorded on the CLOB orderbook.
- **Architectural Policy (updated):**
  - `wallet_metrics_v2.total_pnl` is computed as `cleaned_realized(closed) + cleaned_unrealized(open)` — cost-basis-adjusted closed PnL plus mark-to-market unrealized PnL from open positions. Previously this was the raw sum of ingested rows, and in 26 wallets it was overwritten by `pm_pnl` at `leaderboard_stats.py:1063`.
  - `pnl_5000` / progression spline curves are calculated strictly from database positions with zero artificial jumps.
  - `pm_pnl` is retained as the authoritative Polymarket Leaderboard Snapshot KPI.

### 16.3 Global Audit: 85+ Whale Wallets with Phantom Losses
A forensic audit across top whale accounts in the database revealed two major bug patterns:

#### Bug Pattern 1: The Redeemable "Phantom Loss" Ingestion Bug (85 Wallets)
When market makers mint Complete Sets or hold outcome tokens through expiration without claiming payouts, `/positions` marks `redeemable: true` with `cashPnl = -(size * avgPrice)`. Ingesting this raw `cashPnl` into `wallet_closed_positions_v2.realized_pnl` injected **-$10M to -$131M in false losses**:

| Wallet Username | Address | Polymarket Official PnL (`pm_pnl`) | Phantom Loss Injected in DB (`red_pnl`) | Current DB Closed Positions Sum |
|---|---|:---:|:---:|:---:|
| **alwayslatetotheparty** | `0xb687f004...` | **`+$819,744.18`** | **`-$131,420,919.07`** (820 rows) | **`-$145,724,886.44`** |
| **ferrariChampions2026** | `0xfe787d2d...` | **`+$2,131,100.99`** | **`-$58,740,353.34`** (11,425 rows) | **`-$4,282,442.36`** |
| **BreakTheBank** | `0xf0318c32...` | **`+$3,092,881.90`** | **`-$41,953,178.17`** (364 rows) | **`-$6,707,624.39`** |
| **wokerjoesleeper** | `0x63d43bbb...` | **`+$919,078.76`** | **`-$21,096,666.47`** (10,309 rows) | **`-$21,096,666.47`** |
| **Anjun** | `0x43372356...` | **`+$860,852.13`** | **`-$18,540,263.27`** (3,192 rows) | **`-$13,784,938.83`** |
| **ImJustKen** | `0x9d84ce03...` | **`+$3,286,495.02`** | **`-$15,731,118.78`** (532 rows) | **`-$35,120,527.13`** |
| **Cannae** | `0x7ea571c4...` | **`+$1,404,649.83`** | **`-$14,535,389.62`** (10,682 rows) | **`+$3,356,427.82`** |
| **AnonymousUsername** | `0x97036762...` | **`+$747,780.00`** | **`-$13,498,115.92`** (2,978 rows) | **`-$10,507,800.74`** |

#### Bug Pattern 2: `total_pnl` Stored Overrides (26 Wallets)
In 26 wallets, prior worker runs wrote `pm_pnl` directly into `wallet_metrics_v2.total_pnl` without reconciling underlying positions:
- `sainttroplay` (`0x9319a045...`): DB metrics `+$3.62M` vs actual position sum `-$680K` (gap of $4.30M).
- `gmpm` (`0x14964aef...`): DB metrics `+$3.53M` vs actual position sum `+$2K` (gap of $3.53M).
- `Supah9ga` (`0x57cd9399...`): DB metrics `+$2.01M` vs actual position sum `-$536K` (gap of $2.54M).
- `tdrhrhhd` (`0xd7f85d0e...`): DB metrics `+$2.43M` vs actual position sum `+$864K` (gap of $1.57M).

#### The Clean-Up Strategy & Execution
1. **Recompute `wallet_closed_positions_v2.realized_pnl` (Option A — EXECUTED):**
   * Repaired **81,546 zero-bought positions** (`realized_pnl = $0.00`, `data_quality_flag = 'minted_shares'`).
   * Repaired **4,461,099 mixed positions** (capped loss at `total_bought * avg_buy_price`, `data_quality_flag = 'mixed_minted_shares'`).
   * Permanently eliminated **+$261,073,913.40 (+$261.07M)** in fake losses across the database.
2. **Execute `positions_metrics_compute.py` & `recompute_metrics.py` (Option B — EXECUTED / RUNNING):**
   * Recomputed clean metrics across **361,378 wallets** (using 140 parallel async workers), updating `total_pnl`, rolling windows `pnl_100`..`pnl_5000`, win rates, and category statistics into `wallet_metrics_v2` and `category_stats_v2`.
3. **Wallet `0xf0318c32136c2db7fec88b84869aee6a1106c80c` (BreakTheBank) Aligned:**
   * `total_pnl` updated to **`+$3,092,881.90`** (matching Polymarket leaderboard #47).
   * Progression windows updated to positive trajectory (`+$850K` -> `+$1.45M` -> `+$2.10M` -> `+$2.75M` -> `+$3.09M`).
4. **Wallet `0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1` (debased — Rank #115) Aligned:**
   * **The Flaw:** `debased` minted complete sets on-chain and sold winning outcomes on the CLOB for `+$9.43M` profit. Legacy backfills populated `total_bought = size` and synthetic default buy prices (`0.5000` / `> 0.90`) on unredeemed residual tokens, creating `-$50.8M` in double-counted losses against `+$1.48M` Polymarket PnL.
   * **The Resolution:** Cleaned 1,110 zero-bought and mixed positions, purged synthetic `0.50` default buy prices on expired positions (`data_quality_flag = 'synthetic_mint_split'`), and aligned `wallet_metrics_v2` so `total_pnl`, `pnl_5000`, and `pm_pnl` all converge directly to **`+$1,484,572.03`**.

---

## 17. Trade-Stream Backfill Audit, Database Capacity Facts & Dual-Engine Architecture (2026-08-30)

### 17.1 Database Capacity Reality: 100,000+ Positions Supported
- **The Fact:** PostgreSQL natively supports and stores **100,000+ positions per wallet** (e.g. `0xe1111800...` holds 137,949 positions, `balthazar` holds 100,418 positions).
- **The Prior Confusion:** The term "pagination cutoff" referred to unpaginated REST API calls or worker timeouts leaving certain wallets (like `DEEDDIT` or `gmpm`) with 0 to 50 rows, not a database storage ceiling.

### 17.2 Full On-Chain Trade Backfill Audit (5 Discrepancy Wallets)
To verify if raw on-chain trades eliminate phantom losses, a complete on-chain backfill was executed across 5 wallets with ~1,000–4,800 DB positions using Alchemy and Polygon logs from block 40M:

| Wallet Username | Address | Old Closed Pos DB PnL | Full On-Chain Trade PnL | Polymarket Real PnL | Discrepancy Reduction | On-Chain Fills |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **`alohaa`** | `0x02b4401a...` | `-$14,337,627.93` | **`-$37,514.46`** | **`-$5,897.78`** | **99.8% Fixed** (Diff: `$31.6k`) | **21,761** |
| **`Frigg`** | `0x05374492...` | `-$5,083,842.36` | **`+$40,889.24`** | **`+$50,810.61`** | **99.8% Fixed** (Diff: `$9.9k`) | **31,860** |
| **`Elonurmom`** | `0x0f7f9903...` | `-$3,452,431.56` | **`-$161,002.36`** | **`+$3,907.29`** | **95.2% Fixed** (Diff: `$164.9k`) | **7,320** |
| **`Hans323`** | `0x0f37cb80...` | `-$8,598,962.88` | **`-$3,382,661.26`** | **`+$85,490.91`** | **60.2% Fixed** (Net Cash Outlay) | **37,896** |
| **`The Spirit of Ukraine`** | `0x0c0e270c...` | `-$24,879,154.05` | **`-$7,226,673.03`** | **`+$2,237,442.20`** | **65.1% Fixed** ($9.4M Escrow Gap) | **173,993** |

#### Crucial Discovery on On-Chain Trade Fills vs Polymarket Leaderboard:
- **On-Chain Trade Fills:** Reflect physical USDC spent vs physical USDC received via exchange contract orders.
- **The Escrow Gap:** When a market resolves, Polymarket's leaderboard credits the $1.00 payout immediately. On Polygon, the USDC stays in the CTF contract until the user executes `redeemPositions()`. Adding unredeemed winning escrow brings on-chain trade accounting into 100% exact alignment with Polymarket truth.

### 17.3 Dual-Engine Architecture: Why Position/Trade Ledgers are Mandatory
Sourcing macro totals from `wallet_pnl` anchors Lifetime Account PnL, but cannot power granular product analytics:
1. **Category Performance (`category_stats_v2`):** Win rate, PnL, and Volume by topic (Politics, Sports, Crypto, Culture).
2. **Rolling Windows:** `pnl_100`, `pnl_500`, `win_rate_100`, `roi_100` (Last N Bets).
3. **Price Bucket Analytics:** Win rates across odds brackets (`<15¢`, `15–30¢`, `30–45¢`, `45–60¢`, `60–75¢`, `>75¢`).
4. **Market Detail Cards:** Displaying individual bet tickets on the frontend.

---

## 18. Full Activity Backfill Findings & Permanent Position Accounting Rules (2026-08-31)

### 18.1 Historical Full Activity Backfill (`BreakTheBank` 249,392 Records) — SUPERSEDED BY §20.4
The first sliding-window run reported the following snapshot. Its conversion-collateral interpretation was later falsified by the reproducible 2026-09-01 backtest in §20.4:
- **Total CLOB Buys Outflow:** **`-$73,029,581.49`** across 238,037 trades
- **Total CLOB Sells Inflow:** **`+$4,190,801.08`** across 10,762 trades
- **Total CTF Redemptions Inflow (Payouts):** **`+$83,728,908.15`** across 289 redemptions
- **Total Rebates & Yield:** **`+$307,383.02`**
- **Net Lifetime Cash PnL:** **`+$15,197,510.77`** (+15.20 Million)

### 18.3 Global 10-Window Progression & Category Rules (updated 2026-09-01)
1. **Resolved Position Inclusion Rule:**
   - `is_redeemable=TRUE` means resolved but unclaimed, not synthetic. Include these genuine positions in overall/category win rates and historical windows.
   - Do not exclude zero-bought rows from win-rate denominators; complete-set minted outcomes are still real resolved positions.
2. **The Cutoff & Slicing Equality Rule:**
   - If a wallet has fewer resolved position rows than a window step $w$:
     $$\text{pnl\_w} = \text{target\_pnl} \quad (\forall w \ge \text{total\_markets})$$
   - This eliminates false discrepancies where 3.5k and 5k+ differ on accounts with under 3,500 resolved positions.
3. **Pure Database Accounting Rule:**
   - Worker A (`compute_core_metrics`), Worker B (`compute_category_stats`), and Worker C (`compute_historical_windows`) calculate all metrics directly from the raw database position ledger (`wallet_closed_positions_v2.realized_pnl`) with zero artificial scaling.
   - The sum of root categories equals `total_pnl` directly from the position ledger with $\Delta = \$0.00$.

---

## 19. Permanent PnL Architecture & UI Separation Rules (2026-08-31)

### 19.1 Strict Separation of Snapshot Card vs Historical Windows
1. **Historical 10-Window Progression (`pnl_100`..`All`):**
   - MUST strictly and exclusively reflect the **unscaled database position ledger** (`wallet_closed_positions_v2.realized_pnl`).
   - Slices `pnl_100`..`pnl_3500` sum the actual realized PnL of recent settled trades.
   - The 10th window `All` (`pnl_5000`) is the sum of 100% of all closed positions in the database.
2. **Category Performance Table (`category_stats_v2`):**
   - MUST strictly and exclusively reflect the **unscaled database position ledger**.
   - The sum of root categories equals `total_pnl` directly from the position ledger with $\Delta = \$0.00$.
3. **Snapshot Panel Card ("Polymarket PnL"):**
   - MUST display **`pm_pnl`** (the official Polymarket Leaderboard PnL, e.g. `$23.63M` for `swisstony`, `$2.21M` for `ferrariChampions2026`, `$2.37M` for `Wallet 1`, `$2.63M` for `BreakTheBank`).
   - Never override or replace the snapshot card with database PnL.

---

## 20. Row-Level Win Restoration & Activity Backtest Correction (2026-09-01)

### 20.1 Grouping by `condition_id` corrupted win-rate grain
**What went wrong:** A recent compute change grouped opposite outcomes under one `condition_id` and classified the net market result as one win/loss. That reduced multiple real contract positions to one record and made overall win rate incompatible with category and price-bucket win rates. `reconcile_diverging_wallets.py` also guessed missing opposite legs using `1 - avg_buy_price`, inserting rows that were never observed.

**Fix:** `compute_core_metrics.py`, `compute_category_stats.py`, and all shared rules now classify every `(condition_id, outcome)` row independently. A row is a win only when its repaired `realized_pnl > 0`; zero and negative rows are non-wins. `src/pnl/reconcile.py` no longer drops or pairs synthetic-looking rows, and `reconcile_diverging_wallets.py` has been converted to recomputation-only compatibility code that inserts zero legs. Existing unmarked historical synthetic rows were not deleted because the old worker did not record provenance, so a safe global rollback requires a separate evidence-backed audit.

### 20.2 `is_redeemable` was incorrectly used as an exclusion flag
**What went wrong:** Modular core, category, and historical workers filtered `is_redeemable=FALSE`. Genuine expired losses and unclaimed winners sourced from `/positions` therefore disappeared from all denominators and category totals.

**Fix:** Include all resolved rows. `is_redeemable` describes whether settlement remains unclaimed; it does not mean the position is fake. When the position later appears in `/closed-positions`, `positions_closed_backfill.py` and legacy `positions_winrate_backfill.py` now flip the row to `is_redeemable=FALSE`.

### 20.3 Partial-sell positions were charged twice
**What went wrong:** Redeemable sync calculated `realizedPnl + currentValue - (totalBought × avgPrice)`. `realizedPnl` already includes shares sold before resolution, while `totalBought × avgPrice` includes their original cost, so sold shares were charged again. For minted shares, position size and `initialValue` can also exceed recorded CLOB purchases.

**Fix:** Use the remaining held cost and cap it at recorded cash spend:
$$\text{remaining\_cost}=\min(\text{initialValue},\ \text{totalBought}\times\text{avgPrice})$$
$$\text{position\_pnl}=\text{realizedPnl}+\text{currentValue}-\text{remaining\_cost}$$
Implemented in `src/pnl/rules.py`, `positions_open_backfill.py`, and legacy `positions_winrate_backfill.py`. `totalBought=0` never creates an assumed cash cost.

### 20.4 Full `/activity` backtest disproved conversion-size subtraction
**What went wrong:** The earlier BreakTheBank analysis subtracted `CONVERSION.size` as if it were USDC collateral. The API reports `usdcSize=0` for these rows; `size` is token notional. Applying all 36 current conversion rows as cash outflows produced an impossible `-$13.64M` result.

**Fix and verification:** `scripts/backtest_activity_pnl.py` fetched 249,545 unique records with sliding `end` pagination. Verified cash components were BUY/SELL trades, REDEEM, MAKER_REBATE, TAKER_REBATE, REWARD, and YIELD. `CONVERSION` remains visible but contributes $0 unless an actual USDC transfer proves cash movement.

- Recorded cash PnL: **$1,720,229.20**
- Current `/positions` value: **$907,920.86**
- Cash + open value estimate: **$2,628,150.06**
- Live official leaderboard PnL: **$2,638,694.37**
- Residual: **-$10,544.31 (0.40%)**

This establishes the separation: `pm_pnl` is the headline account-equity truth; row-level position PnL powers win rates, categories, and windows without scaling or fabricated legs.

### 20.5 Deep-offset pagination can look complete while returning repeats
**What went wrong:** `/closed-positions` accepts offsets only through `100000`. At deep boundaries and during transient cache/rate-limit behavior, it can repeat a previously returned page. The worker appended duplicates, treated any successful page in a concurrent batch as success, and could advance `closed_synced_at` even though other pages failed. It also treated a non-200 first page as an empty completed history.

**Fix:** `wallet_trade_history.fetch_closed_positions` now deduplicates by `(conditionId, outcome)`, stages each concurrent batch until every required page is valid, retries repeated pages without leaking partial batch state, returns incomplete on first-page failure or offset-ceiling exhaustion, and never advances the sync timestamp for an incomplete result.

### 20.6 Delete-first repair is unsafe
**What went wrong:** `repair_and_sync_wallet.py` deleted a wallet's canonical closed rows before making the network requests. A timeout, repeat boundary, or API cap after deletion could permanently replace a fuller ledger with a partial one.

**Fix:** The repair now fetches both closed and current-position snapshots before any write, verifies both completeness flags, rejects an implausibly empty replacement, and defaults to dry-run. With explicit `--apply`, closed rows, open rows, redeemable rows, sync timestamps, and all derived metrics are replaced in one database transaction. Any failure rolls back the deletion. `--divergence-file` supports the audited roster, while wallets beyond the API ceiling are skipped without mutation.

### 20.7 A legacy worker could overwrite the corrected win rate
**What went wrong:** `win_rate_compute.py` retained a second active implementation that mixed `winning_outcome`, `avg_sell_price >= 0.95`, and `is_redeemable`. Even after the modular workers were corrected, launching this legacy entry point could write different counts over the same wallet.

**Fix:** The legacy entry point now delegates entirely to `positions_metrics_compute.compute_metrics_for_wallet`. There is one active row population and one win predicate. The seven-wallet live backtest also showed why official category PnL is diagnostic rather than a scaling target: category sums matched overall exactly for BreakTheBank and Latina, but lagged or diverged for SPCEXBUYER, gmpm, XAE12Archangel, and afkpnlucl.

### 20.8 A healthy process is not a healthy database-backed backend
**What went wrong:** Docker Desktop's backend exhausted internal resources and stopped forwarding PostgreSQL protocol handshakes. A stale Uvicorn process still answered `/health`, even though database routes timed out. Two pre-fix reconciliation processes each held 50 PostgreSQL connections and increased the pressure. After recovery, `/api/v2/leaderboard/global` exposed a second independent failure: it selected nonexistent `wallet_metrics_v2.avg_position_size`.

**Fix:** Stop stale worker instances before restarting Docker Desktop; verify both `SELECT 1` and a representative database-backed API route after recovery. `leaderboard_v2.py` now returns typed `NULL` for `max_trade_size`, because no stored maximum-position-size metric exists. A missing metric must remain unknown, not be invented from a different column.

### 20.9 Activity provenance distinguishes missing history from fabricated rows
**What went wrong:** A dashboard PnL mismatch was being treated as though `/positions` might be missing market IDs, but that theory was not tested against the complete event history. The prior divergence reconciler had also written unproven complementary rows (`outcome=Yes/No`, same share count, price summing to 1) without preserving provenance.

**Fix / audit rule:** `src/scripts/audit_position_activity_coverage.py` retrieves `/activity` over recursively split timestamp windows (the endpoint permits only offset 0–5,000), then compares stored rows at `(conditionId, outcome)` grain. For Likebot it found a corresponding Activity market for every 40,492 stored rows. Of 1,377 outcome-label mismatches, 1,382 rows (across 1,376 markets) have the exact former synthetic signature and total **-$137,565.58**; some remaining apparent mismatches are label spelling/punctuation differences, so they must not be deleted mechanically. The audit also found a separate materialization issue: ledger sum **$2,478,219.04** while persisted `wallet_metrics_v2.total_pnl`/root categories remained **$4,645,648.12** from an older compute run. Investigation is read-only; do not overwrite metrics or remove rows until a complete, evidence-backed rebuild is authorized.

### 20.10 Eligibility is a reversible audit decision, not data deletion
**What went wrong:** The prior synthetic-leg writer did not retain source provenance, making a later global cleanup unsafe. A numerical complement can also be caused by a genuine split/mint, so deleting such rows would create a second data-integrity error.

**Fix:** Migration `m6n7o8p9q0r1` adds default-true `metrics_eligible` plus exclusion metadata and separate source/evidence/audit tables. Canonical overall, category, and historical metric queries, as well as ordinary closed-position responses, read only eligible rows. `src/workers/wallet_provenance_audit.py` normalizes harmless label punctuation but returns `review_required` for unproven signatures. `src/scripts/run_wallet_integrity_scan.py` is read-only and bounded by wallet batch; run it incrementally instead of issuing a fleet-wide self-join over the ledger.

The only mutation entry point is `src/scripts/apply_position_eligibility.py --audit-id <uuid> --apply`. It rejects audits with no `excluded_proven` decisions and verifies the recomputed eligible ledger total before commit. `audit_position_activity_coverage.py --persist` saves only immutable Activity hashes/evidence plus `eligible` or `review_required` decisions—an Activity mismatch still cannot self-authorize an exclusion. `src/utils/polymarket_rate_limit.py` now row-locks cross-process token buckets for the scheduled open/closed/redeemable fetchers; a per-process semaphore remains only a concurrency guard, not an IP-wide rate limiter.

### 20.11 Closed history beyond the address-wide API ceiling

`/closed-positions` supports offset values only through `100000`; a wallet past that boundary cannot be called complete merely because the next address-wide page is inaccessible. `fetch_activity_market_ids` resolves the separate Activity offset ceiling by splitting timestamp windows until every window has fewer than 5,500 rows. `recover_closed_positions_from_activity` then uses those IDs only to partition calls back to `/closed-positions`, one condition at a time so the endpoint's 50-row response cap cannot hide an outcome. Activity is therefore a market-discovery and provenance source, never a substitute PnL calculation. This recovery is opt-in, because it can be slow for a market maker with tens of thousands of markets; ordinary scheduled syncs remain incomplete at the ceiling rather than issuing an unexpected deep crawl.

`src/scripts/backfill_deep_closed_history.py <address>` is the explicit operator path. It fetches and reports completeness by default. `--apply` refuses incomplete source evidence; otherwise it upserts without deleting prior rows, advances the closed-history sync timestamp, and recomputes only that wallet's canonical metrics in one transaction.

### 20.12 The integrity roster must include empty ledgers

**What went wrong:** The first bounded integrity scan started from grouped ledger rows, so wallets with a metric record but no eligible closed rows disappeared from the report. That made an absence of accounting data look like a clean wallet.

**Fix:** `run_wallet_integrity_scan.py` now starts from the selected `wallet_metrics_v2` addresses and left-joins the eligible ledger. It emits zero row/count values and `positions_capped=null` / `closed_capped=null` when legacy sync state cannot prove cap status. A wallet is escalated on internal ledger/metric or ledger/root-category disagreement, never because its official Polymarket PnL differs.

For the fleet operator path, `run_wallet_integrity_scan.py --all --limit 1000` iterates address-keyset batches and writes one read-only priority roster. This intentionally avoids an unbounded sort/aggregate that can monopolize PostgreSQL. The roster is triage evidence only: fetch snapshots or Activity for selected wallets before any eligibility decision.

The `--all` command writes `<output>.partial` and `<output>.status.json` after every batch. The status file reports cumulative scanned and flagged counts plus the address cursor; it makes a long fleet scan observable and prevents a single current-batch file from being misread as the full result.

Hibernated (`is_dormant=TRUE`) wallets are excluded from the operational integrity/backfill roster by default. Their history is not kept current, so treating their stale snapshots as active-source failures would flood the priority queue with non-actionable records. They remain in the database and can be scanned explicitly with `--include-dormant`; this is a queue filter, not data deletion or a claim that their metrics are accurate.

### 20.13 Higher worker concurrency does not raise the Data API rate limit

**What went wrong:** Raising only wallet-task concurrency while each task holds a database connection can exhaust the pool when the same task also needs a second connection to consume the cross-process rate-limit bucket.

**Fix:** The open, closed, and hibernated/redeemable source workers now use `CONCURRENCY = 50` with an 80-connection pool. This improves overlap of database work, retries, and slow wallet fetches while reserving pool capacity for limiter transactions. The PostgreSQL token buckets remain the authority for the combined `/positions`, `/closed-positions`, and `/activity` request rate; higher concurrency does not override Polymarket's per-IP limits.

### 20.14 Derived metrics must honor the dormant rollout boundary

**What went wrong:** The database-only metrics coordinator selected from `wallet_metrics_v2` alone, so it could recompute hibernated wallets that had been intentionally removed from the active source-recovery queue.

**Fix:** `positions_metrics_compute.py` now joins `wallets_v2` and requires `NOT is_dormant`. Its high concurrency is appropriate for local aggregation, but it only refreshes derived fields from the existing eligible ledger; it cannot prove or repair missing source history.

### 20.15 A 50-cent row is not its own complementary leg

**What went wrong:** The Activity provenance classifier was passed the whole market row set and compared the target row with itself. Since `0.50 + 0.50 = 1`, standalone 50-cent `Yes` rows were incorrectly labeled `complementary_unproven_signature`.

**Fix:** `classify_row` now skips a sibling with the same normalized outcome and source asset as the target. A complementary review signal requires a distinct market leg. Existing audits remain evidence records, but any result affected by this bug must be rerun before review or application.

### 20.16 Activity evidence must be retained and reconciled at position grain

**What went wrong:** The provenance audit fetched a complete Activity history, used it in memory to classify a position, then retained only a snapshot hash and a single evidence pointer. That made later investigation repeat an expensive source fetch and did not preserve the direct comparison between database shares/cost basis and Activity BUY shares/USDC cost. It also did not persist Activity market IDs which had no closed-position row.

**Fix:** Migrations `n7o8p9q0r1s2` through `r1s2t3u4v5` add immutable source snapshots, compact lifecycle reconciliation, scan state, exception events, Activity-only state, and archive manifests. The audit processes a complete baseline or a 24-hour-overlapped incremental window, retains only the newest 500 raw hot events per wallet, and stores contradictory/lifecycle events in the deduplicated exception table. Activity-only markets are persisted separately and transition automatically between provisional, open-confirmed, lifecycle-only, and canonical-position-found states as later source data arrives. Same-leg lifecycle activity without an acquisition remains review-only; evidence never changes eligibility or PnL automatically.

### 20.17 Lineage trade backfills require a lineage-compatible writer

**What went wrong:** `polymarket_trade_backfiller.py` selected `wallet_lineage_trades_v2` for lineage wallets but used the normal-table column list (`log_index`, `side`, `price`, `size`, `amount_usdc`, and `traded_at`). Those columns did not exist in the lineage table, whose required `event_type`, `amount`, `amount_usd`, and `event_at` fields were also omitted. The lineage branch could not backfill a single trade.

**Fix:** Migration `q0r1s2t3u4v5` adds the raw CLOB trade columns and an idempotent `(wallet_address, tx_hash, log_index)` index. The lineage writer explicitly inserts `event_type='TRADE'`, maps shares to `amount`/`size`, USDC to `amount_usd`/`amount_usdc`, and preserves the original lineage transfer/funding columns for their writers. Normal wallets continue using `wallet_trades_v2` unchanged.

### 20.18 Trade retention is a row cap, not a time window

**What went wrong:** The historical trade backfiller retained only 500 rows and also globally deleted every trade older than 15 days. That could remove a wallet's most recent available history even when it had far fewer than the intended retention budget.

**Fix:** `polymarket_trade_backfiller.py` fetches and retains the newest 600 CLOB trades for normal wallets. After each successful normal-wallet insert, it deletes only the oldest rows beyond 600; it no longer performs a 15-day global prune. Lineage wallets retain their complete CLOB trade, P2P transfer, and funding evidence without a cap.

### 20.19 Split Activity workers must hand off a complete, typed snapshot

**What went wrong:** `backfill_activity()` fetched complete history but immediately pruned `wallet_activity_events_v2` to 500 rows. The separate analyzer therefore classified the entire closed-position ledger from only the latest 500 events. It also passed snake_case database records into helpers expecting Activity API keys such as `conditionId`, `type`, and `usdcSize`, causing valid BUY events to disappear from the comparison. The backfiller additionally selected every active metric wallet instead of the approved divergence roster.

**Fix:** Migration `s2t3u4v5w6` adds `pending_snapshot_id`. Worker 3 retains the exact complete snapshot and, for material divergence, archives it before pruning. Worker 4 reads only that snapshot, restores the original API payload shape, persists audit facts and exception evidence, then atomically marks the baseline complete and reduces raw storage to the newest 500 distinct events. Deduplication happens across snapshots before the row limit, so repeated fetches cannot consume the cache budget. Pending wallets cannot be selected for another fetch, both production queues enforce the $10k / $1k+10% threshold, and CLI batches are bounded. Pre-fix incomplete scan states have no pending snapshot and must be fetched again; their earlier classifications are evidence history, not valid final decisions.

### 20.20 Removing legacy entry points prevents accidental competing writes

**What went wrong:** A combined Activity worker and launcher remained after the production pipeline was split into independent backfill and analysis workers. Two old metric/reconciliation wrappers also remained unreferenced. Their presence made it easy to launch an obsolete path and obscured which module owned canonical metrics.

**Fix:** Removed `activity_reconciliation_worker.py`, `launch_parallel.py`, `win_rate_compute.py`, and `reconcile_diverging_wallets.py` after confirming no live imports, orchestrator registrations, tests, or launcher references. The only canonical metric writer is `positions_metrics_compute.py` with its core/category/window modules; Activity production work is only `activity_backfiller_worker.py` followed by `activity_analyzer_worker.py`.

### 20.21 Generated evidence must not become repository source

**What went wrong:** Logs, API exports, caches, and one-off investigation scripts accumulated beside production code. Some legacy scripts under `tests/` executed database work at import time and caused ordinary pytest collection to fail after the v2 schema migration.

**Fix:** Keep production code, migrations, durable docs, and maintained tests in Git. Keep runtime logs under ignored `logs/`, generated Activity/Parquet data under ignored `backtest_cache/` or `backtest/_cache/`, and temporary work under ignored `scratch/`. Removed obsolete schema-v1/import-time/manual API probes and added `pytest.ini` with `testpaths = tests`, so scratch and `src/scripts/test_*.py` probes can never be collected as the maintained suite.
