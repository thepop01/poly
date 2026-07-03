"""remove deferred features

Revision ID: a1b2c3d4e5f6
Revises: 397e853462b3
Create Date: 2026-06-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '397e853462b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove deferred feature tables."""
    
    print("Removing deferred feature tables...")
    
    # Alert system tables (Telegram/Discord alerts - deferred in PRD §2)
    op.execute("DROP TABLE IF EXISTS alert_subscriptions CASCADE;")
    print("  [OK] Removed alert_subscriptions")
    
    op.execute("DROP TABLE IF EXISTS user_alert_channels CASCADE;")
    print("  [OK] Removed user_alert_channels")
    
    op.execute("DROP TABLE IF EXISTS alert_link_tokens CASCADE;")
    print("  [OK] Removed alert_link_tokens")
    
    # Custom alert rules (deferred in PRD §2)
    op.execute("DROP TABLE IF EXISTS custom_rules CASCADE;")
    print("  [OK] Removed custom_rules")
    
    # Cross-platform odds comparison (deferred in PRD §2)
    op.execute("DROP TABLE IF EXISTS odds_snapshots CASCADE;")
    print("  [OK] Removed odds_snapshots")
    
    # News feed per market (deferred in PRD §2)
    op.execute("DROP TABLE IF EXISTS market_news CASCADE;")
    print("  [OK] Removed market_news")
    
    # Market correlation engine (deferred in PRD §2)
    op.execute("DROP TABLE IF EXISTS market_correlations CASCADE;")
    print("  [OK] Removed market_correlations")
    
    # Event leaderboards (not in PRD scope)
    op.execute("DROP TABLE IF EXISTS event_leaderboards CASCADE;")
    print("  [OK] Removed event_leaderboards")
    
    print("[OK] Cleanup complete: Removed 8 deferred feature tables")


def downgrade() -> None:
    """Recreate tables if needed (from initial migration 19c895f4fbbb)."""
    
    # Alert tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_link_tokens (
            token VARCHAR(64) PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_alert_channels (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            channel_type VARCHAR(32) NOT NULL CHECK (channel_type IN ('telegram', 'discord')),
            chat_id VARCHAR(255) NOT NULL,
            status VARCHAR(32) DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, channel_type, chat_id)
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            rule_type VARCHAR(64) NOT NULL,
            threshold NUMERIC(18,2),
            status VARCHAR(32) DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, rule_type)
        );
    """)
    
    # Custom rules
    op.execute("""
        CREATE TABLE IF NOT EXISTS custom_rules (
            rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(user_id),
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            condition_type VARCHAR(64) NOT NULL,
            threshold NUMERIC(18,4) NOT NULL,
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_triggered_at TIMESTAMPTZ
        );
    """)
    
    # Odds snapshots
    op.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id BIGSERIAL PRIMARY KEY,
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            platform VARCHAR(64) NOT NULL,
            price_yes NUMERIC(10,6) NOT NULL,
            price_no NUMERIC(10,6) NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_odds_market on odds_snapshots(market_id, timestamp DESC);")
    
    # Market news
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_news (
            news_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            source VARCHAR(128),
            sentiment VARCHAR(32) DEFAULT 'neutral',
            published_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    
    # Market correlations
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_correlations (
            market_id_1 VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            market_id_2 VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            correlation_score NUMERIC(5,4) NOT NULL,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (market_id_1, market_id_2)
        );
    """)
    
    # Event leaderboards
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_leaderboards (
            event_id VARCHAR(255) NOT NULL REFERENCES events(event_id),
            wallet_address VARCHAR(42) NOT NULL,
            pnl NUMERIC(18,2) NOT NULL DEFAULT 0,
            roi NUMERIC(10,4) NOT NULL DEFAULT 0,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (event_id, wallet_address)
        );
    """)
