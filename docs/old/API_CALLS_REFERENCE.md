# All API Calls — Feature, Page & Interval Reference

*Updated: 2026-08-12. Grouped by Page/Feature, Worker, and Execution Interval.*

---

## 1. Leaderboard & Wallets Page (`/wallets`, `/leaderboard`)

This page displays wallet metrics across tabs (**All**, **Curated**, **Standard**, **Low Balance**, **New**, **Hibernated**).

> [!NOTE]
> All per-wallet stats refreshes below apply to **all active wallets (`is_dormant = FALSE`)** regardless of tier (`CURATED`, `STANDARD`, `LOW_BALANCE`, or `NEW`). Hibernated wallets are **not** proactively refreshed; when a hibernated wallet trades on-chain, `trade_tracker.py` detects it within 15 seconds → the dormancy sweep flips `is_dormant = FALSE` → the wallet re-enters the active 12h refresh queue automatically.

### Metrics Computed & APIs Used

| Feature / Metric | What API is Called | Endpoint / RPC Method | Worker / Process | Calling Interval | File / Table Updated |
|---|---|---|---|---|---|
| **All-Time PnL, Volume, Rank & Username** | Polymarket Data API | `GET /v1/leaderboard?user={addr}` | Worker 1 · Stats Worker · Wallet Discovery | **Every 12h** (all active wallets) | `leaderboard_stats.py` → `wallet_metrics_v2` |
| **Open Position Value & Count** | Polymarket Data API | `GET /positions?user={addr}&limit=500` | Worker 1 · Stats Refresher · Wallet Discovery | **Every 12h** (all active wallets) | `leaderboard_stats.py` → `wallet_positions_v2` |
| **Win Rate & 10 Sample-Size PnL Windows** | Polymarket Data API | `GET /closed-positions?user={addr}&limit=50` *(capped at 5,000)* | Worker 1 · Stats Worker | **Every 12h** (all active wallets) | `positions_winrate_backfill.py` → `wallet_closed_positions_v2` |
| **Current USDC / pUSD Cash Balance** | Alchemy Polygon RPC | `alchemy_getTokenBalances` | Stats Refresher · Wallet Discovery | **Every 12h** (all active wallets) | `stats_refresher.py` → `wallet_metrics_v2` |
| **All-Time ROI %** | Polymarket Leaderboard API | `(pm_pnl / total_volume) * 100` | Worker 1 · Stats Refresher | **Every 12h** (all active wallets) | `positions_winrate_backfill.py` → `wallet_metrics_v2` |
| **Category Breakdown (All Active Wallets)** | Position Title Parsing (`classify_tags`) + Sync | Derived from `/positions`, `/closed-positions`, & Leaderboard Sync | Worker 1 · Worker 3 (Sync) | **Every 12h** (all active wallets) / **Weekly** (Sync) | `positions_winrate_backfill.py` → `category_stats_v2` |

---

## Unified Trade & Position Data Architecture (All Active Wallets)

We do **not** differentiate between `CURATED` and other active wallets (`STANDARD`, `LOW_BALANCE`, `NEW`) for trade tracking, notifications, or metrics. All active wallets are handled uniformly across two main tables:

1. **Closed & Open Position History (`wallet_closed_positions_v2` / `wallet_positions_v2`)**:
   - Fetched via REST API (`/positions` & `/closed-positions`), capped at **5,000 most recent positions per fetch**.
   - Stores position-level title, condition ID, asset, realized PnL, cash PnL, average buy price, and outcome for **every active wallet**.

2. **Real-Time Global Trade Stream & Notifications (`wallet_activity_v2`)**:
   - `trade_tracker.py` polls Polygon EVM logs (`ORDER_FILLED`) every 15 seconds across all 4 CTF exchanges.
   - Captures **every live trade happening across all wallets**. Powers the real-time activity feed on `/feed` and triggers user trade/position notifications when a user tracks any wallet.

*(Note: Data API calls #4 `/trades?maker=` and #5 `/trades?taker=` and call #7 `/v1/leaderboard?category=` were legacy REST fallbacks from early spec drafts. The current production pipeline processes positions, category stats, and real-time trade feeds uniformly for all active wallets.)*

---

## 2. Real-Time Activity Feed Page (`/feed`, Live Trades, Live Redemptions, Deposit Alerts)

This page streams global Polymarket activity in near-real-time and detects major capital movements.

### Features & APIs Used

| Feature / Feed Item | What API is Called | Endpoint / Log Event | Worker / Process | Calling Interval | File |
|---|---|---|---|---|---|
| **Live Global Trade Stream** | Polygonscan / Etherscan V2 | `getLogs` on CTF Exchange contracts (`ORDER_FILLED` event) | `trade_tracker.py` | **Every 15 seconds** | `trade_tracker.py` · `etherscan_client.py` |
| **Market Title & Tags Resolution (Primary)** | Polymarket CLOB API | `GET /markets/{condition_id}` | `trade_tracker.py` · `redemption_tracker.py` | **On-demand** *(cached in DB)* | `etherscan_client.py` `_fetch_market_meta` |
| **Market Title & Category Resolution (Fallback)** | Polymarket Gamma API | `GET /markets?clob_token_ids={id}` & `GET /events?id={id}` | `trade_tracker.py` · `redemption_tracker.py` | **On-demand** *(fallback retry)* | `etherscan_client.py` `_fetch_market_meta` |
| **Live Payout Redemptions Feed** | Polygonscan / Etherscan V2 | `getLogs` on CTF & NegRisk contracts (`PAYOUT_REDEMPTION`) | `redemption_tracker.py` | **Continuous poll** (~15s) | `redemption_tracker.py` · `etherscan_client.py` |
| **New Whale On-ramp Alerts (≥ $5k)** | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (pUSD mints from zero address) | `deposit_tracker.py` | **Every 60 seconds** | `deposit_tracker.py` · `alchemy_client.py` |
| **Block Number Synchronization** | Alchemy RPC / Polygonscan | `eth_blockNumber` | All feed trackers | **Every 15 seconds** | `etherscan_client.py` `get_latest_block_etherscan` |

---

## 3. On-Chain Verification Pipeline (Worker 3)

For candidate wallets returning $0 volume and 0 positions via REST API, Worker 3 verifies whether on-chain trades occurred.

| Step / Verification Action | What API is Called | Endpoint / Log Event | Worker | Calling Interval | File |
|---|---|---|---|---|---|
| **Historical Maker-Side Fills** | Polygonscan / Etherscan V2 | `getLogs` (`ORDER_FILLED`, topic2 = wallet) | Worker 3 | **1 req/sec** *(queue drain)* | `onchain_verifier.py` · `etherscan_client.py` |
| **Historical Taker-Side Fills** | Polygonscan / Etherscan V2 | `getLogs` (`ORDER_FILLED`, topic3 = wallet) | Worker 3 | **1 req/sec** *(queue drain)* | `onchain_verifier.py` · `etherscan_client.py` |
| **Trade Token Metadata Resolution** | Polymarket CLOB / Gamma API | `GET /markets/{condition_id}` | Worker 3 | **On-demand** | `etherscan_client.py` `_fetch_market_meta` |

---

## 4. Wallet Discovery & Initial Vetting Pipeline

Finds new traders across Polymarket and classifies them into the wallet system.

| Discovery Channel | What API is Called | Worker / Process | Calling Interval | Purpose |
|---|---|---|---|---|
| **Leaderboard Sync** | `GET /v1/leaderboard?category={CAT}` | **Worker 4** (`poly_leaderboard_sync.py`) | **Weekly** (Monday 2 PM UTC) | Finds top 5,000 overall + top 2,000 sports + top 500 per category |
| **On-ramp Deposit Tracker** | `alchemy_getAssetTransfers` | `deposit_tracker.py` | **Every 60 seconds** | Finds new wallets depositing ≥ $5,000 |
| **Global Trade Feed** | `getLogs` (`ORDER_FILLED`) | `trade_tracker.py` | **Every 15 seconds** | Finds active wallet addresses trading on-chain |
| **Initial Vetting Gate** | `GET /trades?user={addr}&limit=1` & balance | `wallet_trade_history.py` | **Every 60 seconds** *(queue drain)* | Checks `last_trade_at` recency and initial tier assignment |

---

## Master API Endpoint Summary Table

| # | Source API | Endpoint / Method | Calling Interval | Primary Purpose | Used By |
|---|---|---|---|---|---|
| 1 | Polymarket Data | `GET /positions` | **Every 12h** (all active wallets) | Open position value & expired loss detection | Worker 1, Stats Refresher, Wallet Discovery |
| 2 | Polymarket Data | `GET /closed-positions` | **Every 12h** (all active wallets) | Resolved positions, win rate, 10 PnL windows | Worker 1, Stats Worker |
| 3 | Polymarket Data | `GET /trades?user=` | **Initial vetting** (queue drain) | Recency check (`last_trade_at`) for dormancy | Wallet Discovery |
| 4 | Polymarket Data | `GET /trades?maker=` | *Legacy REST fallback* | Maker trade history | Legacy `leaderboard_stats.py` |
| 5 | Polymarket Data | `GET /trades?taker=` | *Legacy REST fallback* | Taker trade history | Legacy `leaderboard_stats.py` |
| 6 | Polymarket Data | `GET /v1/leaderboard?user=` | **Every 12h** (all active wallets) | All-time official PnL, volume, rank, username | Worker 1, Stats Worker, Wallet Discovery |
| 7 | Polymarket Data | `GET /v1/leaderboard?category=` | *Legacy REST fallback* | Category PnL query | Legacy `leaderboard_stats.py` |
| 8 | Polymarket Data | `GET /v1/leaderboard?orderBy=PNL` | **Weekly** (Monday 2 PM UTC) | Top trader discovery across categories | Worker 4 (Leaderboard Sync) |
| 9 | Alchemy Polygon RPC | `alchemy_getTokenBalances` | **Every 12h** (all active wallets) | pUSD cash balance | Stats Refresher, Wallet Discovery |
| 10 | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (IN zero) | **Every 12h** (all active wallets) | Lifetime USDC deposits | Worker 2, Stats Refresher |
| 11 | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (OUT pUSD) | **Every 12h** (all active wallets) | Lifetime USDC withdrawals | Worker 2, Stats Refresher |
| 12 | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (IN all) | **Every 12h** (all active wallets) | Deposit timeline for peak capital | Worker 2, Stats Refresher |
| 13 | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (OUT all) | **Every 12h** (all active wallets) | Withdrawal timeline for peak capital & ROI | Worker 2, Stats Refresher |
| 14 | Alchemy Polygon RPC | `alchemy_getAssetTransfers` (Mints) | **Every 60 seconds** | Discover new $5k+ depositors | Deposit Tracker |
| 15 | Alchemy Polygon RPC | `eth_blockNumber` | **Every 15 seconds** | Polygon block height bounding | Trade/Redemption/Deposit Trackers |
| 16 | Polygonscan V2 | `getLogs` (`ORDER_FILLED` maker) | **1 req/sec** *(queue drain)* | On-chain trade verification (maker) | Worker 3 (On-chain Verifier) |
| 17 | Polygonscan V2 | `getLogs` (`ORDER_FILLED` taker) | **1 req/sec** *(queue drain)* | On-chain trade verification (taker) | Worker 3 (On-chain Verifier) |
| 18 | Polygonscan V2 | `getLogs` (`ORDER_FILLED` all) | **Every 15 seconds** | Real-time global trade stream | Trade Tracker |
| 19 | Polygonscan V2 | `getLogs` (`PAYOUT_REDEMPTION` CTF) | **Continuous poll** (~15s) | Real-time payout redemptions stream | Redemption Tracker |
| 20 | Polygonscan V2 | `getLogs` (`PAYOUT_REDEMPTION` NegRisk)| **Continuous poll** (~15s) | Real-time NegRisk payout redemptions | Redemption Tracker |
| 21 | Polygonscan V2 | `eth_blockNumber` | **On demand** *(fallback)* | Block height fallback | Trade/Redemption Trackers |
| 22 | Polymarket CLOB | `GET /markets/{condition_id}` | **On demand** *(cached in DB)* | Primary market title & tag resolution | Trade/Redemption Trackers, Worker 3 |
| 23 | Polymarket Gamma | `GET /markets?clob_token_ids=` | **On demand** *(fallback)* | Fallback market title resolution | Trade/Redemption Trackers, Worker 3 |
| 24 | Polymarket Gamma | `GET /markets?...&closed=true` | **On demand** *(fallback)* | Fallback closed market resolution | Trade/Redemption Trackers, Worker 3 |
| 25 | Polymarket Gamma | `GET /events?id=` | **On demand** *(fallback)* | Market event category & tag resolution | Trade/Redemption Trackers, Worker 3 |
