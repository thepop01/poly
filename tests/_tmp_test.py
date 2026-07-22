import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://poly_user:poly_password@localhost:5432/poly_db')
    try:
        r = await conn.execute("""
            INSERT INTO wallet_positions
                (address, condition_id, asset, title, slug, icon, event_slug,
                 outcome, outcome_index, opposite_outcome, opposite_asset,
                 size, avg_price, initial_value, current_value, cash_pnl,
                 percent_pnl, total_bought, realized_pnl, percent_realized_pnl,
                 cur_price, redeemable, mergeable, end_date, negative_risk,
                 category, subcategory, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,NOW())
            ON CONFLICT (address, condition_id) DO UPDATE SET title=EXCLUDED.title
        """, '0xtest1234', '0xcid123', 'asset123', 'Test Market', 'slug', 'icon', 'event',
            'Yes', 0, 'No', 'opp_asset', 100.0, 0.5, 50.0, 60.0, 10.0,
            20.0, 50.0, 10.0, 20.0, 0.6, False, False, None, False,
            'Politics', 'Politics')
        print(f'Position OK: {r}')
    except Exception as e:
        print(f'Position FAIL: {e}')
    await conn.close()

asyncio.run(main())
