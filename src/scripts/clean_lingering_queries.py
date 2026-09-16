import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")

async def check():
    conn = await asyncpg.connect(DB_URL)
    try:
        # Cancel any lingering SELECT query (not VACUUM)
        lingering = await conn.fetch("""
            SELECT pid, query 
            FROM pg_stat_activity 
            WHERE state != 'idle' AND query LIKE '%SELECT count(DISTINCT condition_id)%'
        """)
        for l in lingering:
            print(f"Cancelling lingering query on PID {l['pid']}...")
            await conn.execute("SELECT pg_cancel_backend($1)", l["pid"])

        # Check remaining
        active = await conn.fetch("""
            SELECT pid, state, query_start, query 
            FROM pg_stat_activity 
            WHERE state != 'idle' AND pid != pg_backend_pid()
        """)
        print("\nCurrent Active DB Activities:")
        for a in active:
            print(f"  PID {a['pid']}: {a['state']} -> {a['query'][:90]}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
