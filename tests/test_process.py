import asyncio, asyncpg, aiohttp, sys, logging, time
sys.stdout.reconfigure(encoding='utf-8')
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

WALLETS = [
    ('Leeche', '0xa20b482f97063f4f88ef621c9203e60814399940'),
    ('0x5d1d', '0x5d1d9cfd66ee3068c2a8a57dedf1e1b006dcafd2'),
    ('bhuumi', '0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab'),
    ('mortewfenloin', '0x160bf4f27cdaaaed1408ccd1558ab30c210d4296'),
    ('blbblb', '0xef185339944167fa992958c53bc371464a8b4d70'),
]

async def main():
    from src.workers.leaderboard_stats import process_wallet
    pool = await asyncpg.create_pool('postgresql://poly_user:poly_password@localhost:5432/poly_db', min_size=2, max_size=5)
    
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for name, addr in WALLETS:
            t0 = time.time()
            try:
                async with pool.acquire() as conn:
                    await asyncio.wait_for(process_wallet(conn, session, addr), timeout=300)
                elapsed = time.time() - t0
                async with pool.acquire() as conn:
                    ws = await conn.fetchrow('SELECT win_rate, resolved_count, winning_count, win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500 FROM wallet_stats WHERE address=$1', addr)
                    po = await conn.fetchval('SELECT COUNT(*) FROM wallet_position_outcomes WHERE address=$1', addr)
                d = dict(ws) if ws else {}
                print(f"{name}: OK {elapsed:.0f}s | outcomes={po} | wr={d.get('win_rate')} | resolved={d.get('resolved_count')} | wins={d.get('winning_count')} | wr100={d.get('win_rate_100')} wr300={d.get('win_rate_300')} wr800={d.get('win_rate_800')} wr1500={d.get('win_rate_1500')} wr2500={d.get('win_rate_2500')}")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"{name}: FAILED {elapsed:.0f}s - {type(e).__name__}: {e}")
    
    await pool.close()

asyncio.run(main())
