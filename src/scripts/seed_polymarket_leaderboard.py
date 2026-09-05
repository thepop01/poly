import asyncio
import os
import sys
import logging
import requests
import asyncpg
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    logger.info("Connecting to database...")
    conn = await asyncpg.connect(db_url)

    urls = [
        "https://lb-api.polymarket.com/profit",
        "https://lb-api.polymarket.com/volume"
    ]

    seen = set()

    for url in urls:
        logger.info(f"Fetching from {url}")
        res = requests.get(url, params={"limit": 500, "window": "all"})
        if res.status_code == 200:
            data = res.json()
            for item in data:
                wallet = item.get("proxyWallet", "").lower()
                username = item.get("pseudonym") or item.get("name")
                if username:
                    username = username[:20]
                if wallet and wallet not in seen:
                    seen.add((wallet, username))
        else:
            logger.error(f"Failed to fetch {url}: {res.status_code}")

    logger.info(f"Found {len(seen)} unique wallets from Polymarket leaderboards.")

    added = 0
    for wallet, username in seen:
        try:
            # Insert or update
            await conn.execute("""
                INSERT INTO tracked_wallets (address, username, is_curated, source_type, added_at, curated_at, is_dormant)
                VALUES ($1, $2, TRUE, 'leaderboard', NOW(), NOW(), FALSE)
                ON CONFLICT (address) DO UPDATE SET 
                    is_curated = TRUE, 
                    username = EXCLUDED.username,
                    curated_at = COALESCE(tracked_wallets.curated_at, NOW())
            """, wallet, username)
            added += 1
        except Exception as e:
            logger.error(f"Error adding {wallet}: {e}")

    logger.info(f"Successfully upserted {added} curated wallets.")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
