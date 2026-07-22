import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def run_migration():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found")
        return
        
    conn = await asyncpg.connect(db_url)
    try:
        # Add columns to tracked_wallets
        await conn.execute("""
            ALTER TABLE tracked_wallets 
            ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'ACTIVE';
        """)
        
        # Populate initial values for existing rows
        await conn.execute("""
            UPDATE tracked_wallets 
            SET last_active = NOW(),
                status = 'ACTIVE'
            WHERE last_active IS NULL;
        """)
        print("Migration successful: Added last_active, next_check_at, status to tracked_wallets")
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
