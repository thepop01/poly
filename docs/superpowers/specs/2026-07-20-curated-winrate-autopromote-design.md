# Curated Wallets — Win Rate & Auto-Promotion Design

**Date:** 2026-07-20
**Status:** Approved for planning
**Branch:** feat/curated-windowed-stats

## Problem

1. The CURATED tier is 100% manual today (`POST /v2/wallets/custom`). There is
   no engine that auto-adds or auto-removes wallets, so the curated list never
   changes on its own. The page advertises criteria (ROI/PnL/win-rate) that
   nothing enforces.
2. Win rate is structurally inflated. The current pipeline defines a "resolved"
   position by on-chain **PayoutRedemption** events
   (`etherscan_client.build_synthetic_closed_positions`). A redemption only
   fires when a wallet **wins and claims**. Losers who buy and ride a position
   to ~$0 without selling or redeeming emit no event, so they never enter the
   denominator. Win rate becomes ~"winners ÷ winners".
3. Stale frontend copy on the curated page says "Win Rate > 70%", which is no
   longer a promotion criterion.

## Goals

- Auto-promote/demote wallets into the CURATED tier on real thresholds.
- Compute an honest win rate that includes hold-to-zero losers.
- Keep a raw individual-trade store for a future trade-feed UI, decoupled from
  the metrics pipeline.

## Non-Goals

- No Kalshi / LLM features.
- No change to how headline PnL/volume is sourced (still website/leaderboard).
- Trade feed UI itself is out of scope; only its data store is built here.

## Architecture: two decoupled pipelines

- **Metrics pipeline (positions)** — drives win rate, ROI, windowed stats, and
  the auto-promotion sweep. Source: Polymarket positions + market resolution.
- **Trade-feed pipeline (raw fills)** — feeds a future trade-feed UI only. Never
  an input to metrics. Independent so it cannot block or corrupt the metrics
  path. Source: per-wallet Polygon (Polygonscan) OrderFilled logs.

The two never join for computation. Positions decide metrics; trades decide the
feed.

## Data model

### `curated_positions` (metrics source of truth)

One row per `(wallet_address, condition_id, outcome)`:

| column | meaning |
|---|---|
| wallet_address | curated wallet |
| condition_id | market condition id |
| outcome / outcome_index | which side the wallet held |
| total_bought / total_sold | USDC in/out for this position |
| net_tokens | tokens still held at resolution |
| market_resolved (bool) | did the market settle |
| won (bool) | did this outcome win |
| payout | net_tokens × $1 if won else 0 |
| realized_pnl | payout + total_sold − total_bought |
| is_resolved (bool) | market_resolved is true |
| is_win (bool) | realized_pnl > 0 |
| resolved_at | market resolution timestamp |
| category / subcategory | from market metadata |

### `curated_trades` (feed only)

One row per fill. PK `(tx_hash, log_index)` for idempotent upsert:
`wallet_address, tx_hash, log_index, condition_id, outcome, outcome_index,
side, price, size, amount_usdc, traded_at, market_name, category, subcategory`.

## Win/loss determination (fixes hidden losers)

For each curated wallet, pull from Polymarket:
- **Resolved/closed positions** (carry `realizedPnl`) — the genuine sold-out
  closes and claimed wins.
- **Open positions** — for each, look up whether its market has resolved via
  CLOB/Gamma metadata (already wired in `_fetch_market_meta`, cached by
  `condition_id` since resolution is immutable once set). If the market
  resolved and the wallet held the **losing** outcome, mark the position lost.
  This is the fix for bought-and-rode-to-zero losers that never redeem.

Classification:
```
realized_pnl = payout + total_sold − total_bought
   payout = net_tokens_held_at_resolution × $1  (if outcome won, else 0)
is_win   = realized_pnl > 0
win_rate = count(is_win) / count(is_resolved)
```

`is_win` keys on the **sign of PnL**, not on "held the winning outcome", so
partial sells and break-evens classify correctly. Win/loss is correct even if
Polymarket missed some fills, because only the sign — not the magnitude — of
PnL matters for classification. This is why positions beat raw trades for win
rate. No Polygonscan calls on this path.

## Backfill

Per curated wallet, one-time: pull up to **5000 positions** (the endpoint's own
cap; no time/date limit), classify each (resolved, or open→lost via market
resolution), and store. For whales beyond the cap, "all-time" means "most
recent ~5000 positions" — documented, not hidden.

## Live updates

- **Positions (metrics):** periodically re-pull each curated wallet's capped
  open + resolved positions, re-derive rows, and re-check still-open positions
  for newly-resolved markets (flip to resolved/win/loss). No block bookkeeping.
- **Trades (feed):** separate per-wallet incremental Polygon poll — fetch
  OrderFilled logs from `last_synced_block + 1` to latest, upsert new fills,
  advance the cursor. Independent cadence; reuses
  `fetch_historical_trades_polygonscan`.

## Wiring into stats

`leaderboard_stats_v2.py` stops calling the redemption scanner for curated
wallets and reads win rate / ROI / PnL from `curated_positions`. The windowed
axis (ALL-TIME / LAST 100 / 300 / 800 / 1500 / 2500) slices `curated_positions`
by `resolved_at DESC` — now including losers — so the windows finally mean
"last N resolved positions" honestly.

## Auto-promote / demote

In `stats_refresher.py`, two SQL sweeps run every 10 minutes (existing worker
loop, `POLL_INTERVAL = 600`):

- **Promote** — the sweep scans the FULL candidate pool, not a top-N slice and
  not only leaderboard entries. Candidate pool = active (`is_dormant = FALSE`)
  wallets whose tier is **not** NEW and **not** LOW_BALANCE (and not already
  CURATED / DEAD / UNCLASSIFIED) — in practice, active STANDARD wallets. Any
  candidate whose metrics satisfy:
  ```
  (roi_pct > CURATED_MIN_ROI OR total_pnl > CURATED_MIN_PNL)
    AND resolved_count >= CURATED_MIN_RESOLVED
  ```
  is promoted → `tier = 'CURATED'`, `tier_reason = 'auto: roi/pnl threshold'`.

  This replaces the old `poly_leaderboard_sync.check_and_promote_curated`, which
  only ever checked Polymarket's public per-category top-100 (`entries[:100]`)
  and therefore never promoted a qualifying wallet that wasn't on that public
  list. `poly_leaderboard_sync.py` reverts to discovery-only.
- **Demote** — a CURATED, non-`custom` wallet that no longer satisfies the rule
  → reset to the canonical stats tier (STANDARD/LOW_BALANCE/NEW/DEAD via the
  existing CASE logic).
- **Sticky manual:** wallets with a `wallet_sources_v2` row `source='custom'`
  are never demoted.

Thresholds as named constants (defaults, tunable):
`CURATED_MIN_ROI = 30`, `CURATED_MIN_PNL = 10000`, `CURATED_MIN_RESOLVED = 10`.

The existing reclassify sweep keeps its `WHERE tier NOT IN ('CURATED',
'UNCLASSIFIED')` guard, so it does not fight the demote step.

### Known boundary caveat

`resolved_count` for promotion **candidates** (non-curated) comes from Supabase
(~1.4% null in current data, so viable — nulls simply don't promote). Once a
wallet is curated, `resolved_count` comes from the accurate `curated_positions`.
This slight source difference across the promotion boundary self-corrects on the
cycle after promotion. Accepted.

## Frontend

Update the stale curated-page criteria string from "Win Rate > 70%" to
"ROI > 30% OR PnL > $10k · active in last 30 days".

## Migration safety

**Correction (verified in code 2026-07-20):** `global_wallet_trades` (≈899k
rows) has exactly ONE writer (`leaderboard_stats.py`, curated-wallet branch) and
**zero readers** — `trades_v2.py` and the frontend actually read
`wallet_activity_v2`, not this table. The earlier "read by trades_v2 and the
frontend" claim (from README) is inaccurate. So dropping it is low-risk. Still:
grep for readers again at implementation time, stop the writer first, then drop.

## Testing

- Position classification: winner (redeemed), sold-out close, hold-to-zero loser
  (open + market resolved + losing outcome → loss), open + unresolved (excluded).
- Win rate denominator includes losers.
- Backfill stops at 5000 positions.
- Auto-promote: qualifying candidate promotes; formerly-qualifying auto wallet
  that dropped demotes; `custom` wallet below threshold stays; dormant wallet
  above threshold does not promote; null-`resolved_count` candidate does not
  promote.

