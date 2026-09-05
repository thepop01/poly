# API Call Timeline & Process Schedule

*All times UTC. System processes run continuously on server unless specified on fixed schedules.*

---

## Weekly Schedule Overview

| Time (UTC) | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| **00:00 – 14:00** | — | — | — | — | — | — | — |
| **14:00 (2 PM)** | 🟦 Leaderboard Sync | — | — | — | — | — | — |
| **14:00 – 24:00** | — | — | — | — | — | — | — |
| **24/7 Continuous** | 🟢 Trade Tracker · 🟢 Deposit Tracker · 🟢 Redemption Tracker · 🟡 Stats Refresher · 🔵 Worker 1 · 🔵 Worker 2 · 🔵 Worker 3 · 🟣 Wallet Discovery | ← | ← | ← | ← | ← | ← |

---

## Feature-by-Feature Process Schedule

### 1. Real-Time Activity Feed Page (`/feed`)

Processes feeding real-time global trade streams, payout redemptions, and deposit alerts.

#### 🟢 Trade Tracker — `trade_tracker.py`
- **Cadence:** Every 15 seconds, 24/7.
- **Page Feature Powered:** Real-Time Trades Stream on `/feed`.
- **API Calls Used:**
  - `#15` (Polygon block height)
  - `#18` (`getLogs` `ORDER_FILLED` across all 4 CTF exchanges)
  - `#22–25` (CLOB & Gamma market title/category resolution)

#### 🟢 Redemption Tracker — `redemption_tracker.py`
- **Cadence:** Continuous loop, 24/7.
- **Page Feature Powered:** Real-Time Payout Redemptions Stream on `/feed`.
- **API Calls Used:**
  - `#15` (Block height)
  - `#19` (`getLogs` `PAYOUT_REDEMPTION` on CTF contract)
  - `#20` (`getLogs` `PAYOUT_REDEMPTION` on NegRisk adapter)

#### 🟢 Deposit Tracker — `deposit_tracker.py`
- **Cadence:** Every 60 seconds, 24/7.
- **Page Feature Powered:** On-ramp Deposit Alerts (≥ $5k) & Wallet Discovery.
- **API Calls Used:**
  - `#14` (Alchemy pUSD mint transfer scan from zero address)
  - `#15` (Block height)

---

### 2. Leaderboard & Wallets Page (`/wallets`, `/leaderboard`)

Processes computing PnL, win rates, ROI %, peak capital, and maintaining tier classification across **All**, **Curated**, **Standard**, **Low Balance**, **New**, and **Hibernated** tabs.

#### 🟡 Stats Refresher — `stats_refresher.py`
- **Cadence:** Every 5 minutes, 24/7.
- **Refresh Window**:
  - **Active Wallets (`is_dormant = FALSE`)**: Checked every **12 hours** (`computed_at < NOW() - 12 hours`).
  - **Hibernated Wallets (`is_dormant = TRUE`)**: Position sources are refreshed when missing or older than 48 hours. `last_trade_sweeper.py` also checks dormant wallets and wakes them only from a verified recent `/activity` timestamp.
- **Page Feature Powered:** Total Capital calculation (`balance + position_value`), dormancy state (`is_dormant`), tier state transitions (`STANDARD`, `LOW_BALANCE`, `NEW`, `HIBERNATED`, `CURATED`).
- **API Calls Used:**
  - `#1` (Open positions value)
  - `#9` (pUSD token cash balance)
  - `#10–13` (Incremental Alchemy capital metrics)

#### 🔵 Derived metrics — `positions_metrics_compute.py`
- **Cadence:** Run after open/closed source refresh; see the [Operations Runbook](rule.md) for phase gates and current concurrency defaults.
- **Page Feature Powered:** Win Rate %, Resolved Count, 10 PnL Sample Windows (`pnl_100` → `pnl_5000`), Official Polymarket PnL/Volume, and Official Leaderboard ROI % (`(pm_pnl / total_volume) * 100`).
- **API Calls Used:**
  - `#1` (Open positions)
  - `#2` (Closed positions source; completeness is tracked by the source worker and is not inferred from a page count)
  - `#6` (Official leaderboard PnL/Volume/Rank)

*(Note: `capital_metrics_backfill.py` retired on 2026-08-22 as ROI is calculated directly in Worker 1 & Stats Refresher).*

---

### 3. Verification & Discovery Processes

Processes discovering new candidates and verifying on-chain activity.

#### 🔵 Worker 3 — `onchain_verifier.py`
- **Cadence:** Continuous queue drain, 24/7 *(1 req/sec rate limit)*.
- **Feature Powered:** Verifies whether wallets returning $0 volume from REST APIs actually traded on-chain.
- **API Calls Used:**
  - `#16` (`getLogs` `ORDER_FILLED` maker)
  - `#17` (`getLogs` `ORDER_FILLED` taker)
  - `#22–25` (Market metadata resolution)

#### 🟣 Wallet Discovery — `wallet_trade_history.py`
- **Cadence:** Every 60 seconds, 24/7.
- **Feature Powered:** Vets `UNCLASSIFIED` candidate wallets discovered by trade_tracker, deposit_tracker, or leaderboard sync and assigns their initial tier.
- **API Calls Used:**
  - `#1` (Open positions)
  - `#3` (Single latest trade `last_trade_at`)
  - `#6` (Leaderboard profile)
  - `#9` (pUSD balance)

#### 🟦 Leaderboard Discovery Sync — `poly_leaderboard_sync.py`
- **Cadence:** Scheduled **Once per week on Monday at 14:00 (2 PM) UTC**.
- **Feature Powered:** Top trader discovery across Polymarket Overall & 10 Category Leaderboards (SPORTS, POLITICS, CRYPTO, etc.). Adds top candidate wallets to `wallets_v2`.
- **API Calls Used:**
  - `#8` (`GET /v1/leaderboard` across Overall and 10 categories, ~150 pages)

---

## Full System Cadence Summary Table

| Process / Worker | Schedule / Frequency | Target Scope | Page / Feature Powered |
|---|---|---|---|
| **Trade Tracker** | Every 15s | Global trading activity | Live Trade Stream on `/feed` & User Notifications |
| **Redemption Tracker** | Continuous poll | Global market payouts | Live Redemptions Stream on `/feed` |
| **Deposit Tracker** | Every 60s | $5k+ pUSD mints | On-ramp Alerts & Wallet Discovery |
| **Stats Refresher** | Every 5 min (12h window) | Active wallets (`is_dormant = FALSE`) | Total Capital & Active Tier State |
| **Worker 1 (Win Rate)** | Continuous | Active wallets | Win Rate & 10 PnL Windows on `/wallets` |
| **Worker 2 (Capital Metrics)**| Continuous | Active wallets | Deposits, Withdrawals, Peak Capital, ROI % |
| **Worker 3 (On-chain Verifier)**| 1 req/sec | $0-volume REST wallets | On-chain trade verification |
| **Wallet Discovery** | Every 60s | `UNCLASSIFIED` discovery queue | Initial tier vetting |
| **Leaderboard Sync** | Monday 2 PM UTC | Polymarket Top 5,000 | Weekly new wallet discovery |
