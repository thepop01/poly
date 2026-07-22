import asyncio
import aiohttp
from src.workers.leaderboard_stats import fetch_website_pnl

async def run():
    async with aiohttp.ClientSession() as s:
        print(await fetch_website_pnl(s, '0x204f72f35326db932158cba6adff0b9a1da95e14'))

asyncio.run(run())
