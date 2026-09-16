import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")

TABLES_TO_DROP = [
    # 1. Obsolete V1 legacy tables with data (freeing ~3.5 GB)
    "curated_positions",
    "curated_position_sync",
    "wallet_position_outcomes",
    "wallet_subcategory_stats",
    "wallet_tags",
    "curated_category_tags",

    # 2. Dead / 0-row unused tables
    "users_v2",
    "user_tracked_wallets_v2",
    "price_ticks",
    "market_resolutions",
    "market_watchlists",
    "app_state_v2",
    "email_verifications",
]

async def drop_tables():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 70)
        print("DROPPING REDUNDANT / LEGACY TABLES")
        print("=" * 70)
        
        dropped_count = 0
        reclaimed_bytes = 0

        for tname in TABLES_TO_DROP:
            # Check if table exists
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = $1
                )
            """, tname)
            
            if exists:
                size_bytes = await conn.fetchval(f'SELECT pg_total_relation_size(\'"{tname}"\')')
                size_pretty = await conn.fetchval(f'SELECT pg_size_pretty(pg_total_relation_size(\'"{tname}"\'))')
                
                await conn.execute(f'DROP TABLE IF EXISTS "{tname}" CASCADE;')
                dropped_count += 1
                reclaimed_bytes += size_bytes
                print(f"  [DROPPED] {tname:<28} (Reclaimed: {size_pretty})")
            else:
                print(f"  [SKIPPED] {tname:<28} (Table does not exist)")

        pretty_reclaimed = await conn.fetchval("SELECT pg_size_pretty($1::bigint)", reclaimed_bytes)
        print("=" * 70)
        print(f"Successfully dropped {dropped_count} redundant tables.")
        print(f"Total Disk Space Reclaimed: {pretty_reclaimed}")
        print("=" * 70)

        # Show remaining active tables
        remaining = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        print(f"\nREMAINING ACTIVE TABLES ({len(remaining)} total):")
        for r in remaining:
            print(f"  - {r['table_name']}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(drop_tables())
