import asyncio, aiohttp, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore

async def check():
    addr = '0xa20b482f97063f4f88ef621c9203e60814399940'
    async with aiohttp.ClientSession() as s:
        all_pos = []
        offset = 0
        while True:
            async with s.get(f'https://data-api.polymarket.com/positions?user={addr}&limit=500&offset={offset}') as r:
                data = await r.json()
            if not data:
                break
            all_pos.extend(data)
            if len(data) < 500:
                break
            offset += 500

        wins_redeemable = [p for p in all_pos if p.get('redeemable') and float(p.get('curPrice', 0)) > 0.99]
        losses_redeemable = [p for p in all_pos if p.get('redeemable') and float(p.get('curPrice', 0)) < 0.01]
        still_open = [p for p in all_pos if not p.get('redeemable')]

        print(f'Total /positions entries: {len(all_pos)}')
        print(f'  redeemable WINS  (curPrice~1): {len(wins_redeemable)}')
        print(f'  redeemable LOSSES (curPrice~0): {len(losses_redeemable)}')
        print(f'  still OPEN (not redeemable):  {len(still_open)}')
        print()

        if losses_redeemable:
            p = losses_redeemable[0]
            cid = p["conditionId"]
            print('Sample redeemable LOSS:')
            print(f'  conditionId: {cid[:20]}...')
            print(f'  title: {p["title"][:55]}')
            print(f'  outcome: {p["outcome"]}')
            print(f'  cashPnl: {p["cashPnl"]}')
            print(f'  totalBought: {p["totalBought"]}')
            print(f'  avgPrice: {p["avgPrice"]}')
            print(f'  endDate: {p["endDate"]}')

        total_wins = 14505
        total_losses = len(losses_redeemable)
        real_wr = total_wins / (total_wins + total_losses) * 100 if (total_wins + total_losses) > 0 else 0
        print()
        print('=== REAL WIN RATE ESTIMATE ===')
        print(f'  Wins (from /closed-positions):  {total_wins}')
        print(f'  Losses (redeemable, curPrice=0): {total_losses}')
        print(f'  Real win rate: {real_wr:.2f}%')
        print()
        print('Note: auto-expired losses (never became redeemable) are NOT counted above')

asyncio.run(check())
