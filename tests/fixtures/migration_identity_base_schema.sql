-- Starting shape for the identity/lifecycle provenance revision
-- (c2d3e4f5a6b7): the canonical v2 objects and the ownership ledger exactly as
-- they exist immediately after revision b1c2d3e4f5a6.  Only the objects that
-- revision c2d3e4f5a6b7 reads or modifies are reproduced here; the analytics
-- tables owned by b1c2d3e4f5a6 are irrelevant to this revision's contract.
CREATE TABLE wallets_v2 (
    address VARCHAR(42) PRIMARY KEY,
    username VARCHAR(255),
    tier VARCHAR(20) NOT NULL DEFAULT 'UNCLASSIFIED',
    tier_reason VARCHAR(50),
    might_cook_type VARCHAR(20),
    is_dormant BOOLEAN DEFAULT FALSE,
    last_trade_at TIMESTAMPTZ,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE markets_v2 (
    condition_id VARCHAR(255) PRIMARY KEY,
    title TEXT,
    description TEXT,
    image_url TEXT,
    category VARCHAR(50),
    subcategory VARCHAR(100),
    league VARCHAR(100) DEFAULT '',
    event_slug VARCHAR(255) DEFAULT '',
    status VARCHAR(20) DEFAULT 'ACTIVE',
    winning_outcome VARCHAR(255),
    winning_index INTEGER,
    resolved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE wallet_positions_v2 (
    address VARCHAR(42),
    condition_id VARCHAR(255),
    outcome VARCHAR(255),
    size NUMERIC,
    avg_price NUMERIC,
    current_value NUMERIC,
    unrealized_pnl NUMERIC,
    entry_at TIMESTAMPTZ,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    is_parlay BOOLEAN,
    is_resolved BOOLEAN,
    asset_token_id TEXT,
    PRIMARY KEY (address, condition_id, outcome)
);
CREATE TABLE wallet_closed_positions_v2 (
    address VARCHAR(42),
    condition_id VARCHAR(255),
    outcome VARCHAR(255),
    avg_buy_price NUMERIC,
    avg_sell_price NUMERIC,
    total_bought NUMERIC,
    total_sold NUMERIC,
    realized_pnl NUMERIC,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    n_trades INTEGER DEFAULT 1,
    is_parlay BOOLEAN,
    is_redeemable BOOLEAN,
    resolved_at TIMESTAMPTZ,
    data_quality_flag TEXT,
    metrics_eligible BOOLEAN,
    exclusion_reason TEXT,
    excluded_at TIMESTAMPTZ,
    source_asset TEXT,
    asset_token_id TEXT,
    source_realized_pnl NUMERIC,
    ledger_cost_basis NUMERIC,
    ledger_volume_usd NUMERIC,
    ledger_settlement_value NUMERIC,
    ledger_pnl NUMERIC,
    ledger_formula_version VARCHAR(64),
    ledger_provenance_version VARCHAR(64),
    settlement_included BOOLEAN,
    ledger_computed_at TIMESTAMPTZ,
    normalized_parlay_key TEXT,
    PRIMARY KEY (address, condition_id, outcome)
);
-- Ownership ledger created and owned by revision b1c2d3e4f5a6.
CREATE TABLE ledger_schema_objects_v2 (
    object_name TEXT PRIMARY KEY,
    object_kind TEXT NOT NULL,
    created_by_revision TEXT NOT NULL,
    preexisting BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO ledger_schema_objects_v2
    (object_name, object_kind, created_by_revision, preexisting)
VALUES ('ledger_schema_objects_v2', 'table', 'b1c2d3e4f5a6', FALSE);
