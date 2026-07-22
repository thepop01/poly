import asyncio
import aiohttp
from src.workers.leaderboard_stats import fetch_all_trades
from src.utils.etherscan_client import fetch_historical_redemptions_polygonscan

async def test_trades():
    async with aiohttp.ClientSession() as session:
        addr = "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee"
        trades = await fetch_all_trades(session, addr)
        print(f"Fetched {len(trades)} trades")
        
        proxies = set(t.get("proxyWallet") for t in trades if t.get("proxyWallet") and isinstance(t.get("proxyWallet"), str))
        print(f"Proxies found: {proxies}")
        
        addresses = [addr] + list(proxies)
        print(f"Querying polygonscan for: {addresses}")
        redemptions = await fetch_historical_redemptions_polygonscan(session, addresses)
        print(f"Total Redemptions found: {len(redemptions)}")

if __name__ == "__main__":
    asyncio.run(test_trades())
