"""One-time backfill: compute wallet_tags for all tracked wallets.
Fetches recent trades (up to 500) for each wallet and classifies into categories.
Run once, then the leaderboard_stats worker maintains tags going forward."""

import asyncio
import asyncpg
import aiohttp
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")


def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def fetch_recent_trades(session: aiohttp.ClientSession, address: str, limit: int = 500) -> list[dict]:
    """Fetch recent trades for classification."""
    all_trades = []
    offset = 0
    page_limit = 500
    for role in ("maker", "taker"):
        offset = 0
        while len(all_trades) < limit:
            url = f"https://data-api.polymarket.com/trades?{role}={address}&limit={page_limit}&offset={offset}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if not data:
                        break
                    if not isinstance(data, list):
                        break
                    all_trades.extend(data)
                    if len(data) < page_limit:
                        break
                    offset += page_limit
            except Exception:
                break
    return all_trades[:limit]


async def backfill():
    from src.utils.category_classifier import classify_tags

    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT tw.address
            FROM tracked_wallets tw
            LEFT JOIN wallet_tags wt ON tw.address = wt.address
            WHERE wt.address IS NULL
            ORDER BY tw.added_at DESC
        """)
        addresses = [r["address"] for r in rows]
        print(f"Backfilling tags for {len(addresses)} wallets...")

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        async with pool.acquire() as conn:
            done = 0
            for addr in addresses:
                try:
                    trades = await fetch_recent_trades(session, addr, limit=500)
                    if not trades:
                        # No trades yet — assign "Other"
                        await conn.execute("""
                            INSERT INTO wallet_tags (address, category, subcategory, trade_count, top_markets, computed_at)
                            VALUES ($1, 'Other', 'General', 0, '{}', NOW())
                            ON CONFLICT (address) DO NOTHING
                        """, addr)
                        done += 1
                        continue

                    market_titles = []
                    market_counts: dict[str, int] = {}
                    for t in trades:
                        title = t.get("title") or t.get("market_name") or ""
                        if title:
                            market_titles.append(title)
                            market_counts[title] = market_counts.get(title, 0) + 1

                    category, subcategory = classify_tags(market_titles)
                    top_markets = sorted(market_counts.keys(), key=lambda k: market_counts[k], reverse=True)[:5]

                    await conn.execute("""
                        INSERT INTO wallet_tags (address, category, subcategory, trade_count, top_markets, computed_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        ON CONFLICT (address) DO UPDATE SET
                            category = EXCLUDED.category,
                            subcategory = EXCLUDED.subcategory,
                            trade_count = EXCLUDED.trade_count,
                            top_markets = EXCLUDED.top_markets,
                            computed_at = NOW()
                    """, addr, category, subcategory, len(trades), top_markets)

                    done += 1
                    if done % 100 == 0:
                        print(f"  {done}/{len(addresses)} wallets tagged...")
                    await asyncio.sleep(0.2)  # Rate limit

                except Exception as e:
                    logger.warning(f"Error tagging {addr[:10]}...: {e}")
                    continue

            print(f"Done! Tagged {done}/{len(addresses)} wallets.")

    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    asyncio.run(backfill())
