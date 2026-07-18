"""add agent engine tables (agents, actions, events, notifications)

Revision ID: b1a2g3e4n5t6
Revises: a829c714e8cd
Create Date: 2026-07-18 12:00:00
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b1a2g3e4n5t6'
down_revision: Union[str, Sequence[str], None] = 'a829c714e8cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id        BIGSERIAL PRIMARY KEY,
            owner_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            name            VARCHAR(200) NOT NULL,
            description     TEXT,
            rule_tree       JSONB NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT FALSE,
            trading_armed   BOOLEAN NOT NULL DEFAULT FALSE,
            cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
            last_evaluated_at TIMESTAMPTZ,
            last_fired_at   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active) WHERE is_active = TRUE;")
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            action_id   BIGSERIAL PRIMARY KEY,
            agent_id    BIGINT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            action_type VARCHAR(16) NOT NULL CHECK (action_type IN ('notify','trade')),
            params      JSONB NOT NULL DEFAULT '{}'::jsonb,
            sort_order  INTEGER NOT NULL DEFAULT 0
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_actions_agent ON agent_actions(agent_id);")
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            event_id        BIGSERIAL PRIMARY KEY,
            agent_id        BIGINT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            fired           BOOLEAN NOT NULL DEFAULT FALSE,
            snapshot        JSONB,
            matched_summary TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id, created_at DESC);")
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id BIGSERIAL PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            agent_id        BIGINT REFERENCES agents(agent_id) ON DELETE SET NULL,
            title           VARCHAR(300) NOT NULL,
            body            TEXT,
            is_read         BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
    op.execute("DROP TABLE IF EXISTS agent_events;")
    op.execute("DROP TABLE IF EXISTS agent_actions;")
    op.execute("DROP TABLE IF EXISTS agents;")
