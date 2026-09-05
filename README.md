# Polymarket Analytics Platform

Real-time analytics dashboard for Polymarket — wallet tracking, smart money alerts, and leaderboard rankings powered by on-chain data.

## Repository layout

- `src/` — maintained backend code; `src/scripts/` contains supported operator commands.
- `frontend/` — maintained web application.
- `tests/` — maintained automated test suite.
- `docs/` — design, operating, and investigation documentation; start with [`docs/rule.md`](docs/rule.md) for the worker runbook.
- `logs/` — local runtime logs (never committed).
- `scratch/` — local one-off diagnostics, backtests, exports, reports, and evidence (never committed).
- `backtest_cache/` and `backtest/_cache/` — local cache only (never committed).

Do not place generated logs, one-off scripts, exports, or working investigation notes at the repository root. Put them in the corresponding `logs/` or `scratch/` subdirectory.

## Architecture

```
Polygon Blockchain (Etherscan V2) ──→ trade_tracker.py ──→ smart_money_alerts (LARGE_TRADE)
                                                            smart_money_trades
                                                            wallets_v2 (source 'trade', trade >= $1k)

Polygon Blockchain (Alchemy) ──→ deposit_tracker.py ──→ smart_money_alerts (LARGE_DEPOSIT)
                                                          wallet_activity_v2 (DEPOSIT events)
                                                          wallets_v2 (source 'deposit', deposit >= $5k,
                                                                      might_cook_type badge if 0 trades)

wallets_v2 (tier='UNCLASSIFIED') ──→ wallet_trade_history.py ──→ tier assigned:
                                       DEAD / LOW_BALANCE / NEW / STANDARD (± is_dormant)

wallets_v2 ──→ leaderboard_stats_v2.py ──→ wallet_metrics_v2 + category_stats_v2 (PnL/ROI/windows)
            ──→ stats_refresher.py ──→ balance/deposits/withdrawals/position_value + tier sweep
            ──→ poly_leaderboard_sync.py ──→ leaderboard discovery (source 'leaderboard') + curated promotion

smart_money_alerts ──→ GET /api/v2/alpha-calls/smart-money ──→ Alpha Feed frontend
wallets_v2 + wallet_metrics_v2 ──→ GET /api/v2/leaderboard/* ──→ wallet list pages
```

The v1 tables (`tracked_wallets`, `wallet_stats`) are legacy-read-only — no worker writes them anymore. Dropping them is a follow-up once the frozen v1 API routers are retired.

### Workers (supervised by `orchestrator.py`)

| Worker | Interval | Purpose |
|--------|----------|---------|
| `live_wallet_listener` | Real-time (WS) | **Method B: Mined Block Logs Listener**: Listens to Polygon WebSockets for `Deposit Wallet Factory` and `Gnosis Safe Proxy Factory` creation events (<1.5s latency). Instantly registers new wallets (`tier='NEW'`) appearing directly under "New Wallets" on the wallet page. Uses Envio HyperSync for restart catch-up. |
| `polymarket_trade_backfiller` | Continuous | **Polymarket Data API Trade Backfiller**: Concurrently syncs up to 3,500 trades per wallet at ~2,600+ trades/sec across 8 async workers, writing to `wallet_trades_v2` and updating `curated_trade_sync`. |
| `positions_winrate_backfill` | Continuous | Computes 10 PnL windows (100–5000), Price-bucket win rates (<0.15 to >0.75), Open Positions, and Balances into `wallet_metrics_v2`. |
| `trade_tracker` | 15s | Watches `OrderFilled` events from 3 CTF Exchange contracts via Etherscan V2. Chunked 200-block requests. $1k+ → `smart_money_trades` + auto-add to `wallets_v2` (source `'trade'`), $5k+ → `LARGE_TRADE` alerts |
| `deposit_tracker` | 60s | Watches pUSD mints from zero address via Alchemy. $5k+ → `wallet_activity_v2` + `LARGE_DEPOSIT` alerts, auto-add to `wallets_v2` (source `'deposit'`), `might_cook_type` badge if 0 trades |
| `wallet_trade_history` | 60s | Vets `tier='UNCLASSIFIED'` wallets: fetches positions + balance from Polymarket API, assigns DEAD / LOW_BALANCE / NEW / STANDARD (± dormant). Transient errors leave the wallet queued |
| `leaderboard_stats` (runs `leaderboard_stats_v2`) | 5min | Computes PnL, ROI, win_rate, volume, per-category window stats into `wallet_metrics_v2` / `category_stats_v2`. Full pipeline only for CURATED wallets |
| `stats_refresher` | 10min | Refreshes balance/deposits/withdrawals for stale wallets; runs the tier state machine sweep and dormancy flips both directions |
| `poly_leaderboard_sync` | 7 days | Syncs top 5000 from Polymarket ALL leaderboard + top 2000 SPORTS + top 500 per category (source `'leaderboard'`). Promotes qualified wallets to `tier='CURATED'` |

### API Routes

| Prefix | Purpose |
|--------|---------|
| `/api/v2/leaderboard/wallets` | Canonical tabbed wallet list (`tab=all\|standard\|low_balance\|new\|hibernated`) with source/search/sort/paging |
| `/api/v2/leaderboard/wallets/counts` | Per-tab counts for the tab badges |
| `/api/v2/leaderboard/global` | Active whales (tier != DEAD, bal+pos >= $1k, traded in 30d), sortable, category + source filters |
| `/api/v2/leaderboard/global-wallets` | Alias of `/global` used by the Global List page |
| `/api/v2/leaderboard/might-cook` | Legacy delegate onto `/wallets` tabs (`new_wallets`→new, `zero_balance`→low_balance, `hibernated`) |
| `/api/v2/leaderboard/hibernating` | Legacy delegate onto the hibernated tab |
| `/api/v2/leaderboard/curated` | High-performing wallets (curation criteria) |
| `/api/v2/leaderboard/curated-wallets` | Curated wallets with per-(category, window) stats |
| `/api/v2/leaderboard/category-curated` | Wallets curated for specific category/subcategory |
| `/api/v2/leaderboard/subcategories` | Distinct subcategories for filter dropdowns |
| `/api/v2/alpha-calls/smart-money` | LARGE_DEPOSIT + LARGE_TRADE alert feed |
| `/api/v2/wallets/{address}/*` | Wallet detail: stats, trades, positions, closed-positions, pnl-chart, deposits |
| `/api/v2/wallets/tracked` | All tracked wallets with stats |
| `/api/v2/wallets/custom` | POST bulk-add custom wallets (tier CURATED, source `'custom'`) |
| `/api/watchlist` | User watchlist CRUD |
| `/api/tracker` | New markets, smart money trades, whale trades |
| `/api/auth` | JWT signup/login |
| `/api/ws` | WebSocket real-time prices/trades |
| `/api/search` | Wallet address search |
| `/api/trades` | Global trade feed |

Legacy v1 routers (`/api/leaderboard`, `/api/tracked`, `/api/wallets`) remain mounted but frozen; they read the legacy v1 tables.

### Frontend

| Page | Route |
|------|-------|
| Activity (Alpha Feed) | `/alpha-calls` |
| Wallets | `/wallets` (home page redirect) — tabs: All / Standard / Low Balance / New / Hibernated, source filter pills, Might Cook badge on the New tab |
| Curated | `/wallets/curated` |
| Custom Wallets | `/wallets/custom` |
| Wallet Profile | `/wallet/[address]` |
| My Tracker | `/tracker` |
| Wallet Tracker | `/tools/wallet-tracker` |

Retired routes: `/might-cook` and `/wallets/hibernating` (deleted — their content lives in the `/wallets` tabs); `/wallets/global` redirects to `/wallets?tab=standard`.

## Database

Key tables (managed by Alembic):

- `wallets_v2` — canonical wallet registry: `tier` (UNCLASSIFIED / DEAD / LOW_BALANCE / NEW / STANDARD / CURATED), `is_dormant`, `might_cook_type` badge, `last_trade_at`
- `wallet_sources_v2` — discovery sources per wallet, PK `(address, source)`: `trade` / `deposit` / `leaderboard` / `custom`
- `wallet_metrics_v2` — balance, deposits, withdrawals, position value, PnL/volume/ROI, Polymarket headline numbers
- `wallet_activity_v2` — deposit/withdrawal events (FK → `wallets_v2`)
- `category_stats_v2` — per-(category, window) PnL/volume stats
- `smart_money_alerts` — unified LARGE_DEPOSIT + LARGE_TRADE alert feed
- `smart_money_trades` — individual wallet trades from OrderFilled events (>= $1k)
- `wallet_tags` — per-wallet category/subcategory classification
- `wallet_category_stats` — per-category PnL/volume/win_rate
- `wallet_closed_positions` — persisted resolved positions (deduped by condition_id)
- `global_wallet_trades` — stored trades for curated wallets
- `curated_category_tags` — curated wallets with category/subcategory tags
- `user_watchlists` — per-user wallet tracking
- `events`, `markets`, `trades` — core market data
- `users`, `refresh_tokens` — auth
- `tracked_wallets`, `wallet_stats` — **legacy v1, read-only** (pending drop)

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
python -m src.orchestrator    # Supervises all 6 workers with crash recovery
```

Or run individual workers:

```bash
python -m src.workers.trade_tracker
python -m src.workers.deposit_tracker
python -m src.workers.wallet_trade_history
python -m src.workers.leaderboard_stats_v2
python -m src.workers.stats_refresher
python -m src.workers.poly_leaderboard_sync
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
- `ALCHEMY_API_KEY_1`…`ALCHEMY_API_KEY_3` — Alchemy (for balance/deposits, 3 keys with rotation)
- `NEXT_PUBLIC_API_URL` — Backend URL for frontend

## Key Design Decisions

### Deposit Detection
- **Signal**: pUSD mints from zero address (`0x000...000`) to user wallets — NOT `CollateralOnramp` transfers
- **Token**: pUSD (`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`) — Polymarket's current collateral (post April 28, 2026 CLOB V2 migration)
- **Filter**: `SYSTEM_RECIPIENTS` excludes exchange contracts (`0xe1118...`, `0xe2222d...`, `0xe33337...`, pUSD contract) from deposit count
- **Persistence**: `.deposit_last_block` avoids full history scan on restart; initializes from `latest - 10,000` blocks

### Trade Detection
- **Source**: Raw `OrderFilled` events from 3 CTF Exchange contracts via Etherscan V2 — no REST API record cap
- **Chunking**: 200 blocks per Etherscan request (avoids timeouts on large ranges)
- **Metadata**: Every trade fetches market title, category, and subcategory from Gamma API (cached per token ID, 10k entry LRU)
- **12-hour rolling window**: Accumulates per-wallet per-market volume to detect slow limit-order accumulations

### Balance Checks
- All balance queries use `PUSD_CONTRACT` (not native USDC or USDC.e) since Polymarket wallets hold pUSD post-migration

### PnL Calculation
- **Source**: Polymarket leaderboard headline (`/v1/leaderboard?user={addr}&category=OVERALL&timePeriod=ALL`)
- **Fallback**: When wallet is not on any leaderboard, uses computed PnL from balance changes
- **Stored as**: `total_pnl` (computed) and `pm_pnl` (Polymarket headline) in `wallet_metrics_v2`

### Wallet Qualification
- **Auto-add (deposit)**: pUSD mint >= $5,000 → `wallets_v2` (source `'deposit'`)
- **Auto-add (trade)**: OrderFilled trade >= $1,000 → `wallets_v2` (source `'trade'`)
- **Vetting**: `wallet_trade_history` assigns tier — DEAD (bal+pos <= 0), LOW_BALANCE (< $1k), NEW (>= $1k, never traded), STANDARD (>= $1k, traded) ± dormant
- **Curated**: not dormant AND (ROI > 30% OR balance > $5k OR PnL > $10k) → `tier='CURATED'`; never auto-demoted
- **Might Cook**: Deposit >= $5,000 AND 0 trades → `might_cook_type` badge (not a tier)

### Worker Supervision
- `orchestrator.py` auto-restarts crashed workers with exponential backoff (1s → 60s max)
- Graceful shutdown via SIGINT/SIGTERM with 10s wind-down

## Contract Addresses (Polygon)

| Contract | Address | Purpose |
|----------|---------|---------|
| pUSD | `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` | Current Polymarket deposit token |
| USDC.e | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | Pre-April 2026 collateral (now only for swaps) |
| Native USDC | `0x3c499c542cef6e924e22cab0d4c1ccec5e48cb12` | NOT used by Polymarket for deposits |
| CTF Exchange V2 | `0xE111180000d2663C0091e4f400237545B87B996B` | Trade monitoring |
| Neg Risk CTF Exchange | `0xe2222d279d744050d28e00520010520000310f59` | Trade monitoring |
| CTF Exchange V3 | `0xe3333700ca9d93003f00f0f71f8515005f6c00aa` | Trade monitoring |

## Thresholds

| Threshold | Value | Context |
|-----------|-------|---------|
| Large deposit alert | >= $5,000 | `deposit_tracker.py` |
| Might Cook deposit | >= $5,000 | `deposit_tracker.py` (0 trades → alert) |
| Large trade alert | >= $5,000 | `trade_tracker.py` |
| Smart money trade | >= $1,000 | `trade_tracker.py` (inserts to `smart_money_trades`) |
| Wallet auto-add (deposit) | >= $5,000 | `deposit_tracker.py` |
| Wallet auto-add (trade) | >= $1,000 | `trade_tracker.py` |
| Curated promotion | ROI > 30% OR bal > $5k OR PnL > $10k, not dormant | `poly_leaderboard_sync.py` (weekly) |
| Might Cook badge | Deposit >= $5k AND 0 trades | `deposit_tracker.py` sets `might_cook_type` |
