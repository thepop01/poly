"""Verify that bad token IDs return Unknown instead of the default market."""
import asyncio
import aiohttp
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.utils.etherscan_client import _fetch_market_meta

async def test():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # Should return Unknown (token doesn't exist)
        result = await _fetch_market_meta(session, "99999999999999999999999999999999999999999999999999999999")
        print(f"Bad token: {json.dumps(result, indent=2)}")
        
        # Should return GTA VI (known good token)
        result2 = await _fetch_market_meta(session, "98022490269692409998126496127597032490334070080325855126491859374983463996227")
        print(f"GTA token: {json.dumps(result2, indent=2)}")

asyncio.run(test())
