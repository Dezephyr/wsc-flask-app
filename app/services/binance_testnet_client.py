"""
Thin wrapper around Binance Spot Testnet.

Uses HMAC-SHA256 signed requests for the private endpoints (account, orders)
and unauthenticated requests for public market data (ticker, klines).

Docs: https://binance-docs.github.io/apidocs/spot/en/
Testnet site: https://testnet.binance.vision

IMPORTANT: this module places real orders against Binance's TESTNET.
No real funds move. Balances reset periodically on Binance's side, which
is why your local paper ledger (trades table) is the source of truth for
what the user sees.
"""
import os
import time
import hmac
import hashlib
import threading
import requests
from urllib.parse import urlencode

DEFAULT_BASE = "https://testnet.binance.vision"
TIMEOUT = 10

# Public market data cache: { symbol: { price, ts } }
_price_cache = {}
_price_lock = threading.Lock()
PRICE_CACHE_SECONDS = 5

# exchangeInfo is expensive and changes rarely. Cache the whole dict for
# an hour so we don't hammer the endpoint every order.
_exchange_info_cache = {"data": None, "ts": 0}
_exchange_info_lock = threading.Lock()
EXCHANGE_INFO_TTL = 3600


def _base():
    return os.environ.get("BINANCE_TESTNET_BASE_URL", DEFAULT_BASE).rstrip("/")


def _keys():
    key = os.environ.get("BINANCE_TESTNET_API_KEY", "").strip()
    secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "").strip()
    return key, secret


def _signed_request(method, path, params=None):
    """
    Send a signed request to a private Binance endpoint.
    Returns parsed JSON on success, raises requests.HTTPError on failure.
    """
    key, secret = _keys()
    if not key or not secret:
        raise RuntimeError("Binance testnet keys are not configured")

    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urlencode(params)
    signature = hmac.new(
        secret.encode("ascii"), query.encode("ascii"), hashlib.sha256
    ).hexdigest()
    url = f"{_base()}{path}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": key}

    resp = requests.request(method, url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _public_request(path, params=None):
    url = f"{_base()}{path}"
    resp = requests.get(url, params=params or {}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------- Public endpoints ----------

def get_price(symbol):
    """
    Latest price for a symbol (e.g. 'BTCUSDT').
    Cached for 5 seconds to smooth bursts.
    """
    symbol = (symbol or "").upper()
    if not symbol:
        return None

    now = time.time()
    with _price_lock:
        cached = _price_cache.get(symbol)
        if cached and now - cached["ts"] < PRICE_CACHE_SECONDS:
            return cached["price"]

    try:
        data = _public_request("/api/v3/ticker/price", {"symbol": symbol})
        price = float(data.get("price") or 0)
    except (requests.RequestException, ValueError, TypeError) as err:
        print(f"[binance_testnet] get_price({symbol}) failed: {err}")
        return None

    with _price_lock:
        _price_cache[symbol] = {"price": price, "ts": now}
    return price


def get_exchange_info():
    """
    Fetch /api/v3/exchangeInfo from the testnet. Public endpoint, no signature.
    Cached for EXCHANGE_INFO_TTL seconds so we only hit it once an hour.
    Returns a dict with a 'symbols' list, or {} on failure.
    """
    now = time.time()
    with _exchange_info_lock:
        cached = _exchange_info_cache["data"]
        if cached and now - _exchange_info_cache["ts"] < EXCHANGE_INFO_TTL:
            return cached

    try:
        data = _public_request("/api/v3/exchangeInfo")
    except requests.RequestException as err:
        print(f"[binance_testnet] get_exchange_info failed: {err}")
        return {}

    with _exchange_info_lock:
        _exchange_info_cache["data"] = data
        _exchange_info_cache["ts"] = now
    return data


def get_24h_stats(symbol):
    """
    Return 24h ticker stats for a symbol: price, change, high, low, volume.
    """
    symbol = (symbol or "").upper()
    if not symbol:
        return None
    try:
        data = _public_request("/api/v3/ticker/24hr", {"symbol": symbol})
    except requests.RequestException as err:
        print(f"[binance_testnet] get_24h_stats({symbol}) failed: {err}")
        return None

    try:
        return {
            "symbol": data.get("symbol"),
            "price": float(data.get("lastPrice") or 0),
            "change_pct": float(data.get("priceChangePercent") or 0),
            "change_abs": float(data.get("priceChange") or 0),
            "high": float(data.get("highPrice") or 0),
            "low": float(data.get("lowPrice") or 0),
            "volume": float(data.get("volume") or 0),
        }
    except (TypeError, ValueError):
        return None


def get_klines(symbol, interval="1h", limit=168):
    """
    Candlestick data for charting.
    interval: 1m, 5m, 15m, 1h, 4h, 1d, etc.
    limit: max 1000
    """
    symbol = (symbol or "").upper()
    try:
        data = _public_request(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
    except requests.RequestException as err:
        print(f"[binance_testnet] get_klines({symbol}) failed: {err}")
        return []

    out = []
    for k in data or []:
        try:
            out.append({
                "open_time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": int(k[6]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    return out


# ---------- Private endpoints ----------

def get_account():
    """Return spot account info: balances for every asset."""
    return _signed_request("GET", "/api/v3/account")


def get_account_balance(asset):
    """Return free balance for one asset (e.g. 'USDT', 'BTC')."""
    acct = get_account()
    for b in acct.get("balances", []):
        if b.get("asset") == asset.upper():
            try:
                return float(b.get("free") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def place_market_order(symbol, side, quantity):
    """
    Place a market order.
    side: 'BUY' or 'SELL'
    quantity: base-asset amount (e.g. 0.001 BTC)

    Returns the raw Binance response (orderId, fills, status, etc.).
    """
    return _signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": f"{float(quantity):.8f}".rstrip("0").rstrip("."),
        },
    )


def get_order(symbol, order_id):
    return _signed_request(
        "GET", "/api/v3/order",
        {"symbol": symbol.upper(), "orderId": order_id},
    )


def ping():
    """Public connectivity check."""
    try:
        _public_request("/api/v3/ping")
        return True
    except requests.RequestException:
        return False