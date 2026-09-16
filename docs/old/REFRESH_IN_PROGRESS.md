# Zero Balance Wallets - Full Database Refresh

## Status: IN PROGRESS ⏳

### What's Running
```
fetch_zero_balances.py - Full batch refresh of all 14,153 wallets
```

### Process
1. ✅ Found 14,153 wallets with zero balance OR zero position
2. 🔄 Currently fetching live data:
   - Balance: On-chain USDC from Alchemy API (9 concurrent)
   - Positions: Open positions from Polymarket API (15 concurrent)
3. ⏳ Batch processing: 500 wallets per database commit
4. 📊 Reclassifying tiers based on fresh data

### Performance
- **Rate:** ~8-12 wallets/second
- **Total Wallets:** 14,153
- **Estimated Duration:** 20-30 minutes
- **ETA:** Completion around 00:15-00:30 UTC

### What It Updates
1. `wallet_metrics_v2.balance` - Current USDC balance
2. `wallet_metrics_v2.position_value` - Sum of all position values
3. `wallet_metrics_v2.computed_at` - Refresh timestamp
4. `wallets_v2.tier` - Auto-reclassified tier:
   - **DEAD** → total ≤ 0, no trades ever
   - **LOW_BALANCE** → total ≤ 0, has traded OR total < $1,000
   - **NEW** → total ≥ $1,000, no trades yet
   - **STANDARD** → total ≥ $1,000, has traded

### Monitor Progress
```bash
# Real-time log
tail -f zero_balances_full.log

# Current status
tail -20 zero_balances_full.log
```

### Expected Output When Complete
```
DONE: refreshed 14153/14153 wallets in [TIME]s ([FAILED] failed)
Final: X wallets with balance > 0, Y with position > 0
```

---

## Database Impact

### Tables Modified
- `wallet_metrics_v2` - Balance and position values updated
- `wallets_v2` - Tier and updated_at timestamps

### No Data Loss
- Old data preserved in `*_at` timestamp columns
- Computed timestamps show refresh time
- All trades/history remain intact

---

## API Data Sources

### Balance Data
- **Source:** Alchemy API
- **Contract:** USDC (Polygon)
- **Keys:** 3 concurrent (9 parallel limit)
- **Field:** `tokenBalance` (in wei, converted to USDC)

### Position Data
- **Source:** Polymarket Data API
- **Endpoint:** `https://data-api.polymarket.com/positions`
- **Concurrency:** 15 concurrent requests
- **Fields:** currentValue, conditionId, outcome, size, avgPrice

---

## Troubleshooting

If script hangs:
1. Check rate limits from Alchemy/Polymarket
2. Verify database connection
3. Review error logs in `zero_balances_full.log`

If database transaction fails:
- Script continues with next batch
- Failed wallets logged as failures
- Can re-run to retry failed addresses

---

**Check back in 25-30 minutes for completion status!**
