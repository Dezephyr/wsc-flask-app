"""
Live crypto prices from CoinMarketCap.

Free "Basic" tier: 10,000 calls/month, ~1-minute update cadence.
We cache the result server-side for CACHE_SECONDS so that N users hitting
the Fund page in the same minute still produce only ONE outbound call.

If CMC_API_KEY isn't set, or the request fails, callers get an empty dict —
the frontend is responsible for falling back to the admin's manual price.
"""
import os
import time
import threading
import requests

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"

# How long a cached price is considered fresh. 300s = 5 minutes.
CACHE_SECONDS = 300

_lock = threading.Lock()
_cache = {
    "fetched_at": 0,
    "prices": {},   # { "BTC": 63000.0, "ETH": 3400.0, ... }
}


def _fetch_from_cmc(symbols):
    """Call CMC once for a comma-separated list of symbols. Returns dict or {}."""
    key = os.environ.get("CMC_API_KEY")
    if not key:
        return {}

    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": key,
    }
    params = {
        "symbol": ",".join(symbols),
        "convert": "USD",
    }

    try:
        resp = requests.get(CMC_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as err:
        print(f"[price_feed] CMC request failed: {err}")
        return {}

    data = payload.get("data") or {}
    out = {}
    for sym, entry in data.items():
        try:
            usd = entry["quote"]["USD"]["price"]
            out[sym.upper()] = float(usd)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def get_prices(symbols):
    """
    Return { SYMBOL_UPPER: usd_price } for the requested symbols.

    Reads from cache if fresh, otherwise calls CMC once.
    Symbols not returned by CMC simply won't appear in the result.
    """
    symbols = [s.upper() for s in symbols if s]
    if not symbols:
        return {}

    with _lock:
        age = time.time() - _cache["fetched_at"]
        if age < CACHE_SECONDS and _cache["prices"]:
            # Return only what was asked for, out of the cached set.
            return {s: _cache["prices"][s] for s in symbols if s in _cache["prices"]}

        # Cache is stale — refresh. Fetch for the union of requested symbols
        # and anything already cached, so a new symbol doesn't force a
        # separate call for existing ones.
        to_fetch = list(set(symbols) | set(_cache["prices"].keys()))
        fresh = _fetch_from_cmc(to_fetch)
        if fresh:
            _cache["prices"] = fresh
            _cache["fetched_at"] = time.time()

        return {s: _cache["prices"][s] for s in symbols if s in _cache["prices"]}