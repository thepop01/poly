# Database Refresh Status Report
**Started:** 2026-07-20 00:24 UTC  
**Status:** 🔄 IN PROGRESS

## Current Metrics
- **Wallets to Process:** 14,118 (updated count)
- **Processing Rate:** 7-8 wallets/second
- **Batch Size:** 100 wallets per commit
- **Task ID:** bwrxn8405

## Progress Timeline
| Time | Batch | Wallets | Rate | ETA |
|------|-------|---------|------|-----|
| 00:24:27 | 1 | 0-100 | - | ~30 min |
| 00:24:40 | 1 | 100 | 7.8 w/s | 1800s |
| 00:24:41 | 2 | 100-200 | - | - |

## What's Happening
1. ✅ Connected to database
2. ✅ Found 14,118 wallets with zero balance or position
3. 🔄 Fetching live data in batches:
   - **Batch 1:** Processing wallets 0-100
   - Running Alchemy API for balance (9 concurrent)
   - Running Polymarket API for positions (15 concurrent)
4. 📝 Updating `wallet_metrics_v2` table with:
   - Fresh balance from Alchemy
   - Fresh position_value from Polymarket
   - computed_at timestamp
5. 🔄 Auto-reclassifying tiers in `wallets_v2`:
   - balance + position_value ≤ 0 → DEAD/LOW_BALANCE
   - $0 < balance+position < $1000 → LOW_BALANCE
   - balance+position ≥ $1000 + never traded → NEW
   - balance+position ≥ $1000 + has traded → STANDARD

## Concurrency Settings
- **Alchemy:** 9 concurrent (3 API keys × 3)
- **Polymarket:** 15 concurrent
- **Database:** Single connection, batch commits

## Estimated Timeline
- **Rate:** 7.8 wallets/second
- **Total:** 14,118 wallets
- **Duration:** ~1,810 seconds = ~30 minutes
- **ETA Completion:** ~00:54 UTC

## Database Tables Being Modified
### `wallet_metrics_v2`
- balance (FLOAT) - On-chain USDC balance
- position_value (FLOAT) - Sum of market positions
- computed_at (TIMESTAMP) - Refresh time

### `wallets_v2`
- tier (VARCHAR) - Auto-reclassified tier
- updated_at (TIMESTAMP) - Update timestamp
- tier_reason (VARCHAR) - 'balance_refresh'

## Monitoring
Check progress with:
```bash
tail -f refresh_session.log
```

Look for lines like:
```
[BATCH N] X/14118 done | fail=Y | Z w/s | elapsed=Ts | ETA=Ts
```

## Completion Expected Output
```
DONE: refreshed 14118/14118 wallets in ~1810s (0 failed)
DB Summary: X wallets with balance > 0, Y with position > 0, Z total tracked
Database connection closed
```

---
**Check back in 25-30 minutes for completion!**
