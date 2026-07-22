import requests
res = requests.get('http://localhost:8000/api/leaderboard/might-cook?tab=zero_balance&limit=1000')
data = res.json()
found = [w for w in data['wallets'] if w['wallet_address'].lower() == '0x2d6938e8ab35f3f8538bee2eb239a8eba228bc81']
print(found)
