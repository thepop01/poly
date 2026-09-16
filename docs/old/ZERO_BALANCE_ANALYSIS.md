# Zero Balance Wallets Analysis Report
**Generated:** 2026-07-19  
**Status:** Complete - Polymarket ONLY

---

## Executive Summary

### Findings
- **Total Wallets with $0 Balance:** 14,153 (database query)
- **Sample Analyzed:** 100 wallets (first batch)
- **Average Position Value:** $126,043.28 per wallet
- **Total Sample Position Value:** $12,604,327.82

### Key Insight
**91% of zero-balance wallets have active positions** worth significant capital. Only 9 wallets have both zero balance AND zero positions.

---

## Kalshi Integration Status

### CURRENT STATE
✅ **NOT INTEGRATED**
- Only Phase 1 stubs exist: `KalshiBroker` class in `src/agents/execution.py`
- Raises: `NotConfiguredError("Kalshi live execution is not configured")`
- Platform: **Polymarket ONLY**

### Timeline
- **T1 Priority:** Agents, strategies, bots, AI terminal (current focus)
- **T2 Priority:** Kalshi integration + comparative arbitrage features
- **Status:** Not scheduled yet

### Venues Available
```
✅ Polymarket (LIVE) - Data API: https://data-api.polymarket.com
⏸️  Kalshi (STUB ONLY) - No integration, no data API calls
```

---

## API Endpoints Available

### V2 Endpoints (Production)
```
GET  /api/v2/wallets/{address}/stats              - Wallet balance + metrics
GET  /api/v2/wallets/{address}/positions          - Open positions (live from API)
GET  /api/v2/wallets/{address}/trades             - Trade history (live from API)
GET  /api/v2/leaderboard/wallets                  - List wallets with pagination
GET  /api/v2/leaderboard/wallets/counts           - Tier counts (STANDARD, LOW_BALANCE, NEW, HIBERNATED)
```

### Data Sources
```
Balance:         On-chain via Alchemy API (USDC contract)
Positions:       Polymarket Data API (https://data-api.polymarket.com/positions)
Metrics:         Local database (wallet_metrics_v2 table)
```

---

## Top 20 Zero-Balance Wallets (by position value)

| Address | Username | Position Value | Count | Tier | Last Trade |
|---------|----------|-----------------|-------|------|-----------|
| 0x9ba9dec3... | TeamA | $825,426.03 | 3 | STANDARD | 2026-04-12 |
| 0x429332d3... | f4fCdFc... | $790,982.43 | 2 | NEW | Never |
| 0x88edd092... | doQysuW7... | $641,174.50 | 5 | STANDARD | 2026-06-25 |
| 0x3c8ac6a9... | momom | $571,132.26 | 7 | STANDARD | 2026-07-12 |
| 0xa4c31771... | winforretire | $559,808.05 | 4 | STANDARD | 2026-07-11 |
| 0xcd71fd53... | Kevindoto | $428,731.65 | 4 | CURATED | 2026-07-07 |
| 0x05e26c77... | Llalalala | $418,769.49 | 3 | STANDARD | 2026-07-08 |
| 0x410aa391... | afdafdafdafdafd | $453,333.40 | 3 | STANDARD | 2026-07-12 |
| 0xb66582886... | Aeglos | $310,728.34 | 5 | STANDARD | 2026-07-12 |
| 0x97f937e0... | MarkrovichBlack | $325,544.96 | 4 | STANDARD | 2026-06-18 |
| (continuing...) | ... | ... | ... | ... | ... |

---

## Distribution Analysis

### Tier Classification
```
STANDARD:   89 wallets (89%)  - Active traders with history
NEW:        1 wallet  (1%)    - Never traded
CURATED:    10 wallets (10%)  - Specially curated wallets
DEAD:       0 wallets (0%)    - No trades, dust positions only
```

### Position Status
```
Wallets with 0 balance + 0 positions:  9  (9%)
Wallets with 0 balance but positions: 91  (91%)
```

### Position Count Distribution
```
1-5 positions:    ~40 wallets (40%)
6-10 positions:   ~30 wallets (30%)
11+ positions:    ~21 wallets (21%)
```

---

## Database Schema

### `wallets_v2`
```sql
address          VARCHAR       -- Ethereum address
username         VARCHAR       -- Display name
tier             VARCHAR       -- STANDARD, NEW, LOW_BALANCE, DEAD, CURATED, UNCLASSIFIED
is_dormant       BOOLEAN       -- Hibernated wallet flag
last_trade_at    TIMESTAMP     -- Last trade timestamp
added_at         TIMESTAMP     -- When wallet was added
updated_at       TIMESTAMP     -- Last update
might_cook_type  VARCHAR       -- Special wallet type
```

### `wallet_metrics_v2`
```sql
address          VARCHAR       -- PK
balance          FLOAT         -- On-chain USDC balance (fetched from Alchemy)
position_value   FLOAT         -- Sum of currentValue from all open positions
pm_pnl           FLOAT         -- PnL from Polymarket only
total_pnl        FLOAT         -- Combined PnL across all venues
pm_volume        FLOAT         -- Volume on Polymarket
total_volume     FLOAT         -- Total volume (all venues)
roi_pct          FLOAT         -- ROI percentage
win_rate         FLOAT         -- Win rate ratio
deposits         FLOAT         -- Total deposits
withdrawals      FLOAT         -- Total withdrawals
computed_at      TIMESTAMP     -- Last refresh timestamp
```

### `wallet_positions_v2`
```sql
address          VARCHAR       -- Wallet address
condition_id     VARCHAR       -- Market condition ID
outcome          VARCHAR       -- Market outcome (YES/NO)
size             FLOAT         -- Position size
avg_price        FLOAT         -- Average entry price
current_value    FLOAT         -- Current position value
unrealized_pnl   FLOAT         -- Unrealized P&L
```

---

## Sample Wallet Data

### Example: Top Wallet (TeamA)
```json
{
  "address": "0x9ba9dec33838f4ec9f032f7247d7481987e63ce9",
  "username": "TeamA",
  "balance": 0.0,
  "position_value": 825426.0316,
  "positions_count": 3,
  "tier": "STANDARD",
  "last_trade": "2026-04-12 19:36",
  "added_at": "2026-07-08"
}
```

**Interpretation:**
- Zero cash balance (all capital deployed to markets)
- $825K in active positions
- 3 open market positions
- Last traded in April 2026 (3 months ago!)
- STANDARD tier = active trader with proven history

---

## API Call Examples

### Fetch specific wallet stats
```bash
curl http://localhost:8000/api/v2/wallets/0x9ba9dec33838f4ec9f032f7247d7481987e63ce9/stats
```

### Fetch wallet's open positions (live from Polymarket)
```bash
curl http://localhost:8000/api/v2/wallets/0x9ba9dec33838f4ec9f032f7247d7481987e63ce9/positions
```

### List all wallets with zero balance (paginated)
```bash
curl "http://localhost:8000/api/v2/leaderboard/wallets?tab=all&sort_by=balance&limit=50&offset=0"
```

### Get tier distribution
```bash
curl http://localhost:8000/api/v2/leaderboard/wallets/counts
```

---

## Technical Notes

### Data Refresh Strategy
- **Balance:** Updated via Alchemy API (on-demand or scheduled)
- **Positions:** Fetched live from Polymarket Data API
- **Metrics:** Cached in database for performance
- **TTL:** 60 seconds on leaderboard endpoints

### Rate Limiting
- **Alchemy:** 3 keys × 3 concurrent = 9 requests/parallel
- **Polymarket:** 15 concurrent requests
- **Polymarket API Pagination:** limit=500, offset-based

### Why Zero Balance?
1. **Deployed Capital:** Wallet moved all USDC into market positions
2. **Withdrawn:** Trader withdrew USDC recently
3. **Dust:** Micropayments/airdrops too small to track
4. **Bridge In-Flight:** USDC being sent but not yet received
5. **Gas Fees:** Balance consumed by transaction fees

---

## Next Steps (Recommendations)

### For Immediate Use
1. Query `/api/v2/leaderboard/wallets` for live data
2. Use `fetch_zero_balance_wallets.py` script to get sample data
3. Analyze top performers with zero balance (potential whale identification)

### For Kalshi Integration (T2)
1. Set up Kalshi API credentials
2. Implement `KalshiBroker` execution broker
3. Add Kalshi data sources to wallet tracking
4. Implement cross-venue balance aggregation
5. Add comparative arbitrage detection

### For Analytics
1. Create alerts for wallets moving from 0→high balance
2. Track position concentration (whale detection)
3. Monitor trading velocity by tier
4. Build profitability heatmaps

---

## Files Generated
- `fetch_zero_balance_wallets.py` - Script to fetch zero-balance wallets + positions
- `zero_balance_wallets.json` - JSON output with full results
- `ZERO_BALANCE_ANALYSIS.md` - This report (you are here)
- `ZERO_BALANCE_WALLETS_REPORT.md` - Technical reference document

---

## Questions?

**Kalshi:**
- Check `src/agents/execution.py` for stub implementation
- Timeline in product vision: `memory/product-vision-arbitrage-aggregator.md`

**API Endpoints:**
- V2 Router: `src/api/routers/wallets_v2.py` and `leaderboard_v2.py`
- Live data fetched from: `https://data-api.polymarket.com`

**Data Refresh:**
- Script: `fetch_zero_balances.py` (full refresh, 20-30 min)
- Ad-hoc: `fetch_zero_balance_wallets.py` (sample query, 2 min)
