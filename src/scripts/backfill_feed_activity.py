import asyncio
import asyncpg
import aiohttp
import logging
from datetime import datetime, timezone
import sys, os

sys.path.insert(0, r"d:\project\poly")
from src.utils.category_classifier import classify_tags, flatten_subcategory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_feed_activity")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

async def backfill():
    conn = await asyncpg.connect(DB_URL)
    logger.info("Starting Activity Feed Backfill from Polymarket Data API...")

    # Fetch active wallets from DB
    wallets = await conn.fetch("""
        SELECT address FROM wallets_v2
        WHERE is_dormant = FALSE
        ORDER BY last_trade_at DESC NULLS LAST
        LIMIT 500
    """)
    addresses = [w["address"] for w in wallets]
    logger.info(f"Loaded {len(addresses)} active wallets to backfill activity for.")

    sem = asyncio.Semaphore(15)
    inserted_count = 0

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        async def _process_wallet(addr):
            nonlocal inserted_count
            async with sem:
                url = f"https://data-api.polymarket.com/activity?user={addr}&limit=50"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            return
                        data = await resp.json()
                        if not data or not isinstance(data, list):
                            return

                        for item in data:
                            act_type = (item.get("type") or "").upper()
                            # We track TRADE (BUY/SELL) and DEPOSIT
                            if act_type not in ("TRADE", "BUY", "SELL", "DEPOSIT"):
                                continue

                            amount = float(item.get("usdcSize") or item.get("size") or item.get("amount") or 0)
                            if amount < 5.0:
                                continue

                            tx_hash = item.get("transactionHash") or item.get("txHash") or f"api_sync_{addr[:8]}_{item.get('timestamp')}"
                            condition_id = item.get("conditionId")
                            title = item.get("title") or item.get("marketTitle") or ""
                            outcome = item.get("outcome") or act_type
                            
                            ts = item.get("timestamp")
                            if isinstance(ts, (int, float)) and ts > 0:
                                event_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                            else:
                                event_dt = datetime.now(timezone.utc)

                            event_kind = "DEPOSIT" if act_type == "DEPOSIT" else "TRADE"

                            # Insert market into markets_v2 if missing
                            if condition_id and title:
                                cat, sub = classify_tags([title])
                                await conn.execute("""
                                    INSERT INTO markets_v2 (condition_id, title, category, subcategory)
                                    VALUES ($1, $2, $3, $4)
                                    ON CONFLICT (condition_id) DO NOTHING
                                """, condition_id, title, cat, flatten_subcategory(cat, sub))

                            # Check if tx_hash already exists
                            exists = await conn.fetchval(
                                "SELECT 1 FROM wallet_activity_v2 WHERE tx_hash = $1 AND event_type = $2", tx_hash, event_kind
                            )
                            if not exists:
                                await conn.execute("""
                                    INSERT INTO wallet_activity_v2 (
                                        address, event_type, amount_usdc, tx_hash, condition_id, outcome, title, event_at, created_at
                                    )
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                                """, addr, event_kind, amount, tx_hash, condition_id, outcome, title, event_dt)
                                inserted_count += 1


                except Exception as e:
                    pass

        tasks = [_process_wallet(a) for a in addresses]
        await asyncio.gather(*tasks)

    logger.info(f"Backfill complete! Inserted {inserted_count} new activity records into wallet_activity_v2.")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(backfill())
