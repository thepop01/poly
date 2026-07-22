import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        url = "http://localhost:8000/api/v2/wallets/custom"
        payload = {"wallets": [{"address": "0x1234567890123456789012345678901234567890", "reason": "Test wallet"}]}
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            print(data)

if __name__ == "__main__":
    asyncio.run(main())
