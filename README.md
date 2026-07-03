# Polymarket Analytics Platform

A real-time analytics dashboard for Polymarket traders — wallet tracking, smart money alerts, and leaderboard rankings powered by on-chain data.

## Architecture

```
Polygon Blockchain (Etherscan V2) ──→ whale_watcher.py ──→ smart_money_alerts (LARGE_TRADE)
                                                           smart_money_trades
                                                           wallet_discovery_queue

Polygon Blockchain (Alchemy) ──→ global_discovery.py ──→ wallet_discovery_queue
                                                          smart_money_alerts (LARGE_DEPOSIT)

wallet_discovery_queue ──→ wallet_discovery.py ──→ tracked_wallets (promoted)

tracked_wallets ──→ leaderboard_stats.py ──→ wallet_stats (fresh-start PnL/ROI/volume)
                ──→ stats_refresher.py ──→ balance/deposits/withdrawals/position_value

smart_money_alerts ──→ GET /api/alpha-calls/smart-money ──→ Alpha Feed frontend
wallet_stats ──→ GET /api/leaderboard ──→ Leaderboard frontend
```

### Workers (supervised by `orchestrator.py`)

| Worker | Interval | Purpose |
|--------|----------|---------|
| `whale_watcher` | 15s | Raw OrderFilled events from Etherscan V2 → $1k+ → discovery queue, $5k+ → LARGE_TRADE alerts |
| `deposit_watcher` | 30min | Monitor tracked wallets for large deposits → Discord alerts |
| `wallet_discovery` | 60s | Evaluate queued wallets, promote to tracked_wallets ($10k balance/positions) |
| `leaderboard_stats` | 5min | Post-addition PnL/ROI/win_rate from balance deltas + trades |
| `global_discovery` | 60s | On-chain pUSD deposit scanning (≥$10k) via Alchemy |
| `stats_refresher` | 10min | Refresh balance/deposits/withdrawals for stale tracked wallets |

### API Routes

| Prefix | Purpose |
|--------|---------|
| `/api/leaderboard` | Ranked wallets with 16 sortable stat columns |
| `/api/alpha-calls/smart-money` | LARGE_DEPOSIT + LARGE_TRADE alert feed |
| `/api/wallet/{address}/*` | Wallet profile: trades, positions, closed positions, PnL chart |
| `/api/watchlist` | User watchlist CRUD |
| `/api/tracker` | New markets, smart money trades, whale trades |
| `/api/auth` | JWT signup/login |
| `/api/ws` | WebSocket real-time prices/trades |
| `/api/search` | Wallet address search |
| `/api/trades` | Global trade feed |

### Frontend

| Page | Route |
|------|-------|
| Leaderboard | `/leaderboard` (home page) |
| Alpha Feed | `/alpha-calls` |
| Wallet Profile | `/wallet/[address]` |
| Wallet Tracker | `/tools/wallet-tracker` |

## Database

Key tables (managed by Alembic, 24 migrations):

- `smart_money_alerts` — unified LARGE_DEPOSIT + LARGE_TRADE alert feed
- `smart_money_trades` — individual wallet trades from OrderFilled events
- `wallet_discovery_queue` — wallets awaiting evaluation
- `tracked_wallets` — promoted wallets with financials and baselines
- `wallet_stats` — aggregated performance metrics for leaderboard
- `wallet_txn_windows` — precomputed last-N-trade window stats
- `wallet_deposits` — deposit history with cumulative alert flagging
- `user_watchlists` — per-user wallet tracking
- `events`, `markets`, `trades` — core market data
- `users`, `refresh_tokens` — auth

## Quick Start

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Node.js 18+ (for frontend)
- `uv` package manager

### Setup

```bash
cd poly
uv sync
cd frontend && npm install && cd ..
```

### Start services

```bash
docker-compose up -d          # PostgreSQL + Redis
alembic upgrade head          # Run migrations
uvicorn src.api.main:app --reload  # Backend API (port 8000)
cd frontend && npm run dev    # Frontend (port 3000)
```

### Start workers

```bash
python src/orchestrator.py    # Supervises all 6 workers with crash recovery
```

Or run individual workers:

```bash
python -m src.workers.whale_watcher
python -m src.workers.wallet_discovery
python -m src.workers.leaderboard_stats
python -m src.workers.global_discovery
python -m src.workers.stats_refresher
python -m src.workers.deposit_watcher
```

### Running tests

```bash
pytest tests/ -v
```

### Database migrations

```bash
alembic revision -m "description"   # Create
alembic upgrade head                # Apply
alembic downgrade -1                # Rollback
```

## Environment

Copy `.env.example` to `.env` and configure:

- `DATABASE_URL` — PostgreSQL connection
- `JWT_SECRET` — Session signing key
- `ETHERSCAN_API_KEY` — Etherscan V2 API (for OrderFilled event scanning)
- `ALCHEMY_API_KEY` / `ALCHEMY_API_KEY_1`… — Alchemy (for balance/deposits)
- `NEXT_PUBLIC_API_URL` — Backend URL for frontend

## Key Design Decisions

- **Trade discovery is on-chain** — reads raw `OrderFilled` events from CTF Exchange V2 via Etherscan V2. No REST API record cap (3,500). 100% gapless coverage.
- **PnL is fresh-start** — stats begin from the moment a wallet is added to the leaderboard (`start_stats_at`, `start_balance`). No historical backfill.
- **PnL formula**: `(balance − start_balance) + (withdrawals − start_withdrawals) − (deposits − start_deposits) + unrealized_pnl`
- **Unrealized PnL** from open positions via Polymarket Data API `currentValue` + `cashPnl`
- **All leaderboard columns are sortable** — 16 stat columns with server-side sorting
- **Workers are supervised** — `orchestrator.py` auto-restarts with exponential backoff
- **Whale watcher persists last block** to `.whale_last_block` for crash recovery, with dynamic `eth_blockNumber` fallback
