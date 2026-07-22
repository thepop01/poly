import asyncio
import asyncpg
import os
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from dotenv import load_dotenv
load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    query = """
        SELECT tw.address as wallet_address, 0 as amount_usdc, tw.added_at as deposited_at, 
        '' as tx_hash, 
        COALESCE(tw.total_pnl, 0) as total_pnl, 
        COALESCE(tw.website_pnl, 0) as website_pnl, 
        COALESCE(tw.balance, 0) as balance, 
        COALESCE(tw.position_value, 0) as position_value, 
        COALESCE(tw.resolved_count, 0) as resolved_count, 
        tw.win_rate, 
        tw.username, tw.source_type, wt.category, wt.subcategory, tw.last_trade_at 
        FROM tracked_wallets tw 
        LEFT JOIN wallet_tags wt ON tw.address = wt.address 
        WHERE tw.address = $1
    """
    res = await conn.fetchrow(query, '0x2d6938e8ab35f3f8538bee2eb239a8eba228bc81')
    r = dict(res)
    print("Raw dict:", r['balance'])
    
    # Try FastAPI JSON serialization
    encoded = jsonable_encoder(r)
    print("Encoded dict:", encoded['balance'])
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
