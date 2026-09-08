-- Historical replay shape after x7y8z9a0b1c2: NUMERIC token storage is not exact-safe.
-- The target migration must fail closed rather than cast or silently normalize it.
CREATE TABLE wallet_positions_v2 (
    address VARCHAR(42),
    condition_id VARCHAR(255),
    outcome VARCHAR(255),
    asset_token_id NUMERIC,
    PRIMARY KEY (address, condition_id, outcome)
);
CREATE TABLE wallet_closed_positions_v2 (
    address VARCHAR(42),
    condition_id VARCHAR(255),
    outcome VARCHAR(255),
    asset_token_id NUMERIC,
    PRIMARY KEY (address, condition_id, outcome)
);
