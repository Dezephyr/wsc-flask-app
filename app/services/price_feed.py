"""Live crypto prices from CoinMarketCap."""
import os, time, threading, requests

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
CACHE_SECONDS = 300

_lock = threading.Lock()
_cache = {"fetched_at": 0, "prices": {}}


def _fetch_from_cmc(symbols):
    key = os.environ.get("CMC_API_KEY")
    if not key:
        print("[price_feed] CMC_API_KEY not set")
        return {}
    headers = {"Accept": "application/json", "X-CMC_PRO_API_KEY": key}
    params = {"symbol": ",".join(symbols), "convert": "USD"}
    try:
        r = requests.get(CMC_URL, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
    except requests.RequestException as err:
        print(f"[price_feed] CMC request failed: {err}")
        return {}
    except ValueError as err:
        print(f"[price_feed] non-JSON: {err}")
        return {}

    data = payload.get("data") or {}
    out = {}
    for sym, entry in data.items():
        try:
            out[str(sym).upper()] = float(entry["quote"]["USD"]["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def get_prices(symbols, force=False):
    symbols = [str(s).strip().upper() for s in (symbols or []) if s]
    if not symbols:
        return {}

    with _lock:
        age = time.time() - _cache["fetched_at"]
        if not force and age < CACHE_SECONDS and _cache["prices"]:
            return {s: _cache["prices"][s] for s in symbols if s in _cache["prices"]}

    to_fetch = list(set(symbols) | set(_cache["prices"].keys()))
    fresh = _fetch_from_cmc(to_fetch)

    with _lock:
        if fresh:
            _cache["prices"] = fresh
            _cache["fetched_at"] = time.time()
        return {s: _cache["prices"][s] for s in symbols if s in _cache["prices"]}
