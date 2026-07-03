"""add_alpha_calls_tables

Revision ID: 89f35540e1a5
Revises: c9fbbc21326e
Create Date: 2026-06-22 16:22:56.961337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89f35540e1a5'
down_revision: Union[str, Sequence[str], None] = '397e853462b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_admin to users
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT false;")
    
    # Create alpha_calls table
    op.execute("""
        CREATE TABLE IF NOT EXISTS alpha_calls (
            call_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source TEXT NOT NULL CHECK (source IN ('admin', 'user')),
            author_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            market_id VARCHAR(255) NOT NULL REFERENCES markets(market_id) ON DELETE CASCADE,
            call_direction TEXT NOT NULL CHECK (call_direction IN ('YES', 'NO')),
            call_price NUMERIC(10,6) NOT NULL,
            rationale TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved BOOLEAN DEFAULT false,
            call_outcome TEXT CHECK (call_outcome IN ('WIN', 'LOSS', 'VOID')),
            pnl_if_held NUMERIC(18,2)
        );
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpha_calls_source ON alpha_calls(source);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpha_calls_author ON alpha_calls(author_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpha_calls_market ON alpha_calls(market_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpha_calls_created ON alpha_calls(created_at DESC);")
    
    # Create user_call_history table
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_call_history (
            user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            total_calls INTEGER DEFAULT 0,
            resolved_calls INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            win_rate NUMERIC(5,4),
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    
    # Trigger for auto-update
    op.execute("""
        CREATE OR REPLACE FUNCTION update_user_call_history()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO user_call_history (user_id, total_calls, resolved_calls, wins, losses, win_rate, last_updated)
            SELECT 
                author_id,
                COUNT(*),
                COUNT(*) FILTER (WHERE resolved = true),
                COUNT(*) FILTER (WHERE call_outcome = 'WIN'),
                COUNT(*) FILTER (WHERE call_outcome = 'LOSS'),
                CASE 
                    WHEN COUNT(*) FILTER (WHERE resolved = true) > 0 
                    THEN CAST(COUNT(*) FILTER (WHERE call_outcome = 'WIN') AS NUMERIC) / COUNT(*) FILTER (WHERE resolved = true)
                    ELSE 0
                END,
                NOW()
            FROM alpha_calls
            WHERE author_id = NEW.author_id
            ON CONFLICT (user_id) 
            DO UPDATE SET
                total_calls = EXCLUDED.total_calls,
                resolved_calls = EXCLUDED.resolved_calls,
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                win_rate = EXCLUDED.win_rate,
                last_updated = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("DROP TRIGGER IF EXISTS trigger_update_call_history ON alpha_calls;")
    op.execute("""
        CREATE TRIGGER trigger_update_call_history
        AFTER INSERT OR UPDATE ON alpha_calls
        FOR EACH ROW EXECUTE FUNCTION update_user_call_history();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_update_call_history ON alpha_calls;")
    op.execute("DROP FUNCTION IF EXISTS update_user_call_history();")
    op.execute("DROP TABLE IF EXISTS user_call_history;")
    op.execute("DROP TABLE IF EXISTS alpha_calls;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin;")
