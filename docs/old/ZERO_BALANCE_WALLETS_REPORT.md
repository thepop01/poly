# Zero Balance Wallets - Fetch Report

**Status:** Script running in background (Task ID: `bfivpz5li`)  
**Started:** 2026-07-19 22:39+  
**Total Wallets to Process:** 14,153

---

## 🔍 Key Findings

### Kalshi Integration Status
**✅ NOT INTEGRATED** - Only Phase 1 stubs exist
- Location: `src/agents/execution.py` 
- KalshiBroker class raises `NotConfiguredError`
- Current scope: **Polymarket ONLY**
- Timeline: T2 priority after agents/strategies/bots complete

### Available Endpoints

#### **V2 Endpoints** (Latest - Production)
| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `GET /api/v2/wallets/{address}/stats` | Wallet balance & metrics | DB-backed, can fetch live |
| `GET /api/v2/wallets/{address}/positions` | Open positions list | Includes market_id, side, size, current_value, unrealized_pnl |
| `GET /api/v2/leaderboard/wallets?tab=all` | List all wallets | Supports filtering, sorting, pagination |
| `GET /api/v2/leaderboard/wallets/counts` | Wallet tier counts | Breakdown: standard, low_balance, new, hibernated |

#### **V1 Endpoints** (Legacy)
- `GET /api/wallets/{address}/stats`
- `GET /api/wallets/{address}/positions`

---

## 📊 What the Script Does

**fetch_zero_balances.py** - Batch refresher for wallets with zero balance/position

### Process Flow:
1. **Query DB** → Find wallets where `balance = 0 OR position_value = 0`
2. **Fetch Balance** → Call Alchemy API for on-chain USDC balance
3. **Fetch Positions** → Call Polymarket Data API for open positions
4. **Calculate Total** → `position_value = SUM(market positions)`
5. **Update DB** → Upsert into `wallet_metrics_v2`
6. **Reclassify Tier** → Auto-tier based on `balance + position_value`:
   - **DEAD** → total ≤ 0, no trades ever
   - **LOW_BALANCE** → total ≤ 0, has traded OR total < $1,000
   - **NEW** → total ≥ $1,000, no trades yet
   - **STANDARD** → total ≥ $1,000, has traded

### Performance:
- **Concurrency:** 
  - Alchemy (balance): 9 concurrent (3 API keys × 3)
  - Polymarket (positions): 15 concurrent
- **Batch Size:** 500 wallets per DB commit
- **Rate:** ~8-12 wallets/second
- **ETA:** ~20-30 minutes for 14,153 wallets

---

## 📋 Schema Reference

### `wallets_v2` table
```
address, username, tier, is_dormant, might_cook_type, 
last_trade_at, added_at, updated_at
```

### `wallet_metrics_v2` table
```
address, balance, position_value, pm_pnl, pm_volume, 
total_pnl, total_volume, roi_pct, win_rate, deposits, 
withdrawals, active_days, biggest_win, biggest_loss, 
computed_at
```

### `wallet_positions_v2` table
```
address, condition_id, outcome, size, avg_price, 
current_value, unrealized_pnl
```

---

## 🚀 Next Steps

Monitor script progress with:
```bash
tail -f zero_balances.log
```

Once complete, script will output:
- ✅ Total wallets refreshed
- ✅ Failed count
- ✅ Final tier distribution
- ✅ Wallets with balance > 0
- ✅ Wallets with position > 0

---

## Sample API Calls

### Get a specific wallet's balance + positions:
```bash
curl http://localhost:8000/api/v2/wallets/0x1234.../stats
curl http://localhost:8000/api/v2/wallets/0x1234.../positions
```

### List all low-balance wallets:
```bash
curl "http://localhost:8000/api/v2/leaderboard/wallets?tab=low_balance&limit=50"
```

### Get wallet tier counts:
```bash
curl http://localhost:8000/api/v2/leaderboard/wallets/counts
```

---

Generated: 2026-07-19 22:40 UTC
