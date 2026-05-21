"""End-to-end smoke test exercising the 402 challenge ↔ credential ↔ capture
flow between the Python buyer SDK and the Python seller SDK.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from plural_mpp_buyer import (
    Amount,
    MppEnvironment,
    PluralBuyer,
    PluralBuyerConfig,
    decode_challenge,
    decode_receipt,
    has_scope,
    parse_scope,
)
from plural_mpp_buyer.client.credential_builder import (
    build_credential,
    encode_credential_header,
)
from plural_mpp_buyer.grantex import (
    check_payment_authorization,
    extract_spending_limit,
)
from plural_mpp_seller import (
    ChargeOptions,
    PluralMPP,
    PluralSellerConfig,
)
from plural_mpp_seller import Amount as SellerAmount


SECRET = "shared-hmac-secret-please-change"
CLIENT_ID = "buyer-client-id"
CLIENT_SECRET = "buyer-client-secret"


def _seller_config(base_url: str) -> PluralSellerConfig:
    return PluralSellerConfig(
        clientId="seller-id",
        clientSecret="seller-secret",
        challengeSecretKey=SECRET,
        realm=MppEnvironment.SANDBOX,
        baseUrl=base_url,
        maxRetries=0,
    )


def _buyer_config(base_url: str) -> PluralBuyerConfig:
    return PluralBuyerConfig(
        clientId=CLIENT_ID,
        clientSecret=CLIENT_SECRET,
        customerReference="cust-smoke",
        baseUrl=base_url,
        maxRetries=0,
    )


def test_scope_parsing_and_limits() -> None:
    parsed = parse_scope("mpp:payment:initiate:max_500")
    assert parsed is not None
    assert parsed.resource == "mpp:payment"
    assert parsed.action == "initiate"
    assert parsed.constraint == "max_500"

    assert has_scope(["mpp:payment:initiate:max_500"], "mpp:payment:initiate")
    assert has_scope(["mpp:*"], "mpp:payment:initiate")
    assert not has_scope(["mpp:mandate:read"], "mpp:payment:initiate")

    limit = extract_spending_limit(["mpp:payment:initiate:max_500"])
    assert limit is not None
    assert limit.maxAmountPaise == 50_000
    assert limit.currency == "INR"


def test_buyer_authorization_check() -> None:
    from plural_mpp_buyer.types.grantex import GrantTokenClaims

    claims = GrantTokenClaims(
        iss="https://grantex.example",
        sub="user-1",
        agt="agent-1",
        scp=["mpp:payment:initiate:max_500"],
        grnt="grant-1",
        iat=0,
        exp=0,
    )
    ok = check_payment_authorization(claims, 25_000)
    assert ok.authorized is True

    too_much = check_payment_authorization(claims, 80_000)
    assert too_much.authorized is False
    assert "exceeds" in (too_much.reason or "").lower()


def test_challenge_roundtrip() -> None:
    seller = PluralMPP.create(_seller_config("https://api.test"))
    result = seller.generate_challenge(
        ChargeOptions(amount=SellerAmount(value=15_000, currency="INR"), resource="/api/x")
    )

    header = f"Payment {result.encoded}"
    challenge = decode_challenge(header)
    assert challenge.id == result.challenge.id
    assert challenge.request.currency == "INR"
    assert challenge.request.amount == "150.00"


class _MockTransport(httpx.BaseTransport):
    """Minimal transport that simulates the MPP API + a paid resource."""

    def __init__(self, base_url: str) -> None:
        self.seller: Any = None  # assigned after seller construction
        self._base = base_url.rstrip("/")
        self.requests: List[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        path = request.url.path

        # Buyer auth / token endpoints on base_url
        if path == "/api/auth/v1/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "buyer-access-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )

        if path == "/mpp/v1/token":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_token": "MPP_TOK_smoke",
                        "expires_in": 300,
                        "type": body.get("type", "SBMD"),
                        "authorization_id": "mnd_test",
                    }
                },
            )

        if path == "/mpp/v1/debit":
            body = json.loads(request.content.decode() or "{}")
            amount_value = int(body.get("amount") or 0)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "SBMD",
                        "authorization_id": "mnd_test",
                        "payment_id": "pay_1",
                        "merchant_order_reference": body.get("merchant_order_reference"),
                        "amount": str(amount_value),
                        "currency": body.get("currency", "INR"),
                        "status": "CONFIRMED",
                        "oms_order_id": "ord_1",
                        "oms_payment_id": "ord_1-up-a",
                        "metadata": {
                            "external_capture_id": "ord_1-up-a",
                            "external_payment_id": "ord_1-up-a",
                            "upstream_payment_status": "PROCESSED",
                            "upstream_order_status": "PROCESSED",
                            "sbmd_data": {
                                "settled_at": "2024-01-01T00:00:00Z",
                                "upi_txn_id": "upi_1",
                            },
                        },
                    }
                },
            )

        # Paid resource lives on a different host — intercept here
        if path == "/api/premium":
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Payment "):
                result = self.seller.generate_challenge(
                    ChargeOptions(
                        amount=SellerAmount(value=15_000, currency="INR"),
                        resource="/api/premium",
                    )
                )
                return httpx.Response(
                    402,
                    json={
                        "type": result.problemDetails.type,
                        "title": result.problemDetails.title,
                        "status": 402,
                        "detail": result.problemDetails.detail,
                        "challengeId": result.problemDetails.challengeId,
                    },
                    headers={
                        "WWW-Authenticate": f"Payment {result.encoded}",
                        "Content-Type": "application/problem+json",
                    },
                )

            verification = self.seller.verify_credential(auth)
            assert verification.valid, verification.error

            capture = self.seller.capture(
                _capture_options_from_credential(verification.credential)
            )
            receipt_header = self.seller.build_receipt_header(
                capture, verification.credential.challenge.id
            )
            return httpx.Response(
                200,
                json={"data": "premium content"},
                headers={"Payment-Receipt": receipt_header},
            )

        return httpx.Response(404)


def _capture_options_from_credential(credential) -> Any:  # noqa: ANN401
    from plural_mpp_seller import Amount as SellerAmount, CaptureOptions
    amt_major = float(credential.challenge.request.amount)
    return CaptureOptions(
        token=credential.payload.token,
        amount=SellerAmount(value=round(amt_major * 100), currency=credential.challenge.request.currency),
        customerReference=credential.payload.customer_reference,
    )


def test_end_to_end_402_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://api.test"
    transport = _MockTransport(base_url)

    # Patch httpx.Client BEFORE constructing any SDK objects so that both the
    # buyer's fetch-interceptor client and the seller's internal capture/auth
    # clients route through our mock transport.
    real_client = httpx.Client

    def _patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _patched_client)

    seller = PluralMPP.create(_seller_config(base_url))
    transport.seller = seller

    buyer = PluralBuyer.create(_buyer_config(base_url))
    try:
        response = buyer.get(f"{base_url}/api/premium")
        assert response.status_code == 200
        assert response.json() == {"data": "premium content"}
        assert response.headers.get("Payment-Receipt", "").startswith("Payment ")

        # Receipt round-trips
        receipt = decode_receipt(response.headers["Payment-Receipt"])
        assert receipt.status == "success"
        assert receipt.settlement.amount == "150.00"
        assert receipt.settlement.currency == "INR"
        debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
        debit_body = json.loads(debit_request.content.decode() or "{}")
        assert debit_body["customer_reference"] == "cust-smoke"
    finally:
        buyer.close()
