"""add_sports_tables

Revision ID: 5dcace8f62d6
Revises: 47d850caf3df
Create Date: 2026-06-21 17:36:48.302244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dcace8f62d6'
down_revision: Union[str, Sequence[str], None] = '47d850caf3df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fixtures (
            fixture_id VARCHAR(255) PRIMARY KEY,
            sport VARCHAR(128) NOT NULL,
            league VARCHAR(255) NOT NULL,
            team_home VARCHAR(255) NOT NULL,
            team_away VARCHAR(255) NOT NULL,
            match_date TIMESTAMPTZ NOT NULL,
            status VARCHAR(64) NOT NULL DEFAULT 'upcoming',
            score_home INTEGER,
            score_away INTEGER
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            id SERIAL PRIMARY KEY,
            team_name VARCHAR(255) NOT NULL,
            sport VARCHAR(128) NOT NULL,
            form_last_10 VARCHAR(10) NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            UNIQUE(team_name, sport)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS match_lineups (
            id SERIAL PRIMARY KEY,
            fixture_id VARCHAR(255) REFERENCES fixtures(fixture_id),
            team VARCHAR(255) NOT NULL,
            lineup_type VARCHAR(64) NOT NULL CHECK(lineup_type IN ('starting', 'bench')),
            player_id VARCHAR(255) NOT NULL,
            position VARCHAR(64),
            confirmed BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS player_profiles (
            player_id VARCHAR(255) PRIMARY KEY,
            player_name VARCHAR(255) NOT NULL,
            sport VARCHAR(128) NOT NULL,
            team VARCHAR(255) NOT NULL,
            nationality VARCHAR(128),
            position VARCHAR(128),
            age INTEGER
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS injuries_suspensions (
            id SERIAL PRIMARY KEY,
            player_id VARCHAR(255) REFERENCES player_profiles(player_id),
            team VARCHAR(255) NOT NULL,
            type VARCHAR(64) NOT NULL,
            description TEXT,
            expected_return TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS player_stats_per_match (
            id SERIAL PRIMARY KEY,
            player_id VARCHAR(255) REFERENCES player_profiles(player_id),
            fixture_id VARCHAR(255) REFERENCES fixtures(fixture_id),
            minutes_played INTEGER,
            goals INTEGER,
            assists INTEGER,
            rating NUMERIC(4,2)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_sport_link (
            market_id VARCHAR(255) PRIMARY KEY,
            fixture_id VARCHAR(255) REFERENCES fixtures(fixture_id)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_sport_link CASCADE;")
    op.execute("DROP TABLE IF EXISTS player_stats_per_match CASCADE;")
    op.execute("DROP TABLE IF EXISTS injuries_suspensions CASCADE;")
    op.execute("DROP TABLE IF EXISTS player_profiles CASCADE;")
    op.execute("DROP TABLE IF EXISTS match_lineups CASCADE;")
    op.execute("DROP TABLE IF EXISTS team_stats CASCADE;")
    op.execute("DROP TABLE IF EXISTS fixtures CASCADE;")
