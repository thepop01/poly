import requests
res = requests.get('http://localhost:8000/api/leaderboard/global-wallets?limit=5&sort_by=balance&sort_order=asc')
data = res.json()
wallets = data['wallets']
for w in wallets:
    bal = float(w.get('balance') or 0)
    pos = float(w.get('position_value') or 0)
    print(f"{w['address'][:10]}... balance={bal:.2f} pos={pos:.2f} total={bal+pos:.2f}")
print("Total count:", data['total_count'])
