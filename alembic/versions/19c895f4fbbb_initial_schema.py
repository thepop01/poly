"""initial schema

Revision ID: 19c895f4fbbb
Revises: 
Create Date: 2026-06-21 12:57:51.164971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19c895f4fbbb'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Phase 1
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id VARCHAR(255) PRIMARY KEY,
            slug VARCHAR(255) NOT NULL UNIQUE,
            title TEXT NOT NULL,
            category VARCHAR(255),
            tags TEXT[] NOT NULL DEFAULT '{}',
            topic_cluster VARCHAR(64),
            keywords_json JSONB NOT NULL DEFAULT '[]',
            status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','cancelled')),
            created_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            market_id VARCHAR(255) PRIMARY KEY,
            event_id VARCHAR(255) NOT NULL REFERENCES events(event_id),
            token_id VARCHAR(255) NOT NULL UNIQUE,
            slug VARCHAR(255),
            title TEXT NOT NULL,
            outcome_label VARCHAR(128),
            status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','cancelled','pending')),
            enable_order_book BOOLEAN NOT NULL DEFAULT false,
            current_price NUMERIC(10,6) CHECK (current_price BETWEEN 0 AND 1),
            total_volume NUMERIC(18,2) NOT NULL DEFAULT 0,
            liquidity NUMERIC(18,2) NOT NULL DEFAULT 0,
            resolution_date TIMESTAMPTZ,
            winning_outcome VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id BIGSERIAL PRIMARY KEY,
            tx_hash VARCHAR(255) NOT NULL,
            wallet_address VARCHAR(42) NOT NULL,
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            token_id VARCHAR(255) NOT NULL,
            side VARCHAR(4) NOT NULL CHECK (side IN ('YES','NO')),
            price NUMERIC(10,6) NOT NULL CHECK (price BETWEEN 0 AND 1),
            size NUMERIC(18,2) NOT NULL CHECK (size > 0),
            fee NUMERIC(18,2) NOT NULL DEFAULT 0,
            is_exit_trade BOOLEAN NOT NULL DEFAULT false,
            timestamp TIMESTAMPTZ NOT NULL,
            resolved_pnl NUMERIC(18,2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT trades_tx_hash_unique UNIQUE (tx_hash)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS price_ticks (
            tick_id BIGSERIAL PRIMARY KEY,
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            token_id VARCHAR(255) NOT NULL,
            price NUMERIC(10,6) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_price_ticks_market ON price_ticks(market_id, timestamp DESC);")
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlists (
            wallet_address VARCHAR(42) PRIMARY KEY,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_stats (
            address VARCHAR(42) PRIMARY KEY,
            win_rate NUMERIC(5,4),
            roi_pct NUMERIC(10,4),
            resolved_count INTEGER DEFAULT 0,
            winning_count INTEGER DEFAULT 0,
            total_volume NUMERIC(18,2) DEFAULT 0,
            total_pnl NUMERIC(18,2) DEFAULT 0,
            avg_position_size NUMERIC(18,2),
            avg_hold_time_hours NUMERIC(10,2),
            biggest_win NUMERIC(18,2),
            biggest_loss NUMERIC(18,2),
            unrealised_pnl NUMERIC(18,2) DEFAULT 0,
            tier VARCHAR(32),
            strategy VARCHAR(64),
            active_days INTEGER DEFAULT 0,
            favourite_category VARCHAR(128),
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            wallet_address VARCHAR(42),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            token VARCHAR(255) PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_verifications (
            token VARCHAR(255) PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(user_id),
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    # Phase 3
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
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_new_trade()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('new_trade_channel', row_to_json(NEW)::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trigger_new_trade ON trades;")
    op.execute("""
        CREATE TRIGGER trigger_new_trade
        AFTER INSERT ON trades
        FOR EACH ROW EXECUTE FUNCTION notify_new_trade();
    """)
    # Phase 4
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_watchlists (
            user_id UUID NOT NULL REFERENCES users(user_id),
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            notify_spike BOOLEAN DEFAULT false,
            notify_new_outcome BOOLEAN DEFAULT false,
            notify_resolved BOOLEAN DEFAULT false,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, market_id)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_resolutions (
            market_id VARCHAR(255) PRIMARY KEY REFERENCES markets(market_id),
            winning_token_id VARCHAR(255),
            winning_outcome VARCHAR(128),
            resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payout_processed BOOLEAN DEFAULT false
        );
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_market_event()
        RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('market_events_channel', json_build_object(
                'event_type', 'resolution',
                'data', row_to_json(NEW)
            )::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trigger_market_resolution ON market_resolutions;")
    op.execute("""
        CREATE TRIGGER trigger_market_resolution
        AFTER INSERT ON market_resolutions
        FOR EACH ROW EXECUTE FUNCTION notify_market_event();
    """)
    # Phase 5
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
    # Phase 6
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_correlations (
            market_id_1 VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            market_id_2 VARCHAR(255) NOT NULL REFERENCES markets(market_id),
            correlation_score NUMERIC(5,4) NOT NULL,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (market_id_1, market_id_2)
        );
    """)
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
    # Phase 7
    op.execute("""
        CREATE TABLE IF NOT EXISTS fixtures (
            fixture_id VARCHAR(255) PRIMARY KEY,
            sport VARCHAR(128) NOT NULL,
            league VARCHAR(128),
            team_home VARCHAR(128) NOT NULL,
            team_away VARCHAR(128) NOT NULL,
            match_date TIMESTAMPTZ NOT NULL,
            status VARCHAR(64) DEFAULT 'upcoming',
            score_home INTEGER,
            score_away INTEGER,
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_sport_link (
            market_id VARCHAR(255) PRIMARY KEY REFERENCES markets(market_id),
            fixture_id VARCHAR(255) NOT NULL REFERENCES fixtures(fixture_id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            team_name VARCHAR(128) NOT NULL,
            sport VARCHAR(128) NOT NULL,
            form_last_10 VARCHAR(10),
            wins INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (team_name, sport)
        );
    """)
    # Phase 8
    op.execute("""
        CREATE TABLE IF NOT EXISTS player_profiles (
            player_id VARCHAR(255) PRIMARY KEY,
            player_name VARCHAR(255) NOT NULL,
            sport VARCHAR(128) NOT NULL,
            team VARCHAR(128) NOT NULL,
            nationality VARCHAR(128),
            position VARCHAR(64),
            age INTEGER,
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS player_stats_per_match (
            id SERIAL PRIMARY KEY,
            player_id VARCHAR(255) NOT NULL REFERENCES player_profiles(player_id),
            fixture_id VARCHAR(255) NOT NULL REFERENCES fixtures(fixture_id),
            minutes_played INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            rating NUMERIC(4,2),
            sport_specific_stats_json JSONB,
            UNIQUE(player_id, fixture_id)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_lineups (
            id SERIAL PRIMARY KEY,
            fixture_id VARCHAR(255) NOT NULL REFERENCES fixtures(fixture_id),
            team VARCHAR(128) NOT NULL,
            player_id VARCHAR(255) NOT NULL REFERENCES player_profiles(player_id),
            lineup_type VARCHAR(32) NOT NULL,
            position VARCHAR(64),
            confirmed BOOLEAN DEFAULT true,
            UNIQUE(fixture_id, player_id)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS injuries_suspensions (
            id SERIAL PRIMARY KEY,
            player_id VARCHAR(255) NOT NULL REFERENCES player_profiles(player_id),
            team VARCHAR(128) NOT NULL,
            type VARCHAR(64) NOT NULL,
            description TEXT,
            expected_return TIMESTAMPTZ,
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(player_id)
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trigger_market_resolution ON market_resolutions;")
    op.execute("DROP FUNCTION IF EXISTS notify_market_event();")
    op.execute("DROP TRIGGER IF EXISTS trigger_new_trade ON trades;")
    op.execute("DROP FUNCTION IF EXISTS notify_new_trade();")
    
    tables = [
        "injuries_suspensions", "match_lineups", "player_stats_per_match", "player_profiles",
        "team_stats", "market_sport_link", "fixtures",
        "event_leaderboards", "market_correlations",
        "market_news", "odds_snapshots", "custom_rules",
        "market_resolutions", "market_watchlists",
        "alert_subscriptions", "user_alert_channels", "alert_link_tokens",
        "email_verifications", "refresh_tokens", "users",
        "wallet_stats", "user_watchlists", "price_ticks", "trades", "markets", "events"
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
