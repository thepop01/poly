import asyncio, aiohttp
from src.workers.leaderboard_stats import fetch_website_pnl

async def run():
    async with aiohttp.ClientSession() as s:
        print(await fetch_website_pnl(s, '0x641b7aa42684b312a49260057f9db0103ca15d3c'))

asyncio.run(run())
