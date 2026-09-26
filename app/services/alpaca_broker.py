"""
Thin wrapper around Alpaca's Broker API.
Docs: https://docs.alpaca.markets/docs/about-broker-api

IMPORTANT: Broker API access is a partnership product. ALPACA_BROKER_API_KEY
and ALPACA_BROKER_API_SECRET will not exist until Alpaca has approved your
business (or your relationship with a sponsoring broker-dealer/RIA). Until
then, every call below will fail auth — that's expected in this scaffold.
"""
import os
import requests

TIMEOUT = 15


def _base_url():
    return os.environ.get("ALPACA_BROKER_BASE_URL", "https://broker-api.sandbox.alpaca.markets")


def _data_url():
    """Alpaca's market-data host. Same key pair works, different base path."""
    return os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")


def _auth():
    return (
        os.environ.get("ALPACA_BROKER_API_KEY", ""),
        os.environ.get("ALPACA_BROKER_API_SECRET", ""),
    )


# ---------------------------------------------------------------
# Account lifecycle
# ---------------------------------------------------------------

def create_account(kyc: dict) -> dict:
    """
    Submit a new end-customer account for KYC/CIP + approval. Alpaca runs the
    actual identity verification asynchronously; the account comes back as
    SUBMITTED and later transitions to APPROVED/ACTIVE or
    ACTION_REQUIRED/REJECTED. Poll get_account() or subscribe to the Broker
    Events (SSE) API rather than assuming approval here.
    """
    body = {
        "contact": {
            "email_address": kyc["email"],
            "street_address": [a for a in [kyc.get("address_line1"), kyc.get("address_line2")] if a],
            "city": kyc["city"],
            "state": kyc["state_region"],
            "postal_code": kyc["postal_code"],
            "country": kyc["country"],
        },
        "identity": {
            "given_name": kyc["given_name"],
            "family_name": kyc["family_name"],
            "date_of_birth": kyc["date_of_birth"],  # YYYY-MM-DD
            "tax_id_type": "USA_SSN",
            "tax_id": kyc.get("ssn_full"),  # collect over TLS, never log this value
            "country_of_citizenship": kyc["country"],
            "country_of_birth": kyc["country"],
            "country_of_tax_residence": kyc["country"],
            "funding_source": [kyc.get("funding_source", "employment_income")],
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
        },
        "agreements": [
            # Alpaca requires signed timestamps for their customer agreement,
            # margin agreement, etc. Capture real IP + signed_at from your
            # actual consent flow before going live.
        ],
    }
    resp = requests.post(f"{_base_url()}/v1/accounts", json=body, auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_account(account_id: str) -> dict:
    resp = requests.get(f"{_base_url()}/v1/accounts/{account_id}", auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------
# Bank links / transfers
# ---------------------------------------------------------------

def create_ach_relationship(account_id: str, processor_token: str) -> dict:
    resp = requests.post(
        f"{_base_url()}/v1/accounts/{account_id}/ach_relationships",
        json={"processor_token": processor_token},
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def create_transfer(account_id: str, relationship_id: str, amount_usd: str, direction: str) -> dict:
    """direction: 'INCOMING' (deposit) | 'OUTGOING' (withdrawal)"""
    resp = requests.post(
        f"{_base_url()}/v1/accounts/{account_id}/transfers",
        json={
            "transfer_type": "ach",
            "relationship_id": relationship_id,
            "amount": amount_usd,
            "direction": direction,
        },
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def list_transfers(account_id: str) -> list:
    resp = requests.get(f"{_base_url()}/v1/accounts/{account_id}/transfers", auth=_auth(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------
# Trading account (positions, balance, orders)
# ---------------------------------------------------------------

def get_positions(account_id: str) -> list:
    resp = requests.get(
        f"{_base_url()}/v1/trading/accounts/{account_id}/positions",
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_trade_account(account_id: str) -> dict:
    resp = requests.get(
        f"{_base_url()}/v1/trading/accounts/{account_id}/account",
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def place_order(account_id: str, symbol: str, qty: float, side: str,
                order_type: str = "market", time_in_force: str = "day") -> dict:
    """
    Submit an order to Alpaca on behalf of a brokerage account.
    side: 'buy' | 'sell'  (Alpaca's trading API uses lowercase)
    order_type: 'market' | 'limit' | 'stop' | 'stop_limit'
    """
    side = (side or "").lower()
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")

    body = {
        "symbol": symbol.upper(),
        "qty": f"{float(qty):.6f}".rstrip("0").rstrip("."),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    resp = requests.post(
        f"{_base_url()}/v1/trading/accounts/{account_id}/orders",
        json=body,
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_orders(account_id: str, status: str = "all", limit: int = 100) -> list:
    """Recent orders for the brokerage account, newest first."""
    resp = requests.get(
        f"{_base_url()}/v1/trading/accounts/{account_id}/orders",
        params={"status": status, "limit": limit, "direction": "desc"},
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------
# Market data (public — uses the data host, not the broker host)
# ---------------------------------------------------------------

def get_quote(symbol: str) -> dict:
    """
    Latest quote for a US equity symbol.
    Returns a normalised dict: { symbol, price, change_pct, change_abs,
    high, low, volume }.
    """
    symbol = (symbol or "").upper()
    if not symbol:
        raise ValueError("symbol is required")

    # Snapshot gives us last trade + daily bar in one call.
    resp = requests.get(
        f"{_data_url()}/v2/stocks/{symbol}/snapshot",
        params={"feed": "iex"},
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json() or {}

    latest_trade = data.get("latestTrade") or {}
    daily_bar = data.get("dailyBar") or {}
    prev_bar = data.get("prevDailyBar") or {}

    price = float(latest_trade.get("p") or daily_bar.get("c") or 0)
    prev_close = float(prev_bar.get("c") or 0)
    change_abs = price - prev_close if prev_close else 0
    change_pct = (change_abs / prev_close * 100) if prev_close else 0

    return {
        "symbol": symbol,
        "price": price,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "high": float(daily_bar.get("h") or 0),
        "low": float(daily_bar.get("l") or 0),
        "volume": float(daily_bar.get("v") or 0),
    }


def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 100) -> list:
    """
    Historical bars for a symbol.
    timeframe: '1Min','5Min','15Min','1Hour','1Day','1Week' (Alpaca's format)
    Returns a list of { t, o, h, l, c, v }.
    """
    symbol = (symbol or "").upper()
    if not symbol:
        raise ValueError("symbol is required")

    resp = requests.get(
        f"{_data_url()}/v2/stocks/{symbol}/bars",
        params={"timeframe": timeframe, "limit": min(int(limit), 1000), "feed": "iex"},
        auth=_auth(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    bars = payload.get("bars") or []

    out = []
    for b in bars:
        try:
            out.append({
                "t": b.get("t"),
                "open": float(b.get("o") or 0),
                "high": float(b.get("h") or 0),
                "low": float(b.get("l") or 0),
                "close": float(b.get("c") or 0),
                "volume": float(b.get("v") or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def search_symbols(query: str) -> list:
    """
    Alpaca doesn't expose a public asset-search endpoint on the data host.
    This is a thin placeholder that returns an empty list — replace with your
    own symbol universe (or query Alpaca's /v2/assets once you have keys).
    The dashboard falls back to its own POPULAR list.
    """
    return []