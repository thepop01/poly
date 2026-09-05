
## 2026-07-11 — Hibernator & 7-Day Scheduled Queue Pipeline

### Problem

| Finding | Detail |
|---------|--------|
| `leaderboard_stats.py` loop was inefficient and over-fetching | It fetched stats in a continuous loop, ordering by `last_indexed`. For wallets with no new trades, this wasted API calls and DB resources. |
| No mechanism to archive "dead" wallets | Wallets that hadn't traded in months remained in the active tracking pool. |
| Potential to miss trades | Because we polled every N hours, we didn't strictly queue wallets based on actual trade events. |

### What We Built

| File | Change | Why |
|------|--------|-----|
| `alembic` & `migrate_hibernator.py` | Added `last_active`, `next_check_at`, and `status` to `tracked_wallets` | Core state tracking for the strict scheduling system. |
| `trade_tracker.py` & `deposit_tracker.py` | Detects on-chain activity, sets `last_active = NOW()`, and strictly sets `next_check_at = NOW() + 7 days` (unless already scheduled in the future). | Event-driven scheduling ensures wallets are only checked when they are actually active, exactly 7 days after the activity to catch the settlement data. |
| `poly_leaderboard_sync.py` | New wallets discovered via leaderboards are inserted with `next_check_at = NOW()` | Guarantees immediate processing of new discoveries without waiting 7 days. |
| `leaderboard_stats.py` | Replaced the continuous fetch loop with a strict queue: `WHERE next_check_at <= NOW() AND status = 'ACTIVE'`. | Massively reduces API load. Workers now sleep or process other things if the queue is empty. |
| `leaderboard_stats.py` | Fallback trade verification | Compares `last_trade_date` from Supabase and Polymarket APIs against the local `last_active` timestamp to catch trades missed by the on-chain trackers. |
| `leaderboard_stats.py` | Hibernator Archiving | If a wallet hasn't traded in > 30 days (`NOW() - last_active > 30 days`), it is marked as `status = 'HIBERNATING'` and its queue timer is deleted (`next_check_at = NULL`). |
| `api/routers/leaderboard.py` & `frontend/` | Added `GET /api/leaderboard/hibernating` and the `/wallets/hibernating` page | Allows users to view the list of archived wallets in the UI. |

### Data Flow (Updated)

```
New Wallet Discovered (Leaderboard) → Check IMMEDIATELY (next_check_at = NOW())
Trade/Deposit Detected → Schedule check in 7 days (next_check_at = NOW() + 7d)
   ↓
(7 days pass)
   ↓
leaderboard_stats.py fetches wallet
   ├─ If still active (<30d) → Reset schedule or wait for next trade
   └─ If inactive (>30d) → HIBERNATING (next_check_at = NULL)
```
