import asyncio
import os
import sys
import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.gamma_tag_resolver import resolve_gamma_tags
from src.utils.category_classifier import classify_tags, flatten_subcategory

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")
ADDR = "0xf0318c32136c2db7fec88b84869aee6a1106c80c".lower()

async def resolve_wallet_markets():
    conn = await asyncpg.connect(DB_URL)
    try:
        print(f"1. Finding all unique condition_ids for wallet {ADDR}...")
        cids = await conn.fetch("""
            SELECT DISTINCT c.condition_id
            FROM wallet_closed_positions_v2 c
            LEFT JOIN markets_v2 m ON c.condition_id = m.condition_id
            WHERE c.address = $1 AND (m.condition_id IS NULL OR m.category = 'OTHER' OR m.category IS NULL)
        """, ADDR)
        cid_list = [r["condition_id"] for r in cids]
        print(f"Found {len(cid_list)} condition_ids needing market metadata.")

        if not cid_list:
            print("All condition_ids are already categorized.")
            return

        print("2. Fetching metadata from CLOB API...")
        sem = asyncio.Semaphore(20)
        
        async def fetch_one(session, cid):
            async with sem:
                url = f"https://clob.polymarket.com/markets/{cid}"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            title = data.get("question") or ""
                            tags = data.get("tags") or []
                            slug = data.get("market_slug") or ""
                            icon = data.get("icon") or ""
                            
                            cat, subcat, league = "OTHER", "", ""
                            if tags:
                                cat, subcat, league = resolve_gamma_tags(tags)
                                cat = cat.upper()
                            
                            if cat == "OTHER" and title:
                                raw_c, raw_s = classify_tags([title])
                                if raw_c and raw_c.upper() != "OTHER":
                                    cat = raw_c.upper()
                                    subcat = flatten_subcategory(raw_c, raw_s)
                                    if cat == "SPORTS" and subcat == "Soccer":
                                        t_low = title.lower()
                                        if "fifa" in t_low or "world cup" in t_low or "fifwc" in slug.lower():
                                            league = "FIFA World Cup"
                                        elif "champions league" in t_low or "ucl" in t_low:
                                            league = "UEFA Champions League"
                                        elif "premier league" in t_low or "epl" in t_low:
                                            league = "Premier League"
                            
                            return (cid, title, icon, cat, subcat, league, slug)
                except Exception as e:
                    pass
                return (cid, "", "", "OTHER", "", "", "")

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            tasks = [fetch_one(session, cid) for cid in cid_list]
            resolved = await asyncio.gather(*tasks)

        print(f"3. Upserting {len(resolved)} markets into markets_v2...")
        valid_rows = [r for r in resolved if r[1] or r[3] != "OTHER"]
        print(f"Valid resolved markets: {len(valid_rows)} / {len(resolved)}")

        await conn.executemany("""
            INSERT INTO markets_v2 (
                condition_id, title, image_url, category, subcategory, league, event_slug, status, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'RESOLVED', NOW())
            ON CONFLICT (condition_id) DO UPDATE SET
                title = COALESCE(NULLIF(EXCLUDED.title, ''), markets_v2.title),
                image_url = COALESCE(NULLIF(EXCLUDED.image_url, ''), markets_v2.image_url),
                category = EXCLUDED.category,
                subcategory = EXCLUDED.subcategory,
                league = EXCLUDED.league,
                event_slug = COALESCE(NULLIF(EXCLUDED.event_slug, ''), markets_v2.event_slug),
                updated_at = NOW()
        """, resolved)

        # 4. Recomputing category_stats_v2 for this wallet
        print(f"4. Recomputing category_stats_v2 for {ADDR}...")
        await conn.execute("DELETE FROM category_stats_v2 WHERE address = $1;", ADDR)

        # Insert Category-level
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
            WHERE c.address = $1
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER')
        """, ADDR)

        # Insert Subcategory-level
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
            WHERE c.address = $1 AND m.subcategory IS NOT NULL AND m.subcategory != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory
        """, ADDR)

        # Insert League-level
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
            WHERE c.address = $1 AND m.league IS NOT NULL AND m.league != ''
            GROUP BY c.address, COALESCE(NULLIF(m.category, ''), 'OTHER'), m.subcategory, m.league
        """, ADDR)

        # 5. Print results
        final_stats = await conn.fetch("""
            SELECT category, subcategory, league, resolved_count, winning_count, win_rate, pnl
            FROM category_stats_v2
            WHERE address = $1
            ORDER BY resolved_count DESC
        """, ADDR)
        print("\n" + "=" * 90)
        print(f"UPDATED 3-TIER CATEGORY BREAKDOWN FOR {ADDR}:")
        print("=" * 90)
        for s in final_stats:
            cat_str = s['category']
            sub_str = f" -> {s['subcategory']}" if s['subcategory'] else ""
            lg_str = f" -> {s['league']}" if s['league'] else ""
            full_tax = f"{cat_str}{sub_str}{lg_str}"
            print(f"  {full_tax:<50} | {s['resolved_count']:>3} trades | Win%: {s['win_rate']:>5.1f}% | PnL: ${s['pnl']:>12,.2f}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(resolve_wallet_markets())
