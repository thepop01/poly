import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")

async def migrate():
    print(f"Connecting to database...")
    conn = await asyncpg.connect(DB_URL)
    try:
        print("1. Updating markets_v2 columns...")
        await conn.execute("""
            ALTER TABLE markets_v2 ADD COLUMN IF NOT EXISTS league VARCHAR(100) DEFAULT '';
            ALTER TABLE markets_v2 ADD COLUMN IF NOT EXISTS event_slug VARCHAR(255) DEFAULT '';
        """)
        print("markets_v2 updated.")

        print("2. Updating category_stats_v2 columns and primary key...")
        # Check if league column exists
        has_league = await conn.fetchval("""
            SELECT count(*) FROM information_schema.columns 
            WHERE table_name = 'category_stats_v2' AND column_name = 'league'
        """)
        if not has_league:
            await conn.execute("ALTER TABLE category_stats_v2 ADD COLUMN league VARCHAR(100) NOT NULL DEFAULT '';")

        # Drop old constraint and recreate PK with league
        print("Recreating primary key on category_stats_v2...")
        try:
            await conn.execute("ALTER TABLE category_stats_v2 DROP CONSTRAINT IF EXISTS category_stats_v2_pkey;")
            await conn.execute("""
                ALTER TABLE category_stats_v2 
                ADD PRIMARY KEY (address, category, subcategory, league, window_size);
            """)
            print("Primary key updated successfully.")
        except Exception as e:
            print(f"PK update warning: {e}")

        # Check indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_catstats_league_v2 ON category_stats_v2 (category, subcategory, league);
        """)
        print("Indexes created.")

        print("Migration complete!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
