import asyncio
import aiohttp
from src.utils.etherscan_client import fetch_historical_redemptions_polygonscan

async def test_polygonscan():
    async with aiohttp.ClientSession() as session:
        addr = "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee"
        redemptions = await fetch_historical_redemptions_polygonscan(session, [addr])
        print(f"Redemptions found: {len(redemptions)}")
        
if __name__ == "__main__":
    asyncio.run(test_polygonscan())
