import asyncpg, asyncio
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def inspect_db():
    c = await asyncpg.connect(DATABASE_URL)
    tables = await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    
    for row in tables:
        table = row["tablename"]
        print(f"\n=== Table: {table} ===")
        
        # Get count
        count = await c.fetchval(f"SELECT COUNT(*) FROM {table}")
        print(f"Total Rows: {count}")
        
        # Get columns
        columns = await c.fetch(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position")
        print("Columns:")
        for col in columns:
            print(f"  - {col['column_name']}: {col['data_type']}")
            
    await c.close()

if __name__ == "__main__":
    asyncio.run(inspect_db())
