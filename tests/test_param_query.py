import asyncio
import asyncpg
import time
import os

async def main():
    conn = await asyncpg.connect(os.environ.get('DATABASE_URL', 'postgresql://poly_user:poly_password@localhost:5432/poly_db'))
    query = '''
            SELECT count(*)
            FROM wallets_v2 w
            JOIN wallet_metrics_v2 m ON w.address = m.address
            LEFT JOIN wallet_sources_v2 s ON w.address = s.address
            WHERE w.tier != 'DEAD'
            AND (m.balance + m.position_value) >= 1000
            AND w.last_trade_at >= NOW() - INTERVAL '30 days'
            AND s.source = $1
    '''
    start = time.time()
    res = await conn.fetchval(query, 'deposit')
    print("deposit count:", res)
    print(f"Time: {time.time() - start:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
