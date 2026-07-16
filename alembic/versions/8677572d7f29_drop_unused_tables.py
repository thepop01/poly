"""drop unused tables

Revision ID: 8677572d7f29
Revises: 8bec2d190c0f
Create Date: 2026-07-13 17:20:16.677115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8677572d7f29'
down_revision: Union[str, Sequence[str], None] = '8bec2d190c0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop unused sports-related tables
    op.drop_table('market_sport_link')
    op.drop_table('injuries_suspensions')
    op.drop_table('player_stats_per_match')
    op.drop_table('match_lineups')
    op.drop_table('team_stats')
    op.drop_table('player_profiles')
    op.drop_table('fixtures')
    
    # Drop unused watchlist tables
    op.drop_table('platform_watchlist')
    op.drop_table('user_wallet_watchlists')


def downgrade() -> None:
    """Downgrade schema."""
    pass
