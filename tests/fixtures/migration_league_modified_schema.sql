-- Ad-hoc replay fixture: the historical league helper already ran.
CREATE TABLE wallets_v2 (
    address VARCHAR(42) PRIMARY KEY,
    username VARCHAR(255),
    tier VARCHAR(20),
    is_dormant BOOLEAN,
    last_trade_at TIMESTAMPTZ
);
CREATE TABLE markets_v2 (
    condition_id VARCHAR(255) PRIMARY KEY,
    title TEXT,
    category VARCHAR(50),
    subcategory VARCHAR(100),
    league VARCHAR(100) DEFAULT '',
    event_slug VARCHAR(255) DEFAULT '',
    status VARCHAR(20)
);
CREATE TABLE wallet_metrics_v2 (
    address VARCHAR(42) PRIMARY KEY REFERENCES wallets_v2(address),
    total_pnl NUMERIC,
    total_volume NUMERIC,
    computed_at TIMESTAMPTZ
);
CREATE TABLE category_stats_v2 (
    address VARCHAR(42) NOT NULL REFERENCES wallets_v2(address),
    category VARCHAR(50) NOT NULL,
    subcategory VARCHAR(100) NOT NULL DEFAULT '',
    league VARCHAR(100) NOT NULL DEFAULT '',
    window_size INTEGER NOT NULL DEFAULT 0,
    pnl NUMERIC,
    volume NUMERIC,
    PRIMARY KEY (address, category, subcategory, league, window_size)
);
CREATE TABLE wallet_positions_v2 (
    address VARCHAR(42) NOT NULL,
    condition_id VARCHAR(255) NOT NULL,
    outcome VARCHAR(255) NOT NULL,
    size NUMERIC,
    is_parlay BOOLEAN,
    is_resolved BOOLEAN,
    asset_token_id TEXT,
    PRIMARY KEY (address, condition_id, outcome)
);
CREATE TABLE wallet_closed_positions_v2 (
    address VARCHAR(42) NOT NULL,
    condition_id VARCHAR(255) NOT NULL,
    outcome VARCHAR(255) NOT NULL,
    realized_pnl NUMERIC,
    closed_at TIMESTAMPTZ,
    is_parlay BOOLEAN,
    is_redeemable BOOLEAN,
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (address, condition_id, outcome)
);
