import requests

url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=3mo&interval=1d"
headers = {"User-Agent": "Mozilla/5.0"}

try:
    r = requests.get(url, headers=headers, timeout=15)
    print("STATUS:", r.status_code)
    print("BODY:", r.text[:500])
except Exception as e:
    print("ERROR:", type(e).__name__, e)