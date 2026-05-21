from __future__ import annotations

import json

import httpx
import plural_mpp_buyer

from plural_mpp_buyer import (
    Amount,
    CreateMandateOptions,
    CreateTokenOptions,
    PluralBuyer,
    PluralBuyerConfig,
)
from plural_mpp_buyer.types.token import CreateTokenUsageLimits
from plural_mpp_buyer.utils.base64url import encode_json


class _CaptureTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/api/auth/v1/token":
            return httpx.Response(
                200,
                json={"access_token": "buyer-access-token", "expires_at": "2030-01-01T00:00:00Z"},
            )

        if path == "/mpp/v1/pre-authorize":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "SBMD",
                        "authorization_id": "v1-sub-260504060504-aa-TledOp",
                        "customer_id": "cust-v1-260504054352-aa-dG9pJs",
                        "challenge_url": "upi://mandate?pa=setu.pluralcug@pineaxis&tr=mandate_r7tjk5r8vx1000",
                        "metadata": {
                            "description": body.get("description"),
                            "amount": int(body.get("amount", {}).get("value", 0)),
                            "currency": body.get("amount", {}).get("currency", "INR"),
                            "external_subscription_id": "v1-sub-260504060504-aa-TledOp",
                            "sbmd_data": {
                                "object": "mandate",
                                "order_id": "v1-260504060504-aa-qSnXPY",
                                "amount_blocked": 0,
                                "amount_debited": 0,
                                "amount_held": 0,
                                "amount_available": int(body.get("amount", {}).get("value", 0)),
                                "challenge_type": "upi_intent",
                                "expires_at": "2026-05-11T06:05:04.746209698Z",
                                "created_at": "2026-05-04T06:05:05.170Z",
                            },
                        },
                        "status": "PENDING",
                        "created_at": "2026-04-22T00:00:00Z",
                    }
                },
            )

        if path.startswith("/mpp/v1/authorization/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "SBMD",
                        "authorization_id": "v1-sub-260422154824-aa-M3qU2m",
                        "merchant_id": "merchant-from-provider",
                        "customer_reference": "buyer@example.com",
                        "customer_id": "cust-v1-260422154823-aa-dF9zGg",
                        "status": "ACTIVE",
                        "amount_value": "1000000",
                        "amount_currency": "INR",
                        "description": "Postman SBMD E2E test",
                        "validity_in_days": 7,
                        "expiry_at": "2026-05-07T15:37:08.391845Z",
                        "challenge_url": "upi://mandate?pa=setu.pluralcug@pineaxis&txnType=CREATE",
                        "external_reference_id": "v1-sub-260422154824-aa-M3qU2m",
                        "metadata": {
                            "sbmd_data": {
                                "object": "mandate",
                                "order_id": "v1-260430153708-aa-77TA5T",
                                "created_at": "2026-04-30T15:37:09.381Z",
                                "expires_at": "2026-05-07T15:37:08.391845257Z",
                                "amount_held": 0.0,
                                "amount_blocked": 0.0,
                                "amount_debited": 0.0,
                                "challenge_type": "upi_intent",
                                "amount_available": 1000.0,
                            }
                        },
                    }
                },
            )

        if path == "/mpp/v1/token":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_token": "MPP_TOK_21165684-af41-455c-b1d4-bc2a97721699",
                        "expires_in": 300,
                        "type": body.get("type", "SBMD"),
                        "authorization_id": "v1-sub-260422154824-aa-M3qU2m",
                    }
                },
            )

        if path == "/api/premium":
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Payment "):
                return httpx.Response(
                    402,
                    json={"type": "about:blank", "title": "Payment Required", "status": 402, "challengeId": "ch_123"},
                    headers={
                        "WWW-Authenticate": "Payment " + encode_json({
                            "id": "ch_123",
                            "realm": "Plural MPP",
                            "method": "plural",
                            "intent": "charge",
                            "request": {
                                "scheme": "exact",
                                "amount": "100.00",
                                "currency": "INR",
                                "resource": "/api/premium",
                            },
                            "expires": "2030-01-01T00:00:00Z",
                        }),
                        "Content-Type": "application/problem+json",
                    },
                )
            return httpx.Response(200, json={"ok": True})

        return httpx.Response(404)


class _SingularTokenTransport(_CaptureTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/api/auth/v1/token":
            return httpx.Response(
                200,
                json={"access_token": "buyer-access-token", "expires_at": "2030-01-01T00:00:00Z"},
            )

        if path == "/mpp/v1/token":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_token": "MPP_TOK_21165684-af41-455c-b1d4-bc2a97721699",
                        "expires_in": 300,
                        "type": body.get("type", "SBMD"),
                        "authorization_id": "v1-sub-260422154824-aa-M3qU2m",
                    }
                },
            )

        return super().handle_request(request)


def _patched_client_factory(transport: _CaptureTransport):
    real_client = httpx.Client

    def _patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return _patched_client


def test_create_mandate_uses_customer_reference(monkeypatch):
    transport = _CaptureTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            baseUrl="https://api.test",
        )
    )
    try:
        mandate = buyer.methods.create_mandate(
            CreateMandateOptions(
                mobileNumber="+919876543210",
                amount=Amount(value=500000, currency="INR"),
                customerReference="cust-ref-123",
                description="Ride booking mandate",
            )
        )
    finally:
        buyer.close()

    mandate_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    body = json.loads(mandate_request.content.decode() or "{}")
    assert body == {
        "type": "SBMD",
        "customer_reference": "cust-ref-123",
        "amount": {"value": "500000", "currency": "INR"},
        "validity_in_days": 7,
        "description": "Ride booking mandate",
    }
    assert "mobile_number" not in body
    assert "customer_id" not in body
    assert mandate.mandate_id == "v1-sub-260504060504-aa-TledOp"


def test_create_mandate_accepts_plain_10_digit_mobile(monkeypatch):
    transport = _CaptureTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            baseUrl="https://api.test",
        )
    )
    try:
        buyer.methods.create_mandate(
            CreateMandateOptions(
                mobileNumber="9876543210",
                amount=Amount(value=500000, currency="INR"),
                customerReference="cust-ref-123",
            )
        )
    finally:
        buyer.close()

    mandate_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    body = json.loads(mandate_request.content.decode() or "{}")
    assert body["customer_reference"] == "cust-ref-123"
    assert "mobile_number" not in body


def test_create_token_uses_customer_reference(monkeypatch):
    transport = _CaptureTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            baseUrl="https://api.test",
        )
    )
    assert not hasattr(buyer.methods, "revoke_token")
    assert not hasattr(plural_mpp_buyer, "RevokeTokenResult")
    try:
        token = buyer.methods.create_token(
            CreateTokenOptions(
                customerReference="cust-ref-123",
                usageLimits=CreateTokenUsageLimits(
                    maxAmount=10000,
                    currency="INR",
                    expiresAt="2030-01-01T00:00:00Z",
                ),
            )
        )
    finally:
        buyer.close()

    token_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/token")
    body = json.loads(token_request.content.decode() or "{}")
    assert body == {"type": "SBMD", "customer_reference": "cust-ref-123"}
    assert "customer_id" not in body
    assert token.token_id == "MPP_TOK_21165684-af41-455c-b1d4-bc2a97721699"
    assert token.token == "MPP_TOK_21165684-af41-455c-b1d4-bc2a97721699"
    assert token.mandate_id == "v1-sub-260422154824-aa-M3qU2m"
    assert token.raw["authorization_id"] == "v1-sub-260422154824-aa-M3qU2m"


def test_get_mandate_maps_v2_authorization_status_response(monkeypatch):
    transport = _CaptureTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            baseUrl="https://api.test",
        )
    )

    try:
        mandate = buyer.methods.get_mandate("v1-sub-260422154824-aa-M3qU2m")
    finally:
        buyer.close()

    status_request = next(req for req in transport.requests if req.url.path.startswith("/mpp/v1/authorization/"))
    assert status_request.url.path == "/mpp/v1/authorization/v1-sub-260422154824-aa-M3qU2m"
    assert mandate.mandate_id == "v1-sub-260422154824-aa-M3qU2m"
    assert mandate.payment_status == "ACTIVE"
    assert mandate.order_status == "ACTIVE"
    assert mandate.customer_reference == "buyer@example.com"
    assert mandate.customer_id == "cust-v1-260422154823-aa-dF9zGg"
    assert mandate.amount.value == 1000000
    assert mandate.amount.currency == "INR"
    assert mandate.amount_available == 1000.0
    assert mandate.amount_debited == 0.0
    assert mandate.amount_held == 0.0
    assert mandate.amount_blocked == 0.0
    assert mandate.expires_at == "2026-05-07T15:37:08.391845Z"
    assert mandate.created_at == "2026-04-30T15:37:09.381Z"
    assert mandate.description == "Postman SBMD E2E test"
    assert mandate.challenge is not None
    assert mandate.challenge.deep_link.startswith("upi://mandate")


def test_auto_402_token_creation_uses_customer_reference_from_config(monkeypatch):
    transport = _CaptureTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            customerReference="cust-ref-123",
            baseUrl="https://api.test",
        )
    )
    try:
        response = buyer.get("https://api.test/api/premium")
    finally:
        buyer.close()

    assert response.status_code == 200
    token_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/token")
    body = json.loads(token_request.content.decode() or "{}")
    assert body == {"type": "SBMD", "customer_reference": "cust-ref-123"}


def test_create_token_uses_singular_mpp_route(monkeypatch):
    transport = _SingularTokenTransport()
    monkeypatch.setattr("httpx.Client", _patched_client_factory(transport))

    buyer = PluralBuyer.create(
        PluralBuyerConfig(
            clientId="buyer-client",
            clientSecret="buyer-secret",
            customerReference="cust-ref-123",
            authBaseUrl="https://api.test",
            mppBaseUrl="https://api.test",
            accessToken="Bearer configured-buyer-token",
        )
    )
    try:
        token = buyer.methods.create_token(
            CreateTokenOptions(
                customerReference="cust-ref-123",
                usageLimits=CreateTokenUsageLimits(
                    maxAmount=100,
                    currency="INR",
                    expiresAt="2030-01-01T00:00:00Z",
                ),
            )
        )
    finally:
        buyer.close()

    attempted_paths = [req.url.path for req in transport.requests]
    assert "/api/auth/v1/token" not in attempted_paths
    assert "/mpp/v1/token" in attempted_paths
    assert "/mpp/v1/tokens" not in attempted_paths
    singular_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/token")
    body = json.loads(singular_request.content.decode() or "{}")
    assert body == {"type": "SBMD", "customer_reference": "cust-ref-123"}
    assert singular_request.headers["Authorization"] == "Bearer configured-buyer-token"
    assert "Merchant-ID" not in singular_request.headers
    assert token.token == "MPP_TOK_21165684-af41-455c-b1d4-bc2a97721699"
