import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://poly_user:poly_password@localhost:5432/poly_db")
    cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = 'tracked_wallets' AND column_name IN
        ('website_pnl','website_volume','website_rank','username','website_pnl_updated_at','position_value')
        ORDER BY column_name
    """)
    for c in cols:
        print(f"  {c['column_name']}: {c['data_type']}")
    print()
    ws_cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = 'wallet_stats' AND column_name IN ('unrealised_pnl','unrealized_pnl','biggest_win','biggest_loss','active_days')
        ORDER BY column_name
    """)
    print("wallet_stats:")
    for c in ws_cols:
        print(f"  {c['column_name']}: {c['data_type']}")
    await conn.close()

asyncio.run(main())
