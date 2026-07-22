import asyncio, asyncpg, sys
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    conn = await asyncpg.connect('postgresql://poly_user:poly_password@localhost:5432/poly_db')
    
    # Check wallet_stats columns
    cols = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='wallet_stats' ORDER BY ordinal_position")
    print("wallet_stats columns:")
    for c in cols:
        print(f"  {c['column_name']}")
    
    # Check wallet_position_outcomes exists
    exists = await conn.fetchval("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='wallet_position_outcomes')")
    print(f"\nwallet_position_outcomes exists: {exists}")
    
    if exists:
        cols2 = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='wallet_position_outcomes' ORDER BY ordinal_position")
        print("wallet_position_outcomes columns:")
        for c in cols2:
            print(f"  {c['column_name']}")
    
    # Check the 5 wallets
    WALLETS = [
        '0xa20b482f97063f4f88ef621c9203e60814399940',
        '0x5d1d9cfd66ee3068c2a8a57dedf1e1b006dcafd2',
        '0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab',
        '0x160bf4f27cdaaaed1408ccd1558ab30c210d4296',
        '0xef185339944167fa992958c53bc371464a8b4d70',
    ]
    for addr in WALLETS:
        row = await conn.fetchrow('SELECT username, is_curated, last_indexed FROM tracked_wallets WHERE address=$1', addr)
        cp = await conn.fetchval('SELECT COUNT(*) FROM wallet_closed_positions WHERE address=$1', addr)
        po_count = await conn.fetchval('SELECT COUNT(*) FROM wallet_position_outcomes WHERE address=$1', addr) if exists else 0
        name = row['username'] if row and row['username'] else addr[:12]
        print(f"\n{name} ({addr[:14]}...): curated={row['is_curated'] if row else '?'}, last_indexed={row['last_indexed'] if row else '?'}, cp={cp}, outcomes={po_count}")
    
    await conn.close()

asyncio.run(main())
