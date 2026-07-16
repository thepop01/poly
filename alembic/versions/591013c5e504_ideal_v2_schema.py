"""ideal_v2_schema

Revision ID: 591013c5e504
Revises: 8677572d7f29
Create Date: 2026-07-15 21:46:02.832504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '591013c5e504'
down_revision: Union[str, Sequence[str], None] = '8677572d7f29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE wallets_v2 (
        address         VARCHAR(42) PRIMARY KEY,
        username        VARCHAR(255),
        tier            VARCHAR(20) NOT NULL DEFAULT 'UNCLASSIFIED',
        tier_reason     VARCHAR(50),
        might_cook_type VARCHAR(20),
        is_dormant      BOOLEAN DEFAULT FALSE,
        last_trade_at   TIMESTAMPTZ,
        added_at        TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_wallets_tier_v2 ON wallets_v2 (tier) WHERE tier != 'DEAD';")

    op.execute("""
    CREATE TABLE wallet_sources_v2 (
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        source          VARCHAR(50) NOT NULL,
        source_detail   VARCHAR(255),
        spotted_at      TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (address, source)
    );
    """)

    op.execute("""
    CREATE TABLE wallet_metrics_v2 (
        address             VARCHAR(42) PRIMARY KEY REFERENCES wallets_v2(address),
        total_pnl           NUMERIC DEFAULT 0,
        total_volume        NUMERIC DEFAULT 0,
        roi_pct             NUMERIC DEFAULT 0,
        win_rate            NUMERIC DEFAULT 0,
        resolved_count      INT DEFAULT 0,
        winning_count       INT DEFAULT 0,
        balance             NUMERIC DEFAULT 0,
        deposits            NUMERIC DEFAULT 0,
        withdrawals         NUMERIC DEFAULT 0,
        position_value      NUMERIC DEFAULT 0,
        peak_capital        NUMERIC DEFAULT 0,
        avg_position_size   NUMERIC,
        avg_buy_price       NUMERIC,
        avg_hold_time_hours NUMERIC,
        biggest_win         NUMERIC,
        biggest_loss        NUMERIC,
        active_days         INT DEFAULT 0,
        trades_2x           INT DEFAULT 0,
        trades_1_5x         INT DEFAULT 0,
        pm_pnl              NUMERIC,
        pm_volume           NUMERIC,
        pm_rank             INT,
        computed_at         TIMESTAMPTZ DEFAULT NOW(),
        pm_synced_at        TIMESTAMPTZ
    );
    """)

    op.execute("""
    CREATE TABLE wallet_activity_v2 (
        id              BIGSERIAL PRIMARY KEY,
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        event_type      VARCHAR(20) NOT NULL,
        amount_usdc     NUMERIC NOT NULL,
        tx_hash         VARCHAR(66),
        condition_id    VARCHAR(255),
        outcome         VARCHAR(255),
        title           TEXT,
        event_at        TIMESTAMPTZ NOT NULL,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX idx_activity_type_time_v2 ON wallet_activity_v2 (event_type, event_at DESC);")
    op.execute("CREATE INDEX idx_activity_address_v2 ON wallet_activity_v2 (address, event_at DESC);")

    op.execute("""
    CREATE TABLE category_stats_v2 (
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        category        VARCHAR(50) NOT NULL,
        subcategory     VARCHAR(100) NOT NULL DEFAULT '',
        window_size     INT NOT NULL DEFAULT 0,
        pnl             NUMERIC DEFAULT 0,
        volume          NUMERIC DEFAULT 0,
        win_rate        NUMERIC DEFAULT 0,
        roi_pct         NUMERIC DEFAULT 0,
        resolved_count  INT DEFAULT 0,
        winning_count   INT DEFAULT 0,
        last_active     TIMESTAMPTZ,
        computed_at     TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (address, category, subcategory, window_size)
    );
    """)
    op.execute("CREATE INDEX idx_catstats_cat_window_v2 ON category_stats_v2 (category, window_size, pnl DESC);")
    op.execute("CREATE INDEX idx_catstats_address_v2 ON category_stats_v2 (address, window_size);")

    op.execute("""
    CREATE TABLE markets_v2 (
        condition_id    VARCHAR(255) PRIMARY KEY,
        title           TEXT,
        description     TEXT,
        image_url       TEXT,
        category        VARCHAR(50),
        subcategory     VARCHAR(100),
        status          VARCHAR(20) DEFAULT 'ACTIVE',
        winning_outcome VARCHAR(255),
        winning_index   INT,
        resolved_at     TIMESTAMPTZ,
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE wallet_positions_v2 (
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        condition_id    VARCHAR(255) REFERENCES markets_v2(condition_id),
        outcome         VARCHAR(255),
        size            NUMERIC,
        avg_price       NUMERIC,
        current_value   NUMERIC,
        unrealized_pnl  NUMERIC,
        entry_at        TIMESTAMPTZ,
        computed_at     TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (address, condition_id, outcome)
    );
    """)

    op.execute("""
    CREATE TABLE wallet_closed_positions_v2 (
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        condition_id    VARCHAR(255) REFERENCES markets_v2(condition_id),
        outcome         VARCHAR(255),
        avg_buy_price   NUMERIC,
        avg_sell_price  NUMERIC,
        total_bought    NUMERIC,
        total_sold      NUMERIC,
        realized_pnl    NUMERIC,
        opened_at       TIMESTAMPTZ,
        closed_at       TIMESTAMPTZ,
        n_trades        INT DEFAULT 1,
        PRIMARY KEY (address, condition_id, outcome)
    );
    """)
    op.execute("CREATE INDEX idx_closed_address_v2 ON wallet_closed_positions_v2 (address, closed_at DESC);")

    op.execute("""
    CREATE TABLE users_v2 (
        user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email           VARCHAR(255) UNIQUE,
        password_hash   VARCHAR(255),
        discord_id      VARCHAR(50),
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE TABLE user_tracked_wallets_v2 (
        user_id         UUID REFERENCES users_v2(user_id),
        address         VARCHAR(42) REFERENCES wallets_v2(address),
        alerts_enabled  BOOLEAN DEFAULT FALSE,
        added_at        TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (user_id, address)
    );
    """)

    op.execute("""
    CREATE TABLE app_state_v2 (
        key             VARCHAR(100) PRIMARY KEY,
        value           TEXT,
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    );
    """)

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS app_state_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_tracked_wallets_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS users_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallet_closed_positions_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallet_positions_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS markets_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS category_stats_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallet_activity_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallet_metrics_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallet_sources_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS wallets_v2 CASCADE;")
