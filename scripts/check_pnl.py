import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://poly_user:poly_password@localhost:5432/poly_db")
    r = await conn.fetchrow("SELECT COUNT(*) as total, COUNT(website_pnl) as filled FROM tracked_wallets")
    total = r["total"]
    filled = r["filled"]
    print(f"Total: {total}, Filled: {filled}, Unfilled: {total - filled}")
    rows = await conn.fetch(
        "SELECT address, username, website_pnl, website_rank FROM tracked_wallets "
        "WHERE website_pnl IS NOT NULL ORDER BY website_pnl DESC LIMIT 5"
    )
    for r in rows:
        name = r["username"] or r["address"][:12]
        print(f"  {name}  pnl={r['website_pnl']}  rank=#{r['website_rank']}")
    await conn.close()

asyncio.run(main())
