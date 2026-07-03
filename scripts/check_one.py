import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://poly_user:poly_password@localhost:5432/poly_db")
    r = await conn.fetchrow(
        "SELECT address, website_pnl, website_pnl_updated_at FROM tracked_wallets WHERE address = $1",
        "0x7edb8d9e184f9747d6957dc3d54e1e8a0d6e7993"
    )
    print(dict(r))
    await conn.close()

asyncio.run(main())
