import asyncpg, asyncio

async def t():
    c = await asyncpg.connect("postgresql://poly_user:poly_password@localhost:5432/poly_db")
    r = await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    print("=== TABLES ===")
    for row in r:
        print(row["tablename"])
    
    for table in ["wallet_deposits", "smart_money_alerts", "tracked_wallets", "wallet_stats", "wallet_tags", "wallet_category_stats", "watchlist"]:
        r2 = await c.fetch(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position")
        print(f"\n=== {table} ({len(r2)} cols) ===")
        for row in r2:
            print(f"  {row['column_name']} ({row['data_type']})")
    await c.close()

asyncio.run(t())
