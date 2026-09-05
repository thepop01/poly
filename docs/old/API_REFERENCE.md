# API Reference

> Complete reference of all API endpoints in the Polymarket tracker backend.
>
> The frontend uses the **v2** routers (`/api/v2/...`), which read the v2 schema (`wallets_v2`, `wallet_sources_v2`, `wallet_metrics_v2`). The unprefixed v1 routers (`/api/leaderboard`, `/api/tracked`, `/api/wallets`) are frozen legacy readers of the v1 tables and will be retired.

---

## Table of Contents

1. [Auth](#auth)
2. [Leaderboard](#leaderboard)
3. [Tracked Wallets](#tracked-wallets)
4. [Wallet Detail](#wallet-detail)
5. [Alpha Calls](#alpha-calls)
6. [Tracker](#tracker)
7. [Trades](#trades)
8. [Watchlist](#watchlist)
9. [Search](#search)
10. [Discord](#discord)
11. [WebSocket](#websocket)

---

## Auth (3 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup` | POST | User registration (email + password) |
| `/api/auth/login` | POST | User login, returns JWT |
| `/api/auth/refresh` | POST | Refresh expired JWT token |

---

## Leaderboard v2 (10 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/leaderboard/wallets` | GET | **Canonical tabbed list** driving the `/wallets` page. Params: `tab` (`all`/`standard`/`low_balance`/`new`/`hibernated`), `source` (`trade`/`deposit`/`leaderboard`/`custom`), `search`, `sort_by` (`pnl`/`volume`/`roi`/`balance`/`position_value`/`deposits`/`last_trade_at`/`added_at`), `sort_order`, `limit` (≤200), `offset`. Returns `sources[]` and `might_cook_type` per row |
| `/api/v2/leaderboard/wallets/counts` | GET | Per-tab counts (`all`, `standard`, `low_balance`, `new`, `hibernated`) for tab badges, 60s cache |
| `/api/v2/leaderboard/global` | GET | Active whales (tier != DEAD, bal+pos >= $1k, traded in 30d). Params: `category`, `sort_by`, `sort_order`, `search`, `source_type`, `limit`, `offset` |
| `/api/v2/leaderboard/global-wallets` | GET | Alias of `/global` (`source` param maps to `source_type`) |
| `/api/v2/leaderboard/might-cook` | GET | Legacy delegate onto `/wallets`: `tab=new_wallets`→`new`, `zero_balance`→`low_balance`, `hibernated`→`hibernated`. Legacy response shape |
| `/api/v2/leaderboard/hibernating` | GET | Legacy delegate onto the `hibernated` tab, oldest trade first |
| `/api/v2/leaderboard/curated` | GET | Curated wallet leaderboard with trade window filter |
| `/api/v2/leaderboard/curated-wallets` | GET | Curated list with per-(category, window) stats. Params: `window`, `category` |
| `/api/v2/leaderboard/category-curated` | GET | Category-specific curated wallets |
| `/api/v2/leaderboard/subcategories` | GET | Distinct subcategories for a given category |

Legacy v1 equivalents live at `/api/leaderboard/*` (frozen).

---

## Tracked Wallets v2 (4 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/wallets/tracked` | GET | List all tracked wallets (tier != DEAD). Params: `source`, `min_win_rate`, `min_volume`, `min_trade_size`, sort/paging |
| `/api/v2/wallets/tracked/count` | GET | Count of tracked wallets |
| `/api/v2/wallets/queue/{address}` | POST | Add wallet to discovery queue (inserts `tier='UNCLASSIFIED'`) |
| `/api/v2/wallets/custom` | POST | Bulk-add custom wallets. Body: `{"wallets": [{"address", "reason"}]}` — validates `0x` + 40 hex chars, sets `tier='CURATED'` + source `'custom'` |

---

## Wallet Detail v2 (9 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/wallets/{address}/stats` | GET | Full wallet stats (PnL, ROI, volume) |
| `/api/v2/wallets/{address}/trades` | GET | Proxied to Polymarket `/trades` API |
| `/api/v2/wallets/{address}/positions` | GET | Proxied to Polymarket `/positions` API |
| `/api/v2/wallets/{address}/closed-positions` | GET | Proxied to Polymarket `/closed-positions` API |
| `/api/v2/wallets/{address}/pnl-chart` | GET | PnL chart data from closed-positions |
| `/api/v2/wallets/{address}/deposits` | GET | Deposit history for wallet |
| `/api/v2/wallets/whales` | GET | List of whale wallets (volume >= $5k) |
| `/api/v2/wallets/deposit-alerts/recent` | GET | Recent large deposit alerts |
| `/api/v2/wallets/smart-money-trades` | GET | Smart money trade feed |

---

## Alpha Calls (1 endpoint)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/alpha-calls/smart-money` | GET | Unified feed of large deposits + large trades. Params: `alert_type`, `tier`, `category`, `subcategory`, `limit`, `offset` |

---

## Tracker (9 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tracker/new-markets` | GET | Newly created markets |
| `/api/tracker/smart-money` | GET | Smart money tracker |
| `/api/tracker/whales` | GET | Whale tracker (trades >= $5k) |
| `/api/tracker/lists` | GET | Get all tracker lists |
| `/api/tracker/lists` | POST | Create a new tracker list |
| `/api/tracker/lists/{list_id}` | DELETE | Delete a tracker list |
| `/api/tracker/lists/{list_id}/wallets` | GET | Get wallets in a list |
| `/api/tracker/lists/{list_id}/wallets` | POST | Add wallet to a list |
| `/api/tracker/lists/{list_id}/wallets/{wallet_address}` | DELETE | Remove wallet from a list |

---

## Trades (2 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/trades` | GET | All trades from DB with filters |
| `/api/trades/export` | GET | Export trades as CSV |

---

## Watchlist (4 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/watchlist` | GET | Get user's watchlist |
| `/api/watchlist/{address}` | POST | Add wallet to watchlist |
| `/api/watchlist/{address}` | DELETE | Remove wallet from watchlist |
| `/api/watchlist/{address}/alerts` | POST | Create alert for wallet |

---

## Search (1 endpoint)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search` | GET | Search wallets and markets |

---

## Discord (2 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/discord/login` | GET | Initiate Discord OAuth |
| `/api/discord/callback` | GET | Discord OAuth callback |

---

## WebSocket (1 endpoint)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ws` | WS | Live updates: new trades, whale alerts, wallet changes |

---

## Summary

| Router | Endpoints |
|--------|-----------|
| Auth | 3 |
| Leaderboard v2 | 10 |
| Tracked Wallets v2 | 4 |
| Wallet Detail v2 | 9 |
| Alpha Calls | 1 |
| Tracker | 9 |
| Trades | 2 |
| Watchlist | 4 |
| Search | 1 |
| Discord | 2 |
| WebSocket | 1 |
| **Total** | **46** (plus frozen v1 legacy routers) |

---