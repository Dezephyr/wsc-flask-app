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


def _auth():
    return (os.environ.get("ALPACA_BROKER_API_KEY", ""), os.environ.get("ALPACA_BROKER_API_SECRET", ""))


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


def get_positions(account_id: str) -> list:
    resp = requests.get(
        f"{_base_url()}/v1/trading/accounts/{account_id}/positions", auth=_auth(), timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def get_trade_account(account_id: str) -> dict:
    resp = requests.get(
        f"{_base_url()}/v1/trading/accounts/{account_id}/account", auth=_auth(), timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()
