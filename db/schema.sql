-- Polymarket Analytics Platform — Phase 1 Schema
-- Idempotent: safe to re-run (uses IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS events (
    event_id        VARCHAR(64)  PRIMARY KEY,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    title           TEXT         NOT NULL,
    category        VARCHAR(64),
    tags            TEXT[]       NOT NULL DEFAULT '{}',
    topic_cluster   VARCHAR(64),
    keywords_json   JSONB        NOT NULL DEFAULT '[]',
    status          VARCHAR(32)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','resolved','cancelled')),
    created_at      TIMESTAMPTZ  NOT NULL,
    resolved_at     TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS markets (
    market_id           VARCHAR(64)  PRIMARY KEY,
    event_id            VARCHAR(64)  NOT NULL REFERENCES events(event_id),
    token_id            VARCHAR(66)  NOT NULL UNIQUE,
    slug                VARCHAR(255),
    title               TEXT         NOT NULL,
    outcome_label       VARCHAR(128),
    status              VARCHAR(32)  NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','resolved','cancelled','pending')),
    enable_order_book   BOOLEAN      NOT NULL DEFAULT false,
    current_price       NUMERIC(10,6) CHECK (current_price BETWEEN 0 AND 1),
    total_volume        NUMERIC(18,2) NOT NULL DEFAULT 0,
    liquidity           NUMERIC(18,2) NOT NULL DEFAULT 0,
    resolution_date     TIMESTAMPTZ,
    winning_outcome     VARCHAR(128),
    created_at          TIMESTAMPTZ  NOT NULL,
    resolved_at         TIMESTAMPTZ,
    last_updated        TIMESTAMPTZ  DEFAULT NOW(),
    fetched_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        BIGSERIAL    PRIMARY KEY,
    tx_hash         VARCHAR(66)  NOT NULL,
    wallet_address  VARCHAR(42)  NOT NULL,
    market_id       VARCHAR(64)  NOT NULL REFERENCES markets(market_id),
    token_id        VARCHAR(66)  NOT NULL,
    side            VARCHAR(4)   NOT NULL CHECK (side IN ('YES','NO')),
    price           NUMERIC(10,6) NOT NULL CHECK (price BETWEEN 0 AND 1),
    size            NUMERIC(18,2) NOT NULL CHECK (size > 0),
    fee             NUMERIC(18,2) NOT NULL DEFAULT 0,
    is_exit_trade   BOOLEAN      NOT NULL DEFAULT false,
    timestamp       TIMESTAMPTZ  NOT NULL,
    resolved_pnl    NUMERIC(18,2),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT trades_tx_hash_unique UNIQUE (tx_hash)
);
