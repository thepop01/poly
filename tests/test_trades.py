import asyncio, aiohttp

async def run():
    async with aiohttp.ClientSession() as s:
        async with s.get('https://data-api.polymarket.com/trades?maker=0x00b08199144bd60ee0aa4f137f7e386b2c0f6cfe&limit=1') as resp:
            print(await resp.text())
        async with s.get('https://data-api.polymarket.com/trades?taker=0x00b08199144bd60ee0aa4f137f7e386b2c0f6cfe&limit=1') as resp2:
            print(await resp2.text())

asyncio.run(run())
