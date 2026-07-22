import asyncio, asyncpg, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(".")))
from dotenv import load_dotenv
load_dotenv()

async def main():
    db_url = os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(db_url)
    
    row = await conn.fetchrow("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE COALESCE(m.balance, 0) = 0) as zero_balance,
            COUNT(*) FILTER (WHERE COALESCE(m.position_value, 0) = 0) as zero_position,
            COUNT(*) FILTER (WHERE COALESCE(m.balance, 0) > 0) as has_balance,
            COUNT(*) FILTER (WHERE COALESCE(m.position_value, 0) > 0) as has_position,
            COUNT(*) FILTER (WHERE m.address IS NULL) as no_metrics
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE w.tier != 'DEAD'
    """)
    
    print("=== Wallet Balance/Position Status (non-DEAD wallets) ===")
    print(f"Total wallets:        {row['total']}")
    print(f"Has balance > 0:      {row['has_balance']}")
    print(f"Zero balance:         {row['zero_balance']}")
    print(f"Has position > 0:     {row['has_position']}")
    print(f"Zero position:        {row['zero_position']}")
    print(f"No metrics row:       {row['no_metrics']}")
    
    # Show sample wallets with 0 balance
    zero_bal = await conn.fetch("""
        SELECT w.address, w.tier, w.username, 
               COALESCE(m.balance, 0) as bal,
               COALESCE(m.position_value, 0) as pos
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE w.tier != 'DEAD' AND COALESCE(m.balance, 0) = 0
        ORDER BY w.added_at DESC LIMIT 5
    """)
    print("\n=== Sample wallets with $0 balance ===")
    for r in zero_bal:
        print(f"  {r['address'][:10]}... tier={r['tier']} user={r['username']} bal={r['bal']} pos={r['pos']}")
    
    await conn.close()

asyncio.run(main())
