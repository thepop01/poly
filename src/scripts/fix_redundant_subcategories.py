"""Script to eliminate redundant and identical subcategories (e.g. CRYPTO -> Crypto)
and accurately classify Token Launches, Altcoins, DeFi, Memecoins, etc.
"""

import asyncio
import os
import sys
import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.category_classifier import classify_tags, flatten_subcategory

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")


def refine_crypto_subcategory(title: str, current_subcat: str) -> str:
    t = title.lower()
    if any(k in t for k in ["launch a token", "launch token", "token by", "token launch", "airdrop", "fdv above", "fdv"]):
        return "Token Launches"
    if any(k in t for k in ["bitcoin", "btc"]):
        return "Bitcoin"
    if any(k in t for k in ["ethereum", "eth ", "eth?", "ether"]):
        return "Ethereum"
    if any(k in t for k in ["solana", "sol ", "sol?"]):
        return "Solana"
    if any(k in t for k in ["memecoin", "meme coin", "doge", "shib", "pepe", "bonk", "wif"]):
        return "Memecoins"
    if any(k in t for k in ["defi", "uniswap", "aave", "lending", "tvl", "makerdao"]):
        return "DeFi"
    if any(k in t for k in ["stablecoin", "usdt", "usdc", "tether"]):
        return "Stablecoins"
    if any(k in t for k in ["nft", "opensea", "blur", "pfp"]):
        return "NFTs"
    if any(k in t for k in ["binance", "coinbase", "kraken", "bybit", "cz"]):
        return "Exchanges"
    if any(k in t for k in ["market cap", "total crypto"]):
        return "Market Cap"
    if current_subcat.lower() in ["crypto", "cryptocurrency", "general"]:
        return ""
    return current_subcat


async def fix_subcategories():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("1. Fetching all markets with redundant or generic subcategories...")
        rows = await conn.fetch("""
            SELECT condition_id, title, category, subcategory, league
            FROM markets_v2
            WHERE category IS NOT NULL AND category != ''
        """)
        print(f"Auditing {len(rows):,} markets in markets_v2...")

        updated_rows = []
        for r in rows:
            cid = r["condition_id"]
            title = r["title"] or ""
            cat = r["category"].upper()
            subcat = r["subcategory"] or ""
            league = r["league"] or ""

            # Check if subcat is identical or generic
            if cat == "CRYPTO":
                new_subcat = refine_crypto_subcategory(title, subcat)
            else:
                if subcat.strip().lower() in [cat.lower(), "general", "others"]:
                    new_subcat = ""
                else:
                    new_subcat = subcat

            if new_subcat != subcat:
                updated_rows.append((cid, new_subcat))

        print(f"2. Updating {len(updated_rows):,} markets with refined subcategories...")
        batch_size = 5000
        for i in range(0, len(updated_rows), batch_size):
            chunk = updated_rows[i:i + batch_size]
            await conn.executemany("""
                UPDATE markets_v2 SET subcategory = $2, updated_at = NOW()
                WHERE condition_id = $1
            """, chunk)

        # 3. Clean up empty/null subcategories in markets_v2
        await conn.execute("""
            UPDATE markets_v2 SET subcategory = '' 
            WHERE LOWER(subcategory) = LOWER(category) 
               OR LOWER(subcategory) IN ('general', 'crypto', 'cryptocurrency', 'sports', 'politics', 'tech', 'technology', 'finance', 'culture');
        """)

        print("\n3. Recomputing category_stats_v2 across all 3 tiers...")
        await conn.execute("DELETE FROM category_stats_v2;")

        # Insert Category-level stats
        print("  -> Inserting Category-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                '' AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER')
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        # Insert Subcategory-level stats
        print("  -> Inserting Subcategory-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                '' AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.subcategory IS NOT NULL AND m.subcategory != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        # Insert League-level stats
        print("  -> Inserting League-level stats...")
        await conn.execute("""
            INSERT INTO category_stats_v2 (
                address, category, subcategory, league, window_size, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, computed_at
            )
            SELECT
                c.address,
                COALESCE(NULLIF(m.category, ''), 'OTHER') AS category,
                m.subcategory AS subcategory,
                m.league AS league,
                0 AS window_size,
                COALESCE(SUM(c.realized_pnl), 0) AS pnl,
                COALESCE(SUM(c.total_bought), 0) AS volume,
                CASE WHEN COUNT(*) > 0 THEN (COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::numeric / COUNT(*)::numeric * 100.0) ELSE 0 END AS win_rate,
                CASE WHEN COALESCE(SUM(c.total_bought), 0) >= 10 THEN (COALESCE(SUM(c.realized_pnl), 0) / SUM(c.total_bought) * 100.0) ELSE 0 END AS roi_pct,
                COUNT(*)::int AS resolved_count,
                COUNT(*) FILTER (WHERE c.realized_pnl > 0 OR c.avg_sell_price >= 0.95)::int AS winning_count,
                NOW() AS computed_at
            FROM wallet_closed_positions_v2 c
            JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE m.league IS NOT NULL AND m.league != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory, m.league
            ON CONFLICT (address, category, subcategory, league, window_size) DO UPDATE SET
                pnl = EXCLUDED.pnl,
                volume = EXCLUDED.volume,
                win_rate = EXCLUDED.win_rate,
                roi_pct = EXCLUDED.roi_pct,
                resolved_count = EXCLUDED.resolved_count,
                winning_count = EXCLUDED.winning_count,
                computed_at = NOW();
        """)

        # 4. Verification on target wallet
        addr = "0xad5353afe30c2da57709e2704ef3ccdcf67eef24".lower()
        stats = await conn.fetch("""
            SELECT category, subcategory, league, resolved_count, winning_count, win_rate, pnl
            FROM category_stats_v2
            WHERE address = $1
            ORDER BY category, resolved_count DESC
        """, addr)
        print("\n" + "=" * 80)
        print(f"CLEANED CATEGORY STATS FOR {addr}:")
        print("=" * 80)
        for s in stats:
            cat = s['category']
            sub = f" -> {s['subcategory']}" if s['subcategory'] else " (Category Total)"
            lg = f" -> {s['league']}" if s['league'] else ""
            print(f"  {cat:<10}{sub:<25}{lg:<20} | {s['resolved_count']:>4} trades | Win%: {s['win_rate']:>5.1f}% | PnL: ${s['pnl']:>12,.2f}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(fix_subcategories())
