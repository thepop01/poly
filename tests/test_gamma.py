"""Quick test to verify Gamma API category fetching."""
import asyncio
import aiohttp
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

async def test():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # Direct test: query events by specific known-sports IDs
        for eid in ["2890", "2891", "2904"]:
            async with session.get(f"https://gamma-api.polymarket.com/events?id={eid}", timeout=10) as r:
                ev = await r.json()
                if ev:
                    print(f"Event {eid}: category={ev[0].get('category')} title={ev[0].get('title','')[:60]}")
        
        # Now find a market with event_id=2890 (Sports)
        async with session.get("https://gamma-api.polymarket.com/markets?limit=50", timeout=10) as r:
            mks = await r.json()
            found = None
            for mk in mks:
                events = mk.get("events", [])
                for ev in events:
                    if ev.get("id") in ("2890", "2891", "2892", "2904"):
                        found = mk
                        break
                if found:
                    break
            
            if found:
                tids = json.loads(found.get("clobTokenIds", "[]"))
                print(f"\nFound market: {found.get('question','')[:60]}")
                print(f"Events: {[e.get('id') for e in found.get('events',[])]}")
                print(f"Token IDs: {tids}")
                
                # Now test _fetch_market_meta
                from src.utils.etherscan_client import _fetch_market_meta
                result = await _fetch_market_meta(session, str(tids[0]))
                print(f"\nMeta result: {json.dumps(result, indent=2)}")
            else:
                print("No matching market found in first 50")

asyncio.run(test())
