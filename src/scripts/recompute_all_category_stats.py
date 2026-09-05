import asyncio
import os
import sys
import logging
import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("recompute_category_stats")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")


async def recompute():
    logger.info("Connecting to database...")
    conn = await asyncpg.connect(DB_URL)
    try:
        logger.info("1. Auditing leagues in markets_v2...")
        soccer_leagues = await conn.fetch("""
            SELECT league, count(*) as cnt
            FROM markets_v2
            WHERE category = 'SPORTS' AND subcategory = 'Soccer' AND league != ''
            GROUP BY league
            ORDER BY count(*) DESC LIMIT 15
        """)
        logger.info("Top Soccer Leagues in markets_v2:")
        for r in soccer_leagues:
            logger.info(f"  Soccer -> {r['league']}: {r['cnt']} markets")

        logger.info("\n2. Recomputing category_stats_v2 for all wallets from closed positions...")
        # Clear old category_stats_v2 rows
        await conn.execute("DELETE FROM category_stats_v2;")

        # Insert Category-level stats (category, subcategory='', league='')
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                '' AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER')
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)
        logger.info("Category-level stats inserted.")

        # Insert Subcategory-level stats (category, subcategory, league='')
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.subcategory IS NOT NULL AND m.subcategory != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)
        logger.info("Subcategory-level stats inserted.")

        # Insert League-level stats (category, subcategory, league)
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                m.league AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.league IS NOT NULL AND m.league != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory, m.league
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)
        logger.info("League-level stats inserted.")

        # Count total rows in category_stats_v2
        total_rows = await conn.fetchval("SELECT count(*) FROM category_stats_v2;")
        logger.info(f"Total category_stats_v2 rows recomputed: {total_rows}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(recompute())
