"""Directly add is_zero_balance column and stamp alembic."""
import asyncio
import os
import subprocess
from dotenv import load_dotenv
load_dotenv()
import asyncpg

async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    # Add column
    await conn.execute(
        "ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS is_zero_balance BOOLEAN DEFAULT FALSE"
    )
    print("Added is_zero_balance column")
    
    # Add index
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracked_wallets_zero_balance "
        "ON tracked_wallets (is_zero_balance) WHERE is_zero_balance = TRUE"
    )
    print("Added index")
    
    # Verify
    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
        "WHERE table_name='tracked_wallets' AND column_name='is_zero_balance')"
    )
    print(f"Column exists: {exists}")
    
    await conn.close()

asyncio.run(main())

# Stamp alembic
result = subprocess.run(
    ["python", "-m", "alembic", "stamp", "head"],
    capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
print("Alembic stamp stdout:", result.stdout)
print("Alembic stamp stderr:", result.stderr)
