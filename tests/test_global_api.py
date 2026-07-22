import requests
res = requests.get('http://localhost:8000/api/leaderboard/global-wallets?search=0x2d6938e8ab35f3f8538bee2eb239a8eba228bc81')
data = res.json()
print(data)
