"""services/crypto_prices.py - wrapper around price_feed for the admin page."""
import time, threading
from . import price_feed

_GAS = {"BTC":0.50,"ETH":2.50,"BNB":0.15,"SOL":0.001,"TRX":0.90,"MATIC":0.02,
        "ADA":0.17,"XRP":0.0002,"DOGE":0.05,"LTC":0.02,"LINK":0.50,
        "USDT":1.50,"USDC":1.50}

def estimate_gas_usd(symbol):
    return _GAS.get((symbol or "").upper(), 0.10)

def get_live_prices(symbols, force=False):
    coins = sorted({(s or "").upper().strip() for s in symbols if s and s.strip()})
    if not coins:
        return {}
    raw = price_feed.get_prices(coins, force=force)
    out = {}
    for sym in coins:
        usd = raw.get(sym)
        if usd is None or usd <= 0:
            continue
        out[sym] = {"usd": float(usd), "gas_usd": estimate_gas_usd(sym), "source": "live"}
    return out
