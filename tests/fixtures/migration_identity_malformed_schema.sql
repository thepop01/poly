-- A pre-existing evidence table whose exact token identity was lost: `asset`
-- is NUMERIC, so leading zeros and tokens wider than NUMERIC precision cannot
-- be recovered.  The identity/lifecycle provenance revision must fail closed
-- against this shape rather than adopt or rewrite it.
CREATE TABLE wallet_source_snapshots_v2 (
    id BIGSERIAL PRIMARY KEY,
    address VARCHAR(42) NOT NULL,
    source TEXT NOT NULL,
    complete BOOLEAN NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_sha256 TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_wallet_source_snapshots_address_v2
    ON wallet_source_snapshots_v2 (address, fetched_at DESC);
CREATE TABLE wallet_position_evidence_v2 (
    id BIGSERIAL PRIMARY KEY,
    address VARCHAR(42) NOT NULL,
    condition_id VARCHAR(255) NOT NULL,
    asset NUMERIC,
    outcome TEXT,
    evidence_type TEXT NOT NULL,
    transaction_hash VARCHAR(66),
    snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_wallet_position_evidence_lookup_v2
    ON wallet_position_evidence_v2 (address, condition_id, asset);
