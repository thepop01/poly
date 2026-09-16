import asyncio
import asyncpg
import argparse
import os

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

SQL_WALLETS_V2 = """
INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
SELECT tw.address, tw.username,
  CASE
    WHEN COALESCE(tw.is_curated, FALSE) THEN 'CURATED'
    WHEN COALESCE(tw.balance,0) + COALESCE(tw.position_value,0) <= 0 THEN 'DEAD'
    WHEN COALESCE(tw.balance,0) + COALESCE(tw.position_value,0) < 1000 THEN 'LOW_BALANCE'
    WHEN tw.last_trade_at IS NULL THEN 'NEW'
    ELSE 'STANDARD'
  END,
  'backfill from tracked_wallets',
  COALESCE(tw.is_dormant, FALSE) OR (tw.last_trade_at IS NOT NULL AND tw.last_trade_at < NOW() - INTERVAL '30 days'),
  tw.last_trade_at, COALESCE(tw.added_at, NOW()), NOW()
FROM tracked_wallets tw
ON CONFLICT (address) DO NOTHING;
"""

SQL_SOURCES_V2 = """
INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
SELECT tw.address, tw.source_type, LEFT(tw.added_reason, 255), COALESCE(tw.added_at, NOW())
FROM tracked_wallets tw
WHERE tw.source_type IN ('trade','deposit','leaderboard','manual')
ON CONFLICT (address, source) DO NOTHING;
"""

SQL_METRICS_V2 = """
INSERT INTO wallet_metrics_v2 (address, total_pnl, total_volume, roi_pct, win_rate, resolved_count,
                               winning_count, balance, deposits, withdrawals, position_value,
                               pm_pnl, pm_volume, pm_rank, computed_at)
SELECT tw.address, tw.total_pnl, tw.total_volume, ws.roi_pct, ws.win_rate, ws.resolved_count,
       ws.winning_count, tw.balance, tw.deposits, tw.withdrawals, tw.position_value,
       tw.website_pnl, tw.website_volume, tw.website_rank, NOW()
FROM tracked_wallets tw
LEFT JOIN wallet_stats ws ON ws.address = tw.address
ON CONFLICT (address) DO NOTHING;
"""

SQL_CURATED = """
UPDATE wallets_v2 w SET tier = 'CURATED', curated_at = COALESCE(tw.curated_at, NOW())
FROM tracked_wallets tw
WHERE tw.address = w.address AND COALESCE(tw.is_curated, FALSE) AND w.tier NOT IN ('CURATED','DEAD');
"""

async def run_migration(apply: bool):
    conn = await asyncpg.connect(DB_URL)
    try:
        prefix = "" if apply else "[DRY RUN] "
        print("Applying migration..." if apply else "Dry run: executing inside a transaction, then rolling back...")

        tr = conn.transaction()
        await tr.start()
        try:
            status_wallets = await conn.execute(SQL_WALLETS_V2)
            print(f"{prefix}wallets_v2: {status_wallets}")

            status_sources = await conn.execute(SQL_SOURCES_V2)
            print(f"{prefix}wallet_sources_v2: {status_sources}")

            status_metrics = await conn.execute(SQL_METRICS_V2)
            print(f"{prefix}wallet_metrics_v2: {status_metrics}")

            status_curated = await conn.execute(SQL_CURATED)
            print(f"{prefix}curated updates: {status_curated}")
        except BaseException:
            await tr.rollback()
            raise

        if apply:
            await tr.commit()
        else:
            await tr.rollback()
            print("[DRY RUN] Rolled back. Run with --apply to commit.")

    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes to DB")
    args = parser.parse_args()
    asyncio.run(run_migration(args.apply))
