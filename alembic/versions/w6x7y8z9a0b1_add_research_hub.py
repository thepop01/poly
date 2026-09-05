"""Add persistent AI Research Hub workspace tables.

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9
Create Date: 2026-09-02
"""

from alembic import op


revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS research_chats (
    chat_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL DEFAULT 'New research',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""")
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_research_chats_owner_updated
    ON research_chats(owner_id, is_archived, updated_at DESC)""")
    op.execute("""
CREATE TABLE IF NOT EXISTS research_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
    prompt TEXT NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""")
    op.execute("""
CREATE TABLE IF NOT EXISTS research_messages (
    message_id BIGSERIAL PRIMARY KEY,
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_runs(run_id) ON DELETE SET NULL,
    role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','tool')),
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""")
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_research_messages_chat_created
    ON research_messages(chat_id, message_id)""")
    op.execute("""
CREATE TABLE IF NOT EXISTS research_result_sets (
    result_set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    run_id UUID REFERENCES research_runs(run_id) ON DELETE SET NULL,
    kind VARCHAR(40) NOT NULL,
    label VARCHAR(160) NOT NULL,
    definition JSONB NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""")
    op.execute("""
CREATE TABLE IF NOT EXISTS research_result_members (
    result_set_id UUID NOT NULL REFERENCES research_result_sets(result_set_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    entity_type VARCHAR(24) NOT NULL,
    entity_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (result_set_id, ordinal)
)""")
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_research_members_entity
    ON research_result_members(result_set_id, entity_type, entity_key)""")
    op.execute("""
CREATE TABLE IF NOT EXISTS research_panels (
    panel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES research_chats(chat_id) ON DELETE CASCADE,
    result_set_id UUID REFERENCES research_result_sets(result_set_id) ON DELETE SET NULL,
    panel_type VARCHAR(40) NOT NULL,
    panel_key VARCHAR(120) NOT NULL,
    title VARCHAR(160) NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'normal' CHECK (state IN ('normal','minimized','maximized','closed')),
    layout JSONB NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(chat_id, panel_key)
)""")
    # Analytical indexes over very large position tables (23M / 159M / 4.7M
    # rows). Built CONCURRENTLY outside the migration transaction so the
    # upgrade does not block writes for minutes. IF NOT EXISTS keeps the
    # migration idempotent if a previous attempt created them.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_wallet_positions_market_wallet
    ON wallet_positions_v2(condition_id, address, outcome)
    WHERE COALESCE(current_value, 0) > 0 AND COALESCE(is_resolved, FALSE) = FALSE""")
        op.execute("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_closed_positions_market_wallet
    ON wallet_closed_positions_v2(condition_id, address, outcome)
    WHERE COALESCE(metrics_eligible, TRUE)""")
        op.execute("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_category_stats_scope_winrate
    ON category_stats_v2(category, subcategory, league, window_size, win_rate DESC, resolved_count DESC)""")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_category_stats_scope_winrate")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_closed_positions_market_wallet")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_wallet_positions_market_wallet")
    op.execute("DROP TABLE IF EXISTS research_panels")
    op.execute("DROP TABLE IF EXISTS research_result_members")
    op.execute("DROP TABLE IF EXISTS research_result_sets")
    op.execute("DROP TABLE IF EXISTS research_messages")
    op.execute("DROP TABLE IF EXISTS research_runs")
    op.execute("DROP TABLE IF EXISTS research_chats")
