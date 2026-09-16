# Polymarket Official API Reference

> Comprehensive, authoritative reference for all official Polymarket HTTP and WebSocket APIs.
> Sourced directly from official OpenAPI specs (`docs.polymarket.com`), official developer guides, and live empirical probes.

## 1. Services & Architecture Overview

| Service | Production Base URL | Staging / Alternative Base URL | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| **CLOB API** | `https://clob.polymarket.com` | `https://clob-staging.polymarket.com` | Central Limit Order Book: orders, books, prices, trades, rewards & rebates |
| **Data API** | `https://data-api.polymarket.com` | — | User balances, positions, on-chain activity history, leaderboards, accounting snapshots |
| **Gamma API** | `https://gamma-api.polymarket.com` | — | Discovery metadata: markets, events, series, tags, search, sports teams |
| **Relayer API** | `https://relayer-v2.polymarket.com` | — | Gasless meta-transaction submission, safe nonces, wallet deployment checks |
| **Combos RFQ API** | `https://combos-rfq-api.polymarket.com` | — | Multi-market combinatorial positions and RFQ market maker quoting |
| **Bridge API** | `https://bridge.polymarket.com` | — | Cross-chain deposits, quotes, and withdrawals |
| **Perps API** | `https://api.perpetuals.polymarket.com` | — | Polymarket Perpetual futures trading, accounts, and market data |
| **CLOB Market WS** | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | — | Real-time orderbook, price, and market lifecycle WebSocket streams |
| **CLOB User WS** | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | — | Real-time authenticated order and trade execution updates |
| **Live Data RTDS WS** | `wss://ws-live-data.polymarket.com` | — | Real-time data service (prices, trades, Chainlink TWAP feeds) |
| **Sports WS** | `wss://sports-api.polymarket.com/ws` | — | Real-time sports game scores and period updates |
| **Perps WS** | `wss://ws.perpetuals.polymarket.com/v1` | — | Real-time Perps tickers, orderbooks, trades, user fills & notifications |

### Authentication Models

1. **Public / Keyless**: Most read endpoints across Gamma, Data, and CLOB market data require no API key or signature.
2. **CLOB Level 2 (L2) Auth**: Required for order placement, cancellations, account credentials, and rewards data (`/rewards/user*`):
   - `POLY_ADDRESS`: Signer Ethereum address (EOA or Poly Proxy)
   - `POLY_SIGNATURE`: HMAC signature generated using the API secret
   - `POLY_TIMESTAMP`: Current epoch timestamp (seconds)
   - `POLY_API_KEY`: CLOB API Key ID
   - `POLY_PASSPHRASE`: CLOB API Passphrase
3. **Builder & Relayer Auth**: Used for routing orders through builder accounts or gasless transactions:
   - `POLY_BUILDER_API_KEY`, `POLY_BUILDER_TIMESTAMP`, `POLY_BUILDER_PASSPHRASE`, `POLY_BUILDER_SIGNATURE`
   - Alternatively: `RELAYER_API_KEY` and `RELAYER_API_KEY_ADDRESS`
4. **Perps Auth**: EOA signature for proxy management / withdrawals, and Proxy API secret / HMAC headers for high-frequency trading.

## 2. Rewards & Rebates Endpoints (CLOB API)

> **Documentation Reference:** [`https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date`](https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date)
>
> Polymarket provides liquidity rewards and maker fee rebates calculated daily per market condition.

### Rewards Endpoints Table

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/rewards/user` | Get earnings for user by date | **Req:** `date`<br>Opt: `signature_type`, `maker_address`, `sponsored`, `next_cursor` | 🔒 L2 Auth |
| `GET` `/rewards/user/total` | Get total earnings for user by date | **Req:** `date`<br>Opt: `signature_type`, `maker_address`, `sponsored` | 🔒 L2 Auth |
| `GET` `/rewards/user/percentages` | Get reward percentages for user | Opt: `signature_type`, `maker_address` | 🔒 L2 Auth |
| `GET` `/rewards/user/markets` | Get user earnings and markets configuration | Opt: `date`, `signature_type`, `maker_address`, `sponsored`, `next_cursor`, `page_size`, `q`, `tag_slug`, `favorite_markets`, `no_competition`, `only_mergeable`, `only_open_orders`, `only_open_positions`, `order_by`, `position` | 🔒 L2 Auth |
| `GET` `/rewards/markets/current` | Get current active rewards configurations | Opt: `sponsored`, `next_cursor` | 🌐 Public |
| `GET` `/rewards/markets/{condition_id}` | Get raw rewards for a specific market | **Req:** `condition_id` (path)<br>Opt: `sponsored`, `next_cursor` | 🌐 Public |
| `GET` `/rewards/markets/multi` | Get multiple markets with rewards | Opt: `q`, `tag_slug`, `event_id`, `event_title`, `order_by`, `position`, `min_volume_24hr`, `max_volume_24hr`, `min_spread`, `max_spread`, `min_price`, `max_price`, `next_cursor`, `page_size` | 🌐 Public |
| `GET` `/rebates/current` | Get current rebated fees for a maker | **Req:** `date`, `maker_address` | 🔒 L2 Auth |

### Detailed Specification: `GET /rewards/user` (User Earnings by Date)

- **URL**: `https://clob.polymarket.com/rewards/user`
- **Authentication**: Requires CLOB L2 Auth headers (`POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_API_KEY`, `POLY_PASSPHRASE`).
- **Description**: Returns an array of user earnings per market condition for a provided day.
- **Pagination**: Cursor-based, 100 items per page. Pass the returned `next_cursor` into the next request. A `next_cursor` value of `"LTE="` indicates the final page.

| Query Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `date` | string (YYYY-MM-DD) | **Yes** | Date to query earnings for (e.g. `2024-03-26`). |
| `signature_type` | integer | No | Signature type for address derivation (`0` = EOA, `1` = POLY_PROXY, `2` = POLY_GNOSIS_SAFE). |
| `maker_address` | string | No | Maker address to query earnings for (defaults to authenticated identity). |
| `sponsored` | boolean | No | Filter by sponsored rewards program. |
| `next_cursor` | string | No | Pagination cursor for fetching subsequent pages. |

#### Response Example (`GET /rewards/user`)
```json
{
  "data": [
    {
      "condition_id": "0x1234...5678",
      "asset_address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
      "date": "2024-03-26",
      "earnings": "12.450000",
      "asset_symbol": "USDC"
    }
  ],
  "next_cursor": "LTE="
}
```

### Detailed Specification: Companion Reward Endpoints

- **`GET /rewards/user/total`**: Sums total daily earnings for the authenticated user grouped by payout asset (e.g. total USDC across all markets).
- **`GET /rewards/user/percentages`**: Returns the real-time share/percentage of rewards the user is currently capturing across active reward-eligible markets.
- **`GET /rewards/user/markets`**: Rich multi-attribute view combining user earnings with market configuration. Supports extensive filters: `only_mergeable`, `only_open_orders`, `only_open_positions`, `no_competition`, `tag_slug`, `favorite_markets`, `order_by`, and `page_size`.
- **`GET /rewards/markets/current`**: All current active market reward pools, reward rates per day, and conditions.
- **`GET /rewards/markets/{condition_id}`**: Historical, present, and scheduled future rewards configured for a specific market condition ID.
- **`GET /rewards/markets/multi`**: Search and discover reward-bearing markets with volume, spread, and price filters (`min_volume_24hr`, `min_spread`, `min_price`).
- **`GET /rebates/current`**: Computes maker fee rebates for an address on a specific date (`date*`, `maker_address*`).

## 3. CLOB API Reference (`https://clob.polymarket.com`)

### 3.1 Trade & Order Execution

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `POST` `/order` | Post a new order | Body payload (JSON) | 🔒 Auth |
| `DELETE` `/order` | Cancel single order | Body payload (JSON) | 🔒 Auth |
| `POST` `/orders` | Post multiple orders | Body payload (JSON) | 🔒 L2 Auth |
| `DELETE` `/orders` | Cancel multiple orders | Body payload (JSON) | 🔒 L2 Auth |
| `GET` `/data/orders` | Get user orders | Opt: `id`, `market`, `asset_id`, `next_cursor` | 🔒 Auth |
| `GET` `/data/order/{orderID}` | Get single order by ID | **Req:** `orderID` (path) | 🔒 Auth |
| `DELETE` `/cancel-all` | Cancel all orders | None | 🔒 Auth |
| `DELETE` `/cancel-market-orders` | Cancel orders for a market | Body payload (JSON) | 🔒 L2 Auth |
| `POST` `/heartbeats` | Send heartbeat | None | 🔒 Auth |
| `POST` `/v1/heartbeats` | Send heartbeat (v1) | Body payload (JSON) | 🔒 Auth |
| `GET` `/order-scoring` | Get order scoring status | **Req:** `order_id` | 🔒 Auth |
| `GET` `/orders-scoring` | Get scoring status for multiple orders | **Req:** `order_ids` | 🔒 Auth |
| `POST` `/orders-scoring` | Get scoring status for multiple orders (POST) | Body payload (JSON) | 🔒 L2 Auth |
| `GET` `/data/trades` | Get trades | **Req:** `maker_address`<br>Opt: `id`, `market`, `asset_id`, `before`, `after`, `next_cursor` | 🔒 Auth |
| `GET` `/builder/trades` | Get builder trades | **Req:** `builder_code`<br>Opt: `id`, `market`, `asset_id`, `before`, `after`, `next_cursor` | 🌐 Public |

### 3.2 Market Data, Prices & Order Books

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/time` | Get server time | None | 🌐 Public |
| `GET` `/midpoint` | Get midpoint price | **Req:** `token_id` | 🌐 Public |
| `GET` `/midpoints` | Get midpoint prices (query parameters) | **Req:** `token_ids` | 🌐 Public |
| `POST` `/midpoints` | Get midpoint prices (request body) | Body payload (JSON) | 🌐 Public |
| `GET` `/spread` | Get spread | **Req:** `token_id` | 🌐 Public |
| `POST` `/spreads` | Get spreads | Body payload (JSON) | 🌐 Public |
| `GET` `/last-trade-price` | Get last trade price | **Req:** `token_id` | 🌐 Public |
| `GET` `/last-trades-prices` | Get last trade prices (query parameters) | **Req:** `token_ids` | 🌐 Public |
| `POST` `/last-trades-prices` | Get last trade prices (request body) | Body payload (JSON) | 🌐 Public |
| `GET` `/fee-rate` | Get fee rate | Opt: `token_id` | 🌐 Public |
| `GET` `/fee-rate/{token_id}` | Get fee rate by path parameter | **Req:** `token_id` (path) | 🌐 Public |
| `GET` `/tick-size` | Get tick size | Opt: `token_id` | 🌐 Public |
| `GET` `/tick-size/{token_id}` | Get tick size by path parameter | **Req:** `token_id` (path) | 🌐 Public |
| `GET` `/neg-risk` | Get negative risk flag | Opt: `token_id` | 🌐 Public |
| `GET` `/neg-risk/{token_id}` | Get negative risk flag by path parameter | **Req:** `token_id` (path) | 🌐 Public |
| `GET` `/price` | Get market price | **Req:** `token_id`, `side` | 🌐 Public |
| `GET` `/prices` | Get market prices (query parameters) | **Req:** `token_ids`, `sides` | 🌐 Public |
| `POST` `/prices` | Get market prices (request body) | Body payload (JSON) | 🌐 Public |
| `GET` `/book` | Get order book | **Req:** `token_id` | 🌐 Public |
| `GET` `/books` | Get order books (query parameters) | **Req:** `token_ids` | 🌐 Public |
| `POST` `/books` | Get order books (request body) | Body payload (JSON) | 🌐 Public |

### 3.3 Markets Discovery & Price History

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/simplified-markets` | Get simplified markets | Opt: `next_cursor` | 🌐 Public |
| `GET` `/sampling-markets` | Get sampling markets | Opt: `next_cursor` | 🌐 Public |
| `GET` `/sampling-simplified-markets` | Get sampling simplified markets | Opt: `next_cursor` | 🌐 Public |
| `GET` `/clob-markets/{condition_id}` | Get CLOB market info | **Req:** `condition_id` (path) | 🌐 Public |
| `GET` `/markets-by-token/{token_id}` | Get market by token | **Req:** `token_id` (path) | 🌐 Public |
| `POST` `/markets/live-activity` | Get live activity markets by condition IDs | Body payload (JSON) | 🌐 Public |
| `GET` `/markets/live-activity/{condition_id}` | Get live activity market by condition ID | **Req:** `condition_id` (path) | 🌐 Public |
| `GET` `/prices-history` | Get prices history | **Req:** `market`<br>Opt: `startTs`, `endTs`, `interval`, `fidelity` | 🌐 Public |
| `POST` `/batch-prices-history` | Get batch prices history | Body payload (JSON) | 🌐 Public |

### 3.4 Account, API Keys & Allowance

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `POST` `/auth/api-key` | Create API key | None | 🔒 L2 Auth |
| `DELETE` `/auth/api-key` | Delete API key | None | 🔒 L2 Auth |
| `GET` `/auth/api-keys` | Get API keys | None | 🔒 L2 Auth |
| `GET` `/auth/derive-api-key` | Derive API key | None | 🔒 L2 Auth |
| `GET` `/balance-allowance` | Get balance and allowance | **Req:** `asset_type`<br>Opt: `token_id`, `signature_type` | 🔒 Auth |
| `PUT` `/balance-allowance` | Update balance and allowance | **Req:** `asset_type`<br>Opt: `token_id`, `signature_type` | 🔒 Auth |
| `GET` `/balance-allowance/update` | Update balance and allowance | **Req:** `asset_type`<br>Opt: `token_id`, `signature_type` | 🔒 Auth |
| `GET` `/auth/ban-status/closed-only` | Get closed-only mode status | None | 🔒 L2 Auth |
| `GET` `/auth/builder-api-key` | Get builder API keys | None | 🔒 L2 Auth |
| `POST` `/auth/builder-api-key` | Create builder API key | None | 🔒 L2 Auth |
| `DELETE` `/auth/builder-api-key` | Revoke builder API key | None | 🔒 L2 Auth |
| `GET` `/notifications` | Get notifications | **Req:** `signature_type` | 🔒 Auth |
| `DELETE` `/notifications` | Mark notifications as read | **Req:** `ids` | 🔒 Auth |

## 4. Data API Reference (`https://data-api.polymarket.com`)

> Primary service for user trading history, balances, portfolio valuations, and market-level participant data.

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/` | Data API Health check | None | 🌐 Public |
| `GET` `/v1/accounting/snapshot` | Download an accounting snapshot (ZIP of CSVs) | **Req:** `user` | 🌐 Public |
| `GET` `/v1/approvals` | Get token approval state for a wallet | **Req:** `user` | 🌐 Public |
| `GET` `/positions` | Get current positions for a user | **Req:** `user`<br>Opt: `market`, `eventId`, `sizeThreshold`, `redeemable`, `mergeable`, `includeArchived`, `limit`, `offset`, `sortBy`, `sortDirection`, `title` | 🌐 Public |
| `GET` `/trades` | Get trades for a user or markets | Opt: `limit`, `offset`, `takerOnly`, `filterType`, `filterAmount`, `market`, `eventId`, `user`, `side`, `start`, `end` | 🌐 Public |
| `GET` `/activity` | Get user activity | **Req:** `user`<br>Opt: `limit`, `offset`, `market`, `eventId`, `type`, `excludeDepositsWithdrawals`, `start`, `end`, `sortBy`, `sortDirection`, `side` | 🌐 Public |
| `GET` `/v1/activity/combos` | Get user combo activity | **Req:** `user`<br>Opt: `market_id`, `limit`, `offset`, `cursor` | 🌐 Public |
| `GET` `/v1/positions/combos` | Get user combo positions | **Req:** `user`<br>Opt: `status`, `sort`, `market_id`, `limit`, `offset`, `updatedAfter`, `updatedBefore`, `cursor` | 🌐 Public |
| `GET` `/holders` | Get top holders for markets | **Req:** `market`<br>Opt: `limit`, `minBalance` | 🌐 Public |
| `GET` `/traded` | Get total markets a user has traded | **Req:** `user` | 🌐 Public |
| `GET` `/revisions` | Get moderated revisions for a question | **Req:** `questionID`<br>Opt: `limit` | 🌐 Public |
| `GET` `/value` | Get total value of a user's positions | **Req:** `user`<br>Opt: `market` | 🌐 Public |
| `GET` `/oi` | Get open interest | Opt: `market` | 🌐 Public |
| `GET` `/live-volume` | Get live volume for an event | **Req:** `id` | 🌐 Public |
| `GET` `/closed-positions` | Get closed positions for a user | **Req:** `user`<br>Opt: `market`, `title`, `eventId`, `limit`, `offset`, `sortBy`, `sortDirection` | 🌐 Public |
| `GET` `/other` | Get "Other" size for an augmented neg risk event and user | **Req:** `id`, `user` | 🌐 Public |
| `GET` `/v1/market-positions` | Get positions for a market | **Req:** `market`<br>Opt: `user`, `status`, `sortBy`, `sortDirection`, `limit`, `offset` | 🌐 Public |
| `GET` `/v1/builders/leaderboard` | Get aggregated builder leaderboard | Opt: `timePeriod`, `limit`, `offset` | 🌐 Public |
| `GET` `/v1/builders/volume` | Get daily builder volume time-series | Opt: `timePeriod` | 🌐 Public |
| `GET` `/v1/leaderboard` | Get trader leaderboard rankings | Opt: `category`, `timePeriod`, `orderBy`, `limit`, `offset`, `user`, `userName` | 🌐 Public |

## 5. Gamma API Reference (`https://gamma-api.polymarket.com`)

> Primary service for event discovery, market metadata, tag taxonomies, sports schedules, and social comments.

### 5.1 Markets & Keyset Pagination

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/markets` | List markets | Opt: `id`, `slug`, `clob_token_ids`, `condition_ids`, `liquidity_num_min`, `liquidity_num_max`, `volume_num_min`, `volume_num_max`, `start_date_min`, `start_date_max`, `end_date_min`, `end_date_max`, `tag_id`, `related_tags`, `cyom`, `uma_resolution_status`, `game_id`, `sports_market_types`, `rewards_min_size`, `question_ids`, `include_tag`, `closed` | 🌐 Public |
| `GET` `/markets/{id}` | Get market by id | Opt: `include_tag` | 🌐 Public |
| `GET` `/markets/{id}/description` | Get market description by id | None | 🌐 Public |
| `GET` `/markets/{id}/tags` | Get market tags by id | None | 🌐 Public |
| `GET` `/markets/slug/{slug}` | Get market by slug | Opt: `include_tag` | 🌐 Public |
| `POST` `/markets/information` | Query markets by information filters | Body payload (JSON) | 🌐 Public |
| `POST` `/markets/abridged` | Query abridged markets by information filters | Body payload (JSON) | 🌐 Public |
| `GET` `/markets/keyset` | List markets (keyset pagination) | Opt: `limit`, `order`, `ascending`, `after_cursor`, `offset`, `id`, `slug`, `closed`, `decimalized`, `clob_token_ids`, `condition_ids`, `question_ids`, `liquidity_num_min`, `liquidity_num_max`, `volume_num_min`, `volume_num_max`, `start_date_min`, `start_date_max`, `end_date_min`, `end_date_max`, `tag_id`, `related_tags`, `tag_match`, `cyom`, `rfq_enabled`, `uma_resolution_status`, `game_id`, `sports_market_types`, `include_tag`, `locale` | 🌐 Public |

### 5.2 Events & Keyset Pagination

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/events` | List events | Opt: `id`, `tag_id`, `exclude_tag_id`, `slug`, `tag_slug`, `related_tags`, `active`, `archived`, `featured`, `cyom`, `include_chat`, `include_template`, `recurrence`, `closed`, `liquidity_min`, `liquidity_max`, `volume_min`, `volume_max`, `start_date_min`, `start_date_max`, `end_date_min`, `end_date_max` | 🌐 Public |
| `GET` `/events/pagination` | List events (paginated) | Opt: `include_chat`, `include_template`, `recurrence` | 🌐 Public |
| `GET` `/events/results` | List sport events results | None | 🌐 Public |
| `GET` `/events/{id}` | Get event by id | Opt: `include_chat`, `include_template` | 🌐 Public |
| `GET` `/events/{id}/tweet-count` | Get event tweet count | None | 🌐 Public |
| `GET` `/events/{id}/comments/count` | Get event comment count | None | 🌐 Public |
| `GET` `/events/{id}/tags` | Get event tags | None | 🌐 Public |
| `GET` `/events/slug/{slug}` | Get event by slug | Opt: `include_chat`, `include_template` | 🌐 Public |
| `GET` `/events/creators` | List event creators | Opt: `creator_name`, `creator_handle` | 🌐 Public |
| `GET` `/events/creators/{id}` | Get event creator by id | None | 🌐 Public |
| `GET` `/events/keyset` | List events (keyset pagination) | Opt: `limit`, `order`, `ascending`, `after_cursor`, `offset`, `id`, `slug`, `closed`, `live`, `featured`, `cyom`, `title_search`, `liquidity_min`, `liquidity_max`, `volume_min`, `volume_max`, `start_date_min`, `start_date_max`, `end_date_min`, `end_date_max`, `start_time_min`, `start_time_max`, `tag_id`, `tag_slug`, `exclude_tag_id`, `related_tags`, `tag_match`, `series_id`, `game_id`, `event_date`, `event_week`, `featured_order`, `recurrence`, `created_by`, `parent_event_id`, `include_children`, `partner_slug`, `include_chat`, `include_template`, `include_best_lines`, `locale` | 🌐 Public |

### 5.3 Series, Tags, Sports & Search

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/status` | Gamma API Health check | None | 🌐 Public |
| `GET` `/teams` | List teams | Opt: `league`, `name`, `abbreviation` | 🌐 Public |
| `GET` `/teams/{id}` | Get team by id | None | 🌐 Public |
| `GET` `/tags` | List tags | Opt: `include_template`, `is_carousel` | 🌐 Public |
| `GET` `/tags/{id}` | Get tag by id | Opt: `include_template` | 🌐 Public |
| `GET` `/tags/slug/{slug}` | Get tag by slug | Opt: `include_template` | 🌐 Public |
| `GET` `/tags/{id}/related-tags` | Get related tags (relationships) by tag id | Opt: `omit_empty`, `status` | 🌐 Public |
| `GET` `/tags/slug/{slug}/related-tags` | Get related tags (relationships) by tag slug | Opt: `omit_empty`, `status` | 🌐 Public |
| `GET` `/tags/{id}/related-tags/tags` | Get tags related to a tag id | Opt: `omit_empty`, `status` | 🌐 Public |
| `GET` `/tags/slug/{slug}/related-tags/tags` | Get tags related to a tag slug | Opt: `omit_empty`, `status` | 🌐 Public |
| `GET` `/series` | List series | Opt: `slug`, `categories_ids`, `categories_labels`, `closed`, `include_chat`, `recurrence`, `exclude_events` | 🌐 Public |
| `GET` `/series/{id}` | Get series by id | Opt: `include_chat` | 🌐 Public |
| `GET` `/series/{id}/comments/count` | Get series comment count | None | 🌐 Public |
| `GET` `/series-summary/{id}` | Get series summary by id | None | 🌐 Public |
| `GET` `/series-summary/slug/{slug}` | Get series summary by slug | None | 🌐 Public |
| `GET` `/comments` | List comments | Opt: `parent_entity_type`, `parent_entity_id`, `get_positions`, `holders_only` | 🌐 Public |
| `GET` `/comments/{id}` | Get comments by comment id | **Req:** `id` (path)<br>Opt: `get_positions` | 🌐 Public |
| `GET` `/comments/user_address/{user_address}` | Get comments by user address | **Req:** `user_address` (path) | 🌐 Public |
| `GET` `/public-profile` | Get public profile by wallet address | **Req:** `address` | 🌐 Public |
| `GET` `/profiles/user_address/{user_address}` | Get public profile by user address | **Req:** `user_address` (path) | 🌐 Public |
| `GET` `/sports` | Get sports metadata information | None | 🌐 Public |
| `GET` `/sports/market-types` | Get valid sports market types | None | 🌐 Public |
| `GET` `/public-search` | Search markets, events, and profiles | **Req:** `q`<br>Opt: `cache`, `events_status`, `limit_per_type`, `page`, `events_tag`, `keep_closed_markets`, `sort`, `ascending`, `search_tags`, `search_profiles`, `recurrence`, `exclude_tag_id`, `optimized` | 🌐 Public |

## 6. Relayer API (`https://relayer-v2.polymarket.com`)

> Gasless meta-transaction submission on Polygon via Polymarket Proxy or Gnosis Safe.

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `POST` `/submit` | Submit a transaction | Opt: `POLY_BUILDER_API_KEY` (header), `POLY_BUILDER_TIMESTAMP` (header), `POLY_BUILDER_PASSPHRASE` (header), `POLY_BUILDER_SIGNATURE` (header), `RELAYER_API_KEY` (header), `RELAYER_API_KEY_ADDRESS` (header) | 🔒 Auth (Signed) |
| `GET` `/transaction` | Get a transaction by ID | **Req:** `id` | 🌐 Public |
| `GET` `/transactions` | Get recent transactions for a user | Opt: `POLY_BUILDER_API_KEY` (header), `POLY_BUILDER_TIMESTAMP` (header), `POLY_BUILDER_PASSPHRASE` (header), `POLY_BUILDER_SIGNATURE` (header), `RELAYER_API_KEY` (header), `RELAYER_API_KEY_ADDRESS` (header) | 🔒 Auth (Signed) |
| `GET` `/nonce` | Get current nonce for a user | **Req:** `address`, `type` | 🌐 Public |
| `GET` `/relay-payload` | Get relayer address and nonce | **Req:** `address`, `type` | 🌐 Public |
| `GET` `/deployed` | Check if a wallet is deployed | **Req:** `address`<br>Opt: `type` | 🌐 Public |
| `GET` `/relayer/api/keys` | Get all relayer API keys | Opt: `RELAYER_API_KEY` (header), `RELAYER_API_KEY_ADDRESS` (header) | 🔒 Auth (Signed) |

## 7. Combos RFQ API (`https://combos-rfq-api.polymarket.com`)

> Facilitates multi-market combinatorial trading (e.g. cross-event parlays) via Request-for-Quote (RFQ).

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/v1/rfq/combo-markets` | Get combo markets | Opt: `limit`, `cursor`, `exclude` | 🌐 Public |
| `POST` `/v1/maker/quotes` | Submit a quote | Body payload (JSON) | 🔒 Auth |
| `POST` `/v1/maker/quotes/cancel` | Cancel a quote | Body payload (JSON) | 🔒 Auth |
| `POST` `/v1/maker/confirmations` | Confirm or decline last look | Body payload (JSON) | 🔒 Auth |

## 8. Bridge API (`https://bridge.polymarket.com`)

> Cross-chain onboarding and offboarding of collateral (pUSD / USDC).

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/supported-assets` | Get supported assets | None | 🌐 Public |
| `POST` `/quote` | Get a quote | Body payload (JSON) | 🌐 Public |
| `POST` `/deposit` | Create bridge addresses | Body payload (JSON) | 🌐 Public |
| `POST` `/withdraw` | Create withdrawal addresses | Body payload (JSON) | 🌐 Public |
| `GET` `/status/{address}` | Get transaction status | **Req:** `address` (path)<br>Opt: `limit`, `cursor`, `paginate` | 🌐 Public |

## 9. Perps HTTP API (`https://api.perpetuals.polymarket.com`)

> Polymarket Perpetual futures platform HTTP endpoints.

### 9.1 Public Market Info & Klines

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `GET` `/v1/info/ping` | Test Connection | None | 🌐 Public |
| `GET` `/v1/info/time` | Get Server Time | None | 🌐 Public |
| `GET` `/v1/info/exchange` | Get Exchange Info | None | 🌐 Public |
| `GET` `/v1/info/assets` | Get Collateral Assets | None | 🌐 Public |
| `GET` `/v1/info/instruments` | Get Instruments | Opt: `instrument_id`, `instrument_type`, `category` | 🌐 Public |
| `GET` `/v1/info/tickers` | Get Tickers | Opt: `instrument_id` | 🌐 Public |
| `GET` `/v1/info/statistics` | Get Statistics | Opt: `instrument_id` | 🌐 Public |
| `GET` `/v1/info/klines` | Get Klines | **Req:** `instrument_id`, `interval`, `start_timestamp`<br>Opt: `end_timestamp` | 🌐 Public |
| `GET` `/v1/info/mark-history` | Get Mark Price History | **Req:** `instrument_id`, `interval`, `start_timestamp`<br>Opt: `end_timestamp` | 🌐 Public |
| `GET` `/v1/info/bbo` | Get BBO | Opt: `instrument_id` | 🌐 Public |
| `GET` `/v1/info/book` | Get Book | **Req:** `instrument_id`<br>Opt: `depth` | 🌐 Public |
| `GET` `/v1/info/index` | Get Index | **Req:** `asset` | 🌐 Public |
| `GET` `/v1/info/trades` | Get Recent Trades | **Req:** `instrument_id`<br>Opt: `start_timestamp`, `end_timestamp` | 🌐 Public |
| `GET` `/v1/info/portfolio` | Get Public Portfolio | **Req:** `address` | 🌐 Public |
| `GET` `/v1/info/position-fills` | Get Current Position Fills | **Req:** `address`, `instrument_id`<br>Opt: `cursor`, `sort` | 🌐 Public |
| `GET` `/v1/info/funding` | Get Historical Funding | **Req:** `instrument_id`<br>Opt: `start_timestamp`, `end_timestamp` | 🌐 Public |
| `GET` `/v1/info/fees` | Get Fees | None | 🌐 Public |
| `GET` `/v1/info/limit-tiers` | Get Limit Tiers | None | 🌐 Public |
| `GET` `/v1/info/invite` | Check Invite Code | **Req:** `code`<br>Opt: `address` | 🌐 Public |

### 9.2 Trading, Orders & Margin

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `POST` `/v1/trade/orders` | Create Orders | Body payload (JSON) | 🔒 L2 Auth |
| `DELETE` `/v1/trade/orders` | Cancel Orders | Body payload (JSON) | 🔒 L2 Auth |
| `PATCH` `/v1/trade/orders` | Modify Orders | Body payload (JSON) | 🔒 Signed (Proxy) |
| `DELETE` `/v1/trade/orders/all` | Cancel All Orders | Body payload (JSON) | 🔒 L2 Auth |
| `DELETE` `/v1/trade/orders-coid` | Cancel Orders COID | Body payload (JSON) | 🔒 L2 Auth |
| `PATCH` `/v1/trade/orders-coid` | Modify Orders COID | Body payload (JSON) | 🔒 Signed (Proxy) |
| `PATCH` `/v1/trade/auto-cancel` | Set Auto-Cancel | Body payload (JSON) | 🔒 Signed (Proxy) |
| `PATCH` `/v1/trade/leverage` | Update Leverage | Body payload (JSON) | 🔒 Signed (Proxy) |
| `PATCH` `/v1/trade/leverage/batch` | Update Leverage for Multiple Instruments | Body payload (JSON) | 🔒 Signed (Proxy) |
| `PATCH` `/v1/trade/margin` | Update Isolated Margin | Body payload (JSON) | 🔒 Signed (Proxy) |

### 9.3 Account, Portfolio & BLP

| Method & Endpoint | Summary / Purpose | Parameters | Auth |
| :--- | :--- | :--- | :--- |
| `POST` `/v1/account/proxy` | Create Proxy | Body payload (JSON) | 🔒 Auth (HMAC) |
| `DELETE` `/v1/account/proxy` | Delete Proxy | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/account/credentials` | Get Credentials | None | 🔒 Auth (HMAC) |
| `GET` `/v1/account/orders` | Get Orders | Opt: `order_id`, `client_order_id`, `instrument_id`, `start_timestamp`, `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/open-orders` | Get Open Orders | Opt: `instrument_id` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/balances` | Get Balances | None | 🔒 Auth (HMAC) |
| `GET` `/v1/account/portfolio` | Get Portfolio | None | 🔒 Auth (HMAC) |
| `GET` `/v1/account/fills` | Get Fills | Opt: `start_timestamp`, `end_timestamp`, `cursor`, `sort` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/equity` | Get Equity | **Req:** `interval`, `start_timestamp`<br>Opt: `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/pnl` | Get PnL | **Req:** `interval`, `start_timestamp`<br>Opt: `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/funding` | Get Funding Charges | Opt: `instrument_id`, `start_timestamp`, `end_timestamp` | 🔒 Auth (HMAC) |
| `POST` `/v1/account/withdraw` | Withdraw | Body payload (JSON) | 🔒 Auth (HMAC) |
| `POST` `/v1/account/internal-transfer` | Internal Transfer | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/account/deposits` | Get Deposits | Opt: `deposit_status`, `hash`, `start_timestamp`, `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/internal-transfers` | Get Internal Transfers | Opt: `start_timestamp`, `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/withdrawals` | Get Withdrawals | Opt: `withdrawal_status`, `hash`, `start_timestamp`, `end_timestamp` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/stats` | Get Account Stats | None | 🔒 Auth (HMAC) |
| `GET` `/v1/account/limits` | Get Account Limits | None | 🔒 Auth (HMAC) |
| `GET` `/v1/account/rewards` | Get Account Rewards | Opt: `date`, `start_date`, `end_date`, `limit` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/config` | Get Instrument Config | Opt: `instrument_id` | 🔒 Auth (HMAC) |
| `GET` `/v1/account/auto-cancel` | Get Auto-Cancel Status | None | 🔒 Auth (HMAC) |
| `POST` `/v1/account/invite` | Create Account Invite | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/account/referral` | Get Account Referral | None | 🔒 Auth (HMAC) |
| `POST` `/v1/account/referral` | Apply Referral Code | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/account/notifications` | Get Notifications | Opt: `cursor`, `since_seq`, `limit` | 🔒 Auth (HMAC) |
| `POST` `/v1/account/notifications/read` | Mark Notifications Read | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/blp/enrollment` | Get BLP Enrollment | None | 🔒 Auth (HMAC) |
| `POST` `/v1/blp/enroll` | Set BLP Instrument Subscription | Body payload (JSON) | 🔒 Auth (HMAC) |
| `GET` `/v1/blp/liquidations` | List BLP Liquidations | Opt: `start_timestamp`, `end_timestamp`, `cursor`, `sort` | 🔒 Auth (HMAC) |

## 10. WebSocket Real-Time Feeds

### 10.1 Predictions CLOB Market Stream
- **Endpoint**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- **Auth**: Public / Keyless
- **Subscriptions**: Orderbook changes (`book`), price updates (`price_change`), trade execution ticks (`last_trade_price`), and market lifecycle events.

### 10.2 Predictions CLOB User Stream
- **Endpoint**: `wss://ws-subscriptions-clob.polymarket.com/ws/user`
- **Auth**: Authenticated (requires initial auth message with L2 headers)
- **Subscriptions**: Private order placement confirmations, partial/full fills, cancellations, and margin/balance changes.

### 10.3 Real-Time Data Service (RTDS)
- **Endpoint**: `wss://ws-live-data.polymarket.com`
- **Auth**: Public
- **Subscriptions**: Broad-market trade ticks, aggregated volume metrics, and Chainlink-backed TWAP benchmarks.

### 10.4 Sports Live Updates Stream
- **Endpoint**: `wss://sports-api.polymarket.com/ws`
- **Auth**: Public
- **Subscriptions**: Live scores, game status (period, elapsed time, delays), and final settlements.

### 10.5 Combos RFQ Gateway Stream
- **Endpoint**: `wss://combos-rfq-api.polymarket.com/ws`
- **Auth**: Authenticated (Quoter role)
- **Subscriptions**: Stream incoming RFQ quote requests, submit real-time prices, and receive last-look execution confirmations.

### 10.6 Perps WebSocket Stream
- **Endpoint**: `wss://ws.perpetuals.polymarket.com/v1`
- **Auth**: Public for market data; Authenticated with token for private user feeds.
- **Channels**: `trades`, `bbo`, `book`, `klines`, `tickers`, `statistics`, `fills`, `orders`, `funding`, `balances`, `portfolio`, `notifications`.

## 11. Empirical Gotchas & Production Best Practices

These lessons reflect practical verification from real-world trading and indexing systems:

### 1. User Traded Markets Discovery
- **`GET /traded?user=`**: Returns `{user, traded: <count>}`. It is a count checksum, **not** a list.
- **`GET /trades?user=`**: Shallow fill history — only returns recent trades (often < 1,000 fills even for wallets with hundreds of thousands of transactions). Do not rely on it for full audit trails.
- **Complete Transaction History**: Use `GET /activity?user=` paginated inside sliding time windows (`start`/`end` timestamps). Note that `offset` caps at `5000` (requesting offset > 5000 returns `HTTP 400`). To crawl complete histories, window by timestamp epochs so each slice has < 5,000 events.
- **Open/Closed Positions Reconciliation**: Union `GET /positions?user=` + `GET /closed-positions?user=`. Be aware that `/closed-positions` **omits $0-expired losing outcomes** where no redemption transaction was submitted to the contract.

### 2. Gamma Metadata Parsing Gotchas
- **JSON strings inside JSON**: Fields such as `outcomes`, `outcomePrices`, and `clobTokenIds` on `/markets` and `/events` endpoints are returned as stringified JSON arrays (e.g. `'["Yes", "No"]'`). They must be decoded twice.
- **`conditionId` Filtering**: On `GET /markets?conditionId=...`, the parameter is ignored (verified Sep 2026: returns a generic list). The keyset endpoint does not fix this — `GET /markets/keyset?condition_ids=<full-66-char-id>` also returns `markets: []` (verified Sep 2026). Always look up by market `slug` (`GET /markets?slug=` / `GET /events?slug=`).
- **Token ID vs Condition ID**: `conditionId` represents the overall market on Polygon. `clobTokenIds` are ERC-1155 token IDs traded on the CLOB. Always match orders to `clobTokenIds`, not `conditionId`.

### 3. Pagination Standards
- **Keyset (Cursor) Pagination**: Modern endpoints (`/events/keyset`, `/markets/keyset`, `/rewards/user`, `/bridge/status/{address}`) use `next_cursor` / `after_cursor`. Passing `offset` to keyset endpoints will fail.
- **Last Page Indicators**: For CLOB Rewards (`/rewards/user`), a `next_cursor` value of `"LTE="` signals the last page.
- **Offset Wrapping**: Legacy `/positions` endpoints wrap around if `offset > 10000`, silently repeating the last page.

### 4. Rate Limiting & Reliability
- **Cloudflare IP Limits**: Public endpoints are capped by Cloudflare IP tiering (~1,000 req/10s per IP).
- **Order Rate Limits**: Token-bucket rate limiting applies to order creation and cancellation (~200 ops/10s). Use batch endpoints (`POST /orders`, `DELETE /orders`, `DELETE /cancel-all`) to conserve quota.
- **Dead Man's Switch**: For automated market makers, regularly invoke `POST /heartbeats` or set auto-cancel deadlines (`PATCH /v1/trade/auto-cancel` on Perps) to avoid resting stale quotes during network disconnections.

## 12. AI Research Hub API (Internal Platform API)

All Research Hub endpoints require the authenticated bearer identity. Workspace, chat, tab, panel, and result access is owner-scoped; a foreign or nonexistent ID returns `404 Not Found` without disclosing whether the resource exists.

### Workspace and Canvas Endpoints

| Method & Endpoint | Purpose | Notes |
| :--- | :--- | :--- |
| `POST /api/v2/research/workspaces` | Create a named workspace | Authenticated; creates exactly three fixed tabs: `Wallet Groups`, `Market Groups`, and `Agents`. |
| `GET /api/v2/research/workspaces` | List the caller's workspaces | Owner-scoped. |
| `GET /api/v2/research/workspaces/{workspace_id}` | Retrieve one workspace | Foreign IDs return `404`. |
| `PATCH /api/v2/research/workspaces/{workspace_id}` | Rename a workspace | Workspace name only; fixed tabs are not renamed through this endpoint. |
| `DELETE /api/v2/research/workspaces/{workspace_id}` | Delete an empty workspace | A workspace with chats is protected (`409`). |
| `GET /api/v2/research/workspaces/{workspace_id}/tabs` | Retrieve fixed tabs | Returns exactly the three database-backed tabs. Fixed tabs cannot be renamed or deleted. |
| `GET /api/v2/research/workspaces/{workspace_id}/panels` | List the permanent workspace canvas panels | Panels include nullable `source_chat_id`/`result_set_id` provenance and persisted layout/state/z-index. |

`POST /api/v2/research/chats` accepts optional `workspace_id` in its JSON body. When supplied, the workspace must belong to the caller; a foreign workspace returns `404`. If omitted, the service selects or creates the caller's default workspace. Chats remain the owner of messages, runs, immutable result snapshots, and chat-derived research positions; analytical runs upsert their panel into the selected workspace canvas rather than creating a chat-local canvas copy. Closing or deleting a source chat does not delete its workspace panel; its source-chat provenance becomes nullable.

### Positions Endpoint: `GET /api/v2/research/chats/{chat_id}/positions`

- **URL**: `/api/v2/research/chats/{chat_id}/positions`
- **Method**: `GET`
- **Authentication**: Authenticated Bearer token (`get_current_user`). Unauthenticated requests return `401 Unauthorized`.
- **Authorization & Scoping**:
  - `chat_id` must belong to the authenticated user (`owner_id = user["sub"]`). Inaccessible or non-existent chat IDs return `404 Not Found` without disclosing existence.
  - Queries wallets discovered in the authenticated chat's persisted result sets (`entity_type = 'wallet'`). Cross-chat or cross-owner wallets are strictly excluded in SQL.
- **Query Parameters**:
  - `offset` (integer, optional, default `0`, minimum `0`): Pagination offset.
  - `limit` (integer, optional, default `100`, minimum `1`, maximum `200`): Maximum rows returned per page.
- **Open Positions Predicate**:
  - Joins to `wallet_positions_v2` and `markets_v2`.
  - Filters strictly by `COALESCE(p.current_value, 0) > 0` and `COALESCE(p.is_resolved, FALSE) = FALSE`.
- **Ordering**:
  - Deterministic: `ORDER BY p.current_value DESC NULLS LAST, p.condition_id, p.outcome, p.address`.
- **Response Format (`application/json`)**:
  ```json
  {
    "positions": [
      {
        "address": "0x...",
        "condition_id": "0x...",
        "market_title": "Market title or null",
        "outcome": "YES",
        "size": 25.0,
        "avg_price": 0.5,
        "current_value": 12.5,
        "unrealized_pnl": 2.5,
        "entry_at": "2026-09-01T12:00:00Z",
        "computed_at": "2026-09-06T00:00:00Z"
      }
    ],
    "offset": 0,
    "limit": 100
  }
  ```

### Panel Mutation Endpoint: `PATCH /api/v2/research/panels/{panel_id}`

- **URL**: `/api/v2/research/panels/{panel_id}`
- **Method**: `PATCH`
- **Authentication**: Authenticated Bearer token (`get_current_user`). Unauthenticated requests return `401 Unauthorized`.
- **Authorization & Scoping**:
  - `panel_id` must belong to a workspace owned by the caller (`owner_id = user["sub"]`). Cross-user or foreign-workspace mutations return `404 Not Found`.
- **Request Body (`application/json`)**:
  - `state` (string, optional, enum: `"normal"`, `"minimized"`, `"maximized"`, `"closed"`): Updates visual presentation state.
  - `floating` (object, optional): Explicit 2D geometry rectangle:
    - `x` (integer, required, min 0, max 100000)
    - `y` (integer, required, min 0, max 100000)
    - `width` (integer, required, min 320, max 4096)
    - `height` (integer, required, min 240, max 4096)
  - `bring_to_front` (boolean, optional): When `true`, bumps panel's `z_index` atomically to `max(z_index) + 1` across all panels in the same workspace. If `z_index >= 1,000,000`, ranks are automatically compacted to dense positive ranks starting from 1.
- **Analytical Re-run Preservation**:
  - When background runs stream fresh analytical snapshots via `upsert_panel`, existing user geometry (`layout`) is strictly preserved (does not overwrite `layout`).
- **Response Format (`application/json`)**: Full `ResearchPanel` object with updated `state` and `layout`.

