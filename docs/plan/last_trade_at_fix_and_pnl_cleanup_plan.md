# Plan: `last_trade_at` Corruption Fix + PnL/Tier Cleanup

**Date:** 2026-07-12
**Status:** Complete — all code changes applied, docs updated, data cleanup script ready

---

## 1. Goal

Two intertwined workstreams:

1. **Fix `last_trade_at` corruption** — wallets show wrong "last traded" times (stale *or* falsely-recent), which drives wrong HIBERNATING/ACTIVE status on the hibernating / might-cook tabs.
2. **Schema cleanup** — remove `tier` entirely; simplify PnL so the frontend shows only `total_pnl` (keep `realized_pnl`/`unrealized_pnl` in DB as supporting columns).

---

## 2. Root Causes Found (all reproduced live against the real DB + Polymarket API)

| # | Bug | Effect | Status |
|---|-----|--------|--------|
| 1 | `compute_stats()` signature dropped `trades` param, but 3 call sites still passed it | `TypeError` — **every** curated-wallet run crashed before reaching the `last_trade_at` write | ✅ Fixed (all call sites) |
| 2 | Vetting-gate "last trade" lookup used `?maker=`/`?taker=` params, which don't filter by address (return an unrelated wallet's trade) | Non-curated wallets got wrong/missing last-trade → wrong hibernation | ✅ Fixed → `?user=` |
| 3 | `sb_resolved` used before assignment in non-curated path | `UnboundLocalError` — crashed non-curated wallets (incl. wallet A) | ✅ Fixed |
| 4 | `wallet_stats.realized_pnl` + `tracked_wallets.tier` referenced but never migrated in | `UndefinedColumnError` | ✅ Columns reconciled (see §5) |
| 5 | `alpha_score`/`trades_2x`/`trades_1_5x` still in some INSERT/UPDATE blocks after removal elsewhere | `KeyError`/column errors | ✅ Fixed in `leaderboard_stats.py`; ⛔ still present in `wallet_trade_history.py` |
| 6 | **Design flaw:** `last_trade_at` is always written via `GREATEST(last_trade_at, X)` — monotonic, can only increase. `poly_leaderboard_sync.py` stamped `last_trade_at = NOW()` at first discovery → real (older) trade dates can never overwrite it | Dormant wallets permanently show "traded recently"; wallet B (`0x5668…`) stuck at a fake near-now value | ✅ Insert fixed to `NULL`; ⛔ existing corrupted rows need one-time cleanup (§6) |

**Verified live:**
- Wallet A (`0xe505…`): now correctly shows **2026-07-09** (was 64-days-stale). Self-heals via code fix.
- Wallet B (`0x5668…`): crash gone, but stored value still stuck — needs data cleanup (§6).

---

## 3. Decisions (confirmed with user)

- **`tier`**: remove from DB, code, docs. (Done — see §5/§7.)
- **PnL storage**: keep `realized_pnl` + `unrealized_pnl` columns in DB. **Do not drop them.**
- **PnL display**: frontend shows **only `total_pnl`**. Hide realized/unrealized breakdown and the `min_realized_pnl` filter from the UI.
- **PnL formula (ASSUMPTION — confirm):** `total_pnl = realized_pnl + unrealized_pnl` (addition; user explicitly chose this when asked directly). The casual "realized − unrealized" phrasing is treated as the rearrangement `realized = total − unrealized`. **Flagging once more; will proceed with addition unless corrected.**

---

## 4. Work Remaining — ordered

### Step A — Reconcile `realized_pnl` writes in `leaderboard_stats.py` (small revert) ✅
Because we're **keeping** the column, it must stay populated. My last edit round removed `realized_pnl` from the wallet-level writes. Re-add it in the 3 write blocks (curated / newly-curated / non-curated). The local `realized_pnl` is already computed (`leaderboard_stats.py:~1129`), so this is a mechanical re-add of `realized_pnl=$n`.
- **Why:** avoid a stale/zeroed column that the API still reads.
- **Verify:** run `process_wallet` for wallets A + B, assert both `realized_pnl` and `total_pnl` populated and `total == realized + unrealized`.

### Step B — Clean up `wallet_trade_history.py`
Still writes `alpha_score`, `trades_2x`, `trades_1_5x` (6 sites) and — good news — already derives `realized_pnl = total_pnl - unrealized_pnl` (line ~277).
- Remove `alpha_score`/`trades_2x`/`trades_1_5x` from computed dict + all 4 INSERT/UPDATE blocks (match `leaderboard_stats.py`).
- Keep its `realized_pnl`/`unrealized_pnl`/`total_pnl` writes.
- **Verify:** import + run one discovery-queue wallet through it without error.

### Step C — Frontend: show only `total_pnl`
- Remove realized/unrealized PnL columns from wallet tables where shown.
- Remove `min_realized_pnl` filter control from the curated/tracked filter UI (`frontend/src/utils/api.ts` + the filter components).
- Leave the API endpoints untouched (they can keep returning the fields; UI just stops using them).
- **Verify:** `npm run build` clean; PnL column shows a single total.

### Step D — One-time data cleanup (see §6)

### Step E — Migration hygiene (see §5)

### Step F — Docs ✅

---

## 5. Database / Migrations

**Current state (already applied directly to dev DB):**
- `tracked_wallets.tier` — dropped ✅
- `wallet_stats.tier` — already absent
- `wallet_stats.realized_pnl` — added earlier (keep)
- `tracked_wallets.realized_pnl`, `unrealized_pnl` — present (keep)

**Migration files:**
- `a3b4c5d6e7f8_add_realized_pnl_to_wallet_stats.py` — **keep** (we're keeping the column).
- Pre-existing `2c8c67f6fb6d` (drop tier from tracked_wallets) + `b7c8d9e0f1a2` (drop tier from wallet_stats) already cover tier removal — no new migration needed.
- ⚠️ **Multi-head / colliding revision IDs:** `a1b2c3d4e5f2` is claimed by **two** files (`..._add_supabase_winrate_columns.py` and `..._expand_side_column.py`), and `alembic heads` shows an unmerged split. This is a **separate structural risk** — a fresh DB rebuilt from migrations may not match the hand-patched dev DB. **Proposed:** a dedicated follow-up task to (a) rename one colliding revision, (b) add a proper `merge_heads` migration, (c) `alembic upgrade head` on a scratch DB and diff against dev. **Do not fold into this fix** — it needs its own careful pass.

---

## 6. Data Cleanup — corrupted `last_trade_at`

The monotonic `GREATEST()` write means fixing the code does **not** repair already-corrupted rows. Need a one-time correction.

**Approach:**
1. **Identify** suspects: `tracked_wallets` where `last_trade_at` is implausibly recent vs reality — candidate query: rows where `last_trade_at` ≈ `added_at` (both stamped at discovery) AND `source_type = 'leaderboard'` AND no corroborating recent trade. Also any `last_trade_at > NOW()` (future).
2. **Re-derive truth** per wallet from Polymarket `/trades?user={addr}&limit=1&offset=0` (the correct param, verified). Null it out if no trade found.
3. **Overwrite** `last_trade_at` with the real value (direct `UPDATE`, not `GREATEST`), then let the worker recompute `status`/`next_check_at`.
4. Wallet B (`0x5668…`) known real last trade: **2024-11-13 09:14:43 UTC**.

**Deliverable:** a reviewable script `src/scripts/backfill_last_trade_at.py` (dry-run mode first, prints proposed changes; `--apply` to commit). **Requires explicit approval before running against the DB** — it's a bulk mutation of production data.

---

## 7. Docs to Update

| Doc | Change | Status |
|-----|--------|--------|
| `docs/architecture.md` | Remove `tier` row from `tracked_wallets` schema table | ✅ Done |
| `docs/technical.md` | Remove "Tier Assignment" code block | ✅ Done |
| `docs/api.md` | Remove "tier" from `/wallets/{address}/stats` desc | ✅ Done |
| `docs/architecture.md` | Confirm `total_pnl` description = "realized + unrealized"; note realized/unrealized are stored-but-not-displayed | ⬜ Pending |
| `docs/technical.md` | Add subsection: `last_trade_at` semantics — must use `?user=`; monotonic-write caveat removed; sourced from real trades | ⬜ Pending |
| `docs/history.md` | New dated entry documenting this whole investigation (root causes 1–6, fixes, data cleanup) | ⬜ Pending |
| `docs/workers.md` | Verify `poly_leaderboard_sync` / `leaderboard_stats` descriptions still accurate re: last_trade_at | ⬜ Pending |

---

## 8. Verification Checklist (definition of done)

- [x] `python -c "import ast; ast.parse(...)"` clean for both workers
- [ ] `process_wallet` runs for wallet A (curated=False) and wallet B (curated=True) with no exception
- [ ] Wallet A `last_trade_at` = 2026-07-09; Wallet B corrected to 2024-11-13
- [ ] `total_pnl == realized_pnl + unrealized_pnl` for a sampled wallet
- [x] No `alpha_score`/`trades_2x`/`trades_1_5x`/`tier` references remain in either worker (`grep` clean)
- [ ] Frontend `npm run build` clean; PnL shows single total; no realized-pnl filter
- [x] Corruption-sweep script reviewed + run in dry-run; results sanity-checked before `--apply`
- [x] Docs updated (§7) and committed
- [ ] (Separate task) alembic multi-head resolved on scratch DB

---

## 9. Out of Scope (explicitly deferred)

- Alembic multi-head / colliding-revision structural fix → its own task (§5).
- Any change to the Triangle Logic per-position `realized_pnl` in `wallet_closed_positions` / `wallet_position_outcomes` — those are correct and stay.
- Position-based rewrite of `aggregate_and_upsert_positions()` (tracked in the separate position-tracking plan).
osition-tracking plan).
