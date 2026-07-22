import asyncio
import asyncpg
import os

async def main():
    conn = await asyncpg.connect(os.environ.get('DATABASE_URL', 'postgresql://poly_user:poly_password@localhost:5432/poly_db'))
    query = '''
    SELECT COUNT(*) 
    FROM wallet_activity_v2 a
    LEFT JOIN markets_v2 m ON a.condition_id = m.condition_id
    JOIN wallets_v2 w ON a.address = w.address
    JOIN wallet_metrics_v2 wm ON a.address = wm.address
    WHERE (w.tier = 'CURATED' OR w.tier = 'MIGHT_COOK' OR wm.total_volume >= 10000)
    AND a.amount_usdc >= 1000
    AND a.event_type = 'TRADE'
    '''
    res = await conn.fetchval(query)
    print(f'Trade count in query: {res}')
    
    total = await conn.fetchval("SELECT count(*) FROM wallet_activity_v2 WHERE event_type = 'TRADE'")
    print(f'Total trades inserted: {total}')
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
