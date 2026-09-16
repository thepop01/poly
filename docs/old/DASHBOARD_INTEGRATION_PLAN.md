# Plan: Dashboard Integration + Tier Removal + Page Retirement

**Date:** 2026-07-19
**Decisions locked in:**
- Tier removal goes all the way to the database (rename concept, see Phase 2 note).
- "User profile trades" = trades from the user's own wallet (`users.wallet_address` / connected wallet).
- Layout = single scrolling page (no tabs).
- `/alpha-calls` and `/wallets/custom` are removed ONLY after the new dashboard is verified live (Phase 3).

**Key constraint:** `wallets_v2.tier` is not just a display tag — it is the wallet lifecycle
state (`UNCLASSIFIED → DEAD / LOW_BALANCE / NEW / STANDARD / CURATED`) that the vetting
workers, leaderboard tabs, and the alpha-feed filter run on. Dropping it outright would
break wallet discovery. Therefore: remove "tier" completely from code and DB by
**renaming the concept to `status`** — the user-facing "Tier" tag and all "tier" naming
disappear everywhere, while the pipeline keeps working.

---

## Phase 1 — Rebuild `/dashboard` as a single scrolling page

Rework `frontend/src/app/dashboard/page.tsx` into stacked sections (drop the current
Overview/Watchlist/Agents pill tabs):

1. **Profile section (top)**
   - User card: username/avatar from `useAuth`, Discord badge.
   - Connected wallet from wagmi / `users.wallet_address`.
   - **"My trades"** table via existing `GET /api/v2/wallets/{address}/trades` for that address.
   - Empty state when no wallet is connected/linked.
2. **Tracked wallets (list only)**
   - Reuse `WatchlistSnapshot` fed by `getWatchlist()`, full list (not sliced).
3. **Activity section**
   - Port the full feed from `/alpha-calls` into new `frontend/src/app/dashboard/ActivityFeed.tsx`:
     stat cards, All/Trades/Deposits tabs, size filter, search, table, pagination.
   - **No Tier column, no TierBadge** from day one.
4. **Import wallets section**
   - Port the textarea + CSV upload form from `/wallets/custom` into new
     `frontend/src/app/dashboard/ImportWallets.tsx` (same `addCustomWallets()` call).

Old `/alpha-calls` and `/wallets/custom` pages stay untouched and reachable during this phase.

## Phase 2 — Remove "tier" from code and database

### Frontend
- Delete `components/ui/TierBadge.tsx`; remove `tierNumber()`, `wallet_tier` field, Tier column
  (already excluded from the new ActivityFeed).
- Rename the size-bucket filter: values `"Tier 4"…"Tier 1"` → explicit params
  (`min_amount`/`max_amount`); labels stay "$100k+", "$50k+", "$20k+", "$5k+".
- Remove `tier` from:
  - `utils/api.ts` (`getSmartMoneyAlerts` signature)
  - `utils/websocket.ts` type
  - `components/wallets/WalletTable.tsx` interface
  - `--color-tier-*` tokens in `globals.css`

### Backend (rename `tier` → `status`, `tier_reason` → `status_reason`)
- Alembic migration:
  - `ALTER TABLE wallets_v2 RENAME COLUMN tier TO status` (+ `tier_reason` → `status_reason`)
  - Recreate the two partial indexes (`idx_wallets_tier_v2`, `idx_wallets_v2_tier_dormant`)
    under new names.
- Update every SQL reference:
  - Routers: `alpha_calls_v2`, `alpha_calls`, `watchlist`, `leaderboard_v2`,
    `tracked_wallets_v2`, `trades_v2`, `custom_wallets`, `leaderboard`
  - Workers: `stats_refresher`, `poly_leaderboard_sync`, `leaderboard_stats`,
    `leaderboard_stats_v2`, `wallet_trade_history`, `trade_tracker`, `deposit_tracker`
- `alpha_calls_v2`:
  - Drop `w.tier as wallet_tier` from the SELECT.
  - Replace the `tier: str` query param with `min_amount`/`max_amount` floats.
- Response payloads no longer contain any `tier`/`wallet_tier` key.
- NOTE: the leaderboard "window tier" (100/300/800/1500/2500) in `leaderboard.py:790`
  is a different concept — left alone.

## Phase 3 — Verify, then retire old pages

### Verification checklist (live, with the stack running)
- [ ] Dashboard loads logged-out (activity feed public, profile/watchlist gated) and logged-in.
- [ ] My-trades table renders for a linked wallet; watchlist list matches `/api/watchlist`.
- [ ] Activity feed parity vs old `/alpha-calls`: counts, tabs, size filter (new params),
      search, pagination, add-to-watchlist.
- [ ] Import form adds wallets (check `wallets_v2` rows follow the same
      `status='UNCLASSIFIED'`/`CURATED` path as before).
- [ ] Workers still classify (run one `wallet_trade_history` pass); leaderboard tabs still
      populate; `alembic upgrade head` replays clean from zero.

### Then remove
- Delete `frontend/src/app/alpha-calls/` and `frontend/src/app/wallets/custom/`.
- Update `Sidebar.tsx`: drop "Custom Wallets" and "Alpha Calls" nav items; update the
  `AlphaCallsSnapshot` "Open full feed" link (or fold that snapshot into the new
  Activity section).
- Grep sweep for dead links to `/alpha-calls` and `/wallets/custom`.

---

**Order of work:** Phase 1 → Phase 2 (frontend, then backend + migration) → Phase 3 only
after the checklist passes.
