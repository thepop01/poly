# Architecture & Workers

This document outlines the PolyTracker architecture and background worker ecosystem.

## System Architecture

1. **Backend**: FastAPI with asyncpg (PostgreSQL).
2. **Frontend**: Next.js 16 (App Router) with TailwindCSS.
3. **Database**: PostgreSQL (managed via Alembic).
4. **Data Sources**: Polymarket API (Leaderboard, Positions, Trades) and Alchemy (Polygon RPC).

### Data Flow Pipeline

```text
Trade > $5k ─────────────┐
                         │
Deposit > $5k ───────────┼──────────────► Alpha Calls / Activity
                         │                  ├─ Smart Money Trades
                         │                  └─ Large Deposits
                         │
                         ├──► Store Metrics
                         │      • Balance
                         │      • PnL
                         │      • ROI
                         │      • Positions
                         │
                         ├──► Might Cook Wallets
                         │        │
                         │        ├──► New Wallets (0 trades, Bal > $1k)
                         │        ├──► Low Balance (Bal < $1k)
                         │        └─► Hibernated (Inactive > 30 days)
                         │
                         ▼
                 Global Wallets ◄──────────── Polymarket Leaderboards
                         ▲                         • Top 5000 All-Time
                         │                         • Category Specific
                         │
                  Trade + Deposit
                         │
                         ▼
                 Apply Curation Logic
                 (ROI > 30% OR Bal > $5k OR PnL > $10k)
                         │
                         ▼
                   Curated Wallets
```

## Background Workers

All workers write to the v2 schema (`wallets_v2`, `wallet_sources_v2`, `wallet_metrics_v2`, `wallet_activity_v2`, `category_stats_v2`, `wallet_lineage_trades_v2`). The v1 tables (`tracked_wallets`, `wallet_stats`) are legacy-read-only.

### Master Orchestrator Fleet (`src/orchestrator.py` — 14 Supervised Workers)

| # | Worker Script | Role & Responsibilities |
|---|---------------|-------------------------|
| 1 | `positions_open_backfill.py` | **Open Positions & Portfolio Syncer**: Ingests active open positions, calculates marked-to-market unrealized PnL (`current_value - cost_basis`), maps redeemable (concluded) positions to `wallet_closed_positions_v2`, and prunes stale open positions. |
| 2 | `positions_closed_backfill.py` | **Closed Positions Incremental Fetcher**: High-speed incremental fetcher pulling CLOB trade settlements into `wallet_closed_positions_v2`. |
| 3 | `positions_metrics_compute.py` | **Offline Win Rate & Metrics Computer**: High-concurrency worker (80+ workers) rolling up per-market paired win rates (`by_condition`), 10 progression windows (`pnl_100`..`pnl_5000`), price buckets, and category stats with macro anchor to `pm_pnl`. |
| 4 | `poly_leaderboard_sync.py` | **Leaderboard Discovery Sync**: Syncs top 5,000 wallets from official Polymarket leaderboard; discovers new wallets and auto-promotes to curated tier. |
| 5 | `stats_refresher.py` | **Active Wallet Stats Refresher**: 12-hour staleness sweep across active wallets; maintains balance, position value, and the wallet tier state machine. |
| 6 | `trade_tracker.py` | **Real-Time Trade Stream**: Polls Polygon EVM `OrderFilled` logs every 15s; writes to `wallet_activity_v2` and triggers alpha calls. |
| 7 | `redemption_tracker.py` | **Real-Time Redemption Tracker**: Monitors payout redemption events on-chain. |
| 8 | `deposit_tracker.py` | **Whale Deposit Tracker**: Polls on-ramp pUSD mints every 60s and tags the "Might Cook" badge for $5k+ depositors. |
| 9 | `wallet_trade_history.py` | **Wallet Discovery Vetter**: Vets the `UNCLASSIFIED` discovery queue every 60s into real tiers (STANDARD, LOW_BALANCE, NEW, etc.). |
| 10 | `last_trade_sweeper.py` | **Last Trade Sweeper**: Sweeps recent trading timestamps across wallets to maintain accurate dormancy status. |
| 11 | `live_wallet_listener.py` | **Live Wallet Creation Listener**: Listens to Polygon WebSockets for Proxy Factory wallet creation events (<1.5s latency). |
| 12 | `polymarket_trade_backfiller.py` | **Polymarket Trade Backfiller**: Enforces trade retention caps to `wallet_trades_v2` (non-lineage) and `wallet_lineage_trades_v2` (lineage). |
| 13 | `position_and_funding_tracker.py` | **P2P Transfer & Internal Funding Tracker**: Tracks ERC-1155 position transfers and USDC wallet-to-wallet funding. |
| 14 | `onchain_verifier.py` | **On-Chain Verifier**: Cross-checks $0 volume / 0 position candidate wallets against Polygonscan on-chain logs. |

### Decoupled Modular Metrics Computation Pipeline (2026-08-31)
The metrics computation layer is modularized into 3 dedicated standalone workers with individual CLI controls and dedicated concurrency profiles:
- **Worker A (`src/workers/compute_core_metrics.py`)**: Computes per-market paired win rates (`by_condition`), resolved/winning counts, 6 price-bucket matrices (<15c .. >75c), parlay stats, total volume, and anchors `total_pnl` to `pm_pnl` with **250 concurrency** into `wallet_metrics_v2`.
- **Worker B (`src/workers/compute_category_stats.py`)**: Computes multi-tier hierarchical category, subcategory, and competition league returns with proportional PnL scaling so that $\sum \text{Root Categories} \equiv \text{Total PnL}$ (`Delta = $0.00`) into `category_stats_v2`.
- **Worker C (`src/workers/compute_historical_windows.py`)**: Computes the 10 rolling trade progression windows (`pnl_100`..`pnl_5000`) chronologically from real resolved closed trades (`is_redeemable = FALSE`) into `wallet_metrics_v2`.
- **Master Coordinator (`src/workers/positions_metrics_compute.py`)**: Unified entrypoint orchestrating Workers A, B, and C in parallel across all active wallets.

---

## Wallet Tiers & Statuses

Wallets are mutually exclusive and assigned one of the following `tier` values on `wallets_v2`:
- **`UNCLASSIFIED`**: In the discovery queue, awaiting vetting by `wallet_trade_history.py`.
- **`LOW_BALANCE`**: Balance + position value between $0 and $1,000 (including zero-balance active traders).
- **`NEW`**: Balance + position value >= $1,000, never traded.
- **`STANDARD`**: Balance + position value >= $1,000, has traded within 30 days.
- **`CURATED`**: Meets curation criteria (Total PnL > $10k AND ROI > 30% or Win Rate > 70%); never auto-demoted if custom.

Inactive wallets (no trade in 30 days) are flagged with **`is_dormant = True`** (Hibernating) — orthogonal to tier. **Might Cook** ($5k+ deposit, zero trades) is a badge (`might_cook_type`), not a tier.

Wallet discovery sources (`wallet_sources_v2`, multi-row per wallet): `trade`, `deposit`, `leaderboard`, `custom`.

