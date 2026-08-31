"""End-to-end smoke test exercising the 402 challenge ↔ credential ↔ capture
flow between the Python client SDK and the Python server SDK.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from pinelabs_p3p_client import (
    ClientRuntimeContext,
    P3PCustomerAuthMode,
    P3PEnvironment,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
    decode_challenge,
    decode_receipt,
)
from pinelabs_p3p_server import (
    ChargeOptions,
    PaymentGateway as ServerPaymentGateway,
    PaymentMethod as ServerPaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
)
from pinelabs_p3p_server import Amount as ServerAmount
from pinelabs_p3p_client.client.credential_builder import encode_json

def _server_config(base_url: str) -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="server-id",
        clientSecret="server-secret",
        merchantId="merchant-test",
        paymentGateway=ServerPaymentGateway.PineLabsOnline,
        availablePaymentMethods=[ServerPaymentMethod.RESERVE_PAY, ServerPaymentMethod.OTM],
        realm=P3PEnvironment.SANDBOX,
        env=base_url,
        maxRetries=0,
    )


def _client_config(base_url: str) -> PineLabsOnlineClientConfig:
    return PineLabsOnlineClientConfig(
        customerAuthMode=P3PCustomerAuthMode.CustomerKey,
        clientId="client-id",
        clientSecret="client-secret",
        merchantId="merchant-test",
        env=base_url,
        maxRetries=0,
    )


def test_challenge_roundtrip() -> None:
    server = PineLabsOnlineP3P.create(_server_config("https://api.test"))
    result = server.generate_challenge(
        ChargeOptions(amount=ServerAmount(value=15_000, currency="INR"), resource="/api/x")
    )

    header = f"Payment {result.encoded}"
    challenge = decode_challenge(header)
    assert challenge.id == result.challenge.id
    assert challenge.request.currency == "INR"
    assert challenge.request.amount == "150.00"
    assert challenge.request.availablePaymentMethods == [PaymentMethod.RESERVE_PAY, PaymentMethod.OTM]


def test_payment_method_exposes_reserve_pay_member() -> None:
    assert PaymentMethod.RESERVE_PAY.value == "RESERVE_PAY"
    assert PaymentMethod.OTM.value == "OTM"
    assert PaymentMethod.CARD.value == "CARD"
    assert not hasattr(PaymentMethod, "UPI_RESERVE_PAY")


def test_challenge_decode_supports_otm_payment_method() -> None:
    header = "Payment " + encode_json(
        {
            "id": "ch_otm",
            "realm": "Pine Labs Online P3P",
            "intent": "charge",
            "request": {
                "scheme": "exact",
                "amount": "100.00",
                "currency": "INR",
                "resource": "/api/x",
                "availablePaymentMethods": ["OTM"],
            },
            "expires": "2030-01-01T00:00:00Z",
        }
    )

    challenge = decode_challenge(header)

    assert challenge.request.availablePaymentMethods == [PaymentMethod.OTM]


def test_challenge_decode_supports_card_payment_method() -> None:
    header = "Payment " + encode_json(
        {
            "id": "ch_card",
            "realm": "Pine Labs Online P3P",
            "intent": "charge",
            "request": {
                "scheme": "exact",
                "amount": "10.00",
                "currency": "INR",
                "resource": "/api/x",
                "availablePaymentMethods": ["CARD"],
            },
            "expires": "2030-01-01T00:00:00Z",
        }
    )

    challenge = decode_challenge(header)

    assert challenge.request.availablePaymentMethods == [PaymentMethod.CARD]


class _MockTransport(httpx.BaseTransport):
    """Minimal transport that simulates the P3P API + a paid resource."""

    def __init__(self, base_url: str) -> None:
        self.server: Any = None  # assigned after server construction
        self._base = base_url.rstrip("/")
        self.requests: List[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        path = request.url.path

        # Server auth / client token endpoints on base_url
        if path == "/api/auth/v1/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "server-access-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )

        if path == "/api/v1/customer/mpp/token":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_token": "MPP_TOK_smoke",
                        "expires_in": 300,
                        "payment_method": body.get("payment_method", "RESERVE_PAY"),
                        "payment_method_reference_id": "mnd_test",
                    }
                },
            )

        if path == "/mpp/v1/debit":
            body = json.loads(request.content.decode() or "{}")
            payment_amount = body.get("payment_amount") or {}
            amount_value = int(payment_amount.get("value") or 0)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "RESERVE_PAY",
                        "payment_method": "RESERVE_PAY",
                        "payment_method_reference_id": "mnd_test",
                        "payment_id": "pay_1",
                        "merchant_payment_debit_reference": request.headers.get("Idempotency-Key"),
                        "amount": {"value": amount_value, "currency": payment_amount.get("currency", "INR")},
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
            credential_header = request.headers.get("P3P-Credential", "")
            if not credential_header.startswith("Payment "):
                result = self.server.generate_challenge(
                    ChargeOptions(
                        amount=ServerAmount(value=15_000, currency="INR"),
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

            verification = self.server.verify_credential(credential_header)
            assert verification.valid, verification.error

            capture = self.server.capture(
                _capture_options_from_credential(verification.credential)
            )
            receipt_header = self.server.build_receipt_header(
                capture, verification.credential.challenge.id
            )
            return httpx.Response(
                200,
                json={"data": "premium content"},
                headers={"Payment-Receipt": receipt_header},
            )

        return httpx.Response(404)


def _capture_options_from_credential(credential) -> Any:  # noqa: ANN401
    from pinelabs_p3p_server import Amount as ServerAmount, CaptureOptions
    amt_major = float(credential.challenge.request.amount)
    return CaptureOptions(
        token=credential.payload.token,
        amount=ServerAmount(value=round(amt_major * 100), currency=credential.challenge.request.currency),
        paymentMethod=credential.payload.payment_method,
        paymentMethodReferenceId=credential.payload.payment_method_reference_id,
        mobileNumber=credential.payload.mobile_number,
        challengeId=credential.challenge.id,
    )


def test_end_to_end_402_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://api.test"
    transport = _MockTransport(base_url)

    # Patch httpx.Client BEFORE constructing any SDK objects so that both the
    # client's fetch-interceptor client and the server's internal capture/auth
    # clients route through our mock transport.
    real_client = httpx.Client

    def _patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _patched_client)

    server = PineLabsOnlineP3P.create(_server_config(base_url))
    transport.server = server

    client = PineLabsOnlineClient.create(_client_config(base_url))
    try:
        response = client.get(
            f"{base_url}/api/premium",
            context=ClientRuntimeContext(
                customerKey="ck_smoke",
                customerReference="9876543210",
                mobileNumber="9876543210",
                paymentMethod=PaymentMethod.RESERVE_PAY,
            ),
        )
        assert response.status_code == 200
        assert response.json() == {"data": "premium content"}
        assert response.headers.get("Payment-Receipt", "").startswith("Payment ")

        # Receipt round-trips
        receipt = decode_receipt(response.headers["Payment-Receipt"])
        assert receipt.status == "success"
        assert not hasattr(receipt, "method")
        assert receipt.paymentGateway == PaymentGateway.PineLabsOnline
        assert receipt.paymentMethod == PaymentMethod.RESERVE_PAY
        assert receipt.settlement.amount == "150.00"
        assert receipt.settlement.currency == "INR"
        debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
        debit_body = json.loads(debit_request.content.decode() or "{}")
        token_request = next(req for req in transport.requests if req.url.path == "/api/v1/customer/mpp/token")
        token_body = json.loads(token_request.content.decode() or "{}")
        assert token_request.url.host == "api.test"
        assert debit_body["customer"] == {"mobile_number": "9876543210"}
        assert debit_body["payment_method"] == "RESERVE_PAY"
        assert debit_body["payment_amount"] == {"value": 15000, "currency": "INR"}
        assert debit_body["challenge_id"] == token_body["challenge_id"]
        assert token_body["payment_method"] == "RESERVE_PAY"
        assert token_request.headers["X-Customer-Key"] == "ck_smoke"
        assert token_request.headers["Authorization"] == "Bearer server-access-token"
        assert token_body["customer"] == {"mobile_number": "9876543210"}
        assert token_body["challenge_id"]
        assert token_body["payment_amount"] == {"value": 15000, "currency": "INR"}
    finally:
        client.close()


def test_protected_resource_call_is_not_bounded_by_sdk_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    internal_timeouts: list[float | None] = []
    resource_timeouts: list[float | None] = []

    class FakeInternalClient:
        def request(self, method, url, **kwargs):  # noqa: ANN001, ANN202
            internal_timeouts.append(kwargs.get("timeout"))
            if url.endswith("/api/auth/v1/token"):
                return httpx.Response(
                    200,
                    json={"data": {"access_token": "client-access-token", "expires_in": 300}},
                )
            if url.endswith("/api/v1/customer/mpp/token"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "payment_token": "tok_runtime",
                            "expires_in": 300,
                            "type": "RESERVE_PAY",
                            "payment_method_reference_id": "auth_runtime",
                        }
                    },
                )
            raise AssertionError(f"unexpected internal url {url}")

        def close(self):  # noqa: ANN201
            pass

    class FakeResourceClient:
        def __init__(self) -> None:
            self._attempt = 0

        def request(self, method, url, **kwargs):  # noqa: ANN001, ANN202
            resource_timeouts.append(kwargs.get("timeout"))
            self._attempt += 1
            if self._attempt == 1:
                return httpx.Response(
                    402,
                    json={"status": 402, "challengeId": "ch_runtime"},
                    headers={
                        "WWW-Authenticate": "Payment "
                        + encode_json(
                            {
                                "id": "ch_runtime",
                                "realm": "Pine Labs Online P3P",
                                "paymentGateway": "PINE LABS ONLINE",
                                "intent": "charge",
                                "request": {
                                    "scheme": "exact",
                                    "amount": "100.00",
                                    "currency": "INR",
                                    "resource": "/api/premium",
                                    "availablePaymentMethods": ["RESERVE_PAY", "OTM"],
                                },
                                "expires": "2030-01-01T00:00:00Z",
                            }
                        ),
                    },
                )
            return httpx.Response(200, json={"ok": True}, headers={"Payment-Receipt": ""})

        def close(self):  # noqa: ANN201
            pass

    fake_internal = FakeInternalClient()
    fake_resource = FakeResourceClient()
    created = 0

    def _patched_client(*args, **kwargs):  # noqa: ANN001, ANN202
        nonlocal created
        created += 1
        return fake_internal if created == 1 else fake_resource

    monkeypatch.setattr("pinelabs_p3p_client.client.pine_labs_online_client.httpx.Client", _patched_client)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            customerAuthMode=P3PCustomerAuthMode.CustomerKey,
            clientId="client-id",
            clientSecret="client-secret",
            merchantId="merchant-test",
            env=P3PEnvironment.SANDBOX,
            requestTimeoutMs=10_000,
            maxRetries=0,
        )
    )
    try:
        response = client.get(
            "https://server.test/api/premium",
            context=ClientRuntimeContext(
                customerKey="ck_test",
                customerReference="9876543210",
                mobileNumber="9876543210",
                paymentMethod=PaymentMethod.RESERVE_PAY,
            ),
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert internal_timeouts == [10.0, 10.0]
    assert resource_timeouts == [None, None]
