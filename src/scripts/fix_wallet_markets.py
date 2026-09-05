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

async def fix_wallet(address: str):
    addr = address.lower()
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 80)
        print(f"FETCHING ALL CLOSED POSITIONS FOR {addr} FROM POLYMARKET API...")
        print("=" * 80)
        all_positions = []
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            offset = 0
            while True:
                url = f"https://data-api.polymarket.com/closed-positions?user={addr}&limit=100&offset={offset}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if not data or not isinstance(data, list):
                        break
                    all_positions.extend(data)
                    if len(data) < 100:
                        break
                    offset += len(data)

            print(f"Total closed positions fetched from API: {len(all_positions)}")

            # Extract unique condition_ids
            unique_markets = {}
            for p in all_positions:
                cid = p.get("conditionId")
                if not cid:
                    continue
                if cid not in unique_markets:
                    unique_markets[cid] = {
                        "condition_id": cid,
                        "title": p.get("title") or "",
                        "event_slug": p.get("eventSlug") or "",
                        "slug": p.get("slug") or "",
                        "icon": p.get("icon") or "",
                    }

            print(f"Unique condition_ids to classify: {len(unique_markets)}")

            # Resolve in parallel
            sem = asyncio.Semaphore(25)
            async def resolve_one(m):
                async with sem:
                    event_slug = m["event_slug"]
                    title = m["title"]
                    cat, subcat, league = "OTHER", "", ""
                    
                    if event_slug:
                        try:
                            g_url = f"https://gamma-api.polymarket.com/events?slug={event_slug}"
                            async with session.get(g_url, timeout=aiohttp.ClientTimeout(total=6)) as g_resp:
                                if g_resp.status == 200:
                                    g_data = await g_resp.json()
                                    if g_data and isinstance(g_data, list) and len(g_data) > 0:
                                        tags_raw = g_data[0].get("tags", [])
                                        labels = [t["label"] for t in tags_raw if isinstance(t, dict) and "label" in t]
                                        if labels:
                                            cat, subcat, league = resolve_gamma_tags(labels)
                                            cat = cat.upper()
                        except Exception:
                            pass
                    
                    if cat == "OTHER" and title:
                        raw_c, raw_s = classify_tags([title])
                        if raw_c and raw_c.upper() != "OTHER":
                            cat = raw_c.upper()
                            subcat = flatten_subcategory(raw_c, raw_s)
                            if cat == "SPORTS" and subcat == "Soccer":
                                t_low = title.lower()
                                if "fifa" in t_low or "world cup" in t_low or "fifwc" in (event_slug or "").lower():
                                    league = "FIFA World Cup"
                                elif "champions league" in t_low or "ucl" in t_low:
                                    league = "UEFA Champions League"
                                elif "premier league" in t_low or "epl" in t_low:
                                    league = "Premier League"

                    return (m["condition_id"], title, m["icon"], cat, subcat, league, event_slug)

            tasks = [resolve_one(m) for m in unique_markets.values()]
            resolved_rows = await asyncio.gather(*tasks)

            print(f"Upserting {len(resolved_rows)} markets into markets_v2...")
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
            """, resolved_rows)

            # Recompute stats
            print(f"Recomputing category_stats_v2 for {addr}...")
            await conn.execute("DELETE FROM category_stats_v2 WHERE address = $1;", addr)

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
            """, addr)

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
            """, addr)

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
            """, addr)

        # 5. Output
        final_stats = await conn.fetch("""
            SELECT category, subcategory, league, resolved_count, winning_count, win_rate, pnl
            FROM category_stats_v2
            WHERE address = $1
            ORDER BY resolved_count DESC
        """, addr)
        print("\n" + "=" * 85)
        print(f"FINAL CATEGORY STATS FOR {addr}:")
        print("=" * 85)
        for s in final_stats:
            cat_str = s['category']
            sub_str = f" -> {s['subcategory']}" if s['subcategory'] else ""
            lg_str = f" -> {s['league']}" if s['league'] else ""
            full_tax = f"{cat_str}{sub_str}{lg_str}"
            print(f"  {full_tax:<45} | {s['resolved_count']:>4} trades | Win%: {s['win_rate']:>5.1f}% | PnL: ${s['pnl']:>12,.2f}")

    finally:
        await conn.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "0xc684828f6b03487759ced2ebdd975f91f3532228"
    asyncio.run(fix_wallet(target))
