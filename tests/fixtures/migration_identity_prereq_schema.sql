-- Evidence/decision objects exactly as produced by revision m6n7o8p9q0r1.
-- Applied on top of a base v2 fixture so the identity/lifecycle provenance
-- revision replays against the real ancestor shape instead of creating a
-- duplicate snapshot table.
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
    asset TEXT,
    outcome TEXT,
    evidence_type TEXT NOT NULL,
    transaction_hash VARCHAR(66),
    snapshot_id BIGINT NOT NULL REFERENCES wallet_source_snapshots_v2(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_wallet_position_evidence_lookup_v2
    ON wallet_position_evidence_v2 (address, condition_id, asset);
CREATE TABLE wallet_position_audit_decisions_v2 (
    id BIGSERIAL PRIMARY KEY,
    audit_id UUID NOT NULL,
    address VARCHAR(42) NOT NULL,
    condition_id VARCHAR(255) NOT NULL,
    outcome TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('eligible', 'review_required', 'excluded_proven')),
    reason TEXT NOT NULL,
    evidence_id BIGINT REFERENCES wallet_position_evidence_v2(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_wallet_position_audit_decisions_audit_v2
    ON wallet_position_audit_decisions_v2 (audit_id, address);
