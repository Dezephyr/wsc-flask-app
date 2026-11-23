"""
Thin wrapper around Plaid, used only to link a user's bank account and mint
the processor token Alpaca needs to create an ACH relationship. This app
never sees or stores raw account/routing numbers.
Docs: https://plaid.com/docs/
"""
import os
import requests

TIMEOUT = 15

_ENV_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _base_url():
    return _ENV_URLS[os.environ.get("PLAID_ENV", "sandbox")]


def _creds():
    return {
        "client_id": os.environ.get("PLAID_CLIENT_ID"),
        "secret": os.environ.get("PLAID_SECRET"),
    }


def create_link_token(user_id: str) -> dict:
    """Create a Link token for the frontend to open Plaid Link with."""
    resp = requests.post(
        f"{_base_url()}/link/token/create",
        json={
            **_creds(),
            "user": {"client_user_id": user_id},
            "client_name": "Wall Street Capital",
            "products": ["auth"],
            "country_codes": ["US"],
            "language": "en",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # { link_token, expiration }


def exchange_public_token(public_token: str) -> dict:
    """Exchange the public token from Plaid Link for a permanent access token."""
    resp = requests.post(
        f"{_base_url()}/item/public_token/exchange",
        json={**_creds(), "public_token": public_token},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # { access_token, item_id }


def create_processor_token(access_token: str, plaid_account_id: str) -> dict:
    """Mint a processor token scoped for Alpaca from a Plaid access token + account id."""
    resp = requests.post(
        f"{_base_url()}/processor/token/create",
        json={
            **_creds(),
            "access_token": access_token,
            "account_id": plaid_account_id,
            "processor": "alpaca",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # { processor_token }
