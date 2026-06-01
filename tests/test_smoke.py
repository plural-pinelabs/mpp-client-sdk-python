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

def _server_config(base_url: str) -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="server-id",
        clientSecret="server-secret",
        paymentGateway=ServerPaymentGateway.PineLabsOnline,
        availablePaymentMethods=[ServerPaymentMethod.UPI_RESERVE_PAY, ServerPaymentMethod.Crypto],
        realm=P3PEnvironment.SANDBOX,
        env=base_url,
        maxRetries=0,
    )


def _client_config(base_url: str) -> PineLabsOnlineClientConfig:
    return PineLabsOnlineClientConfig(
        selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
        customerAuthMode=P3PCustomerAuthMode.CustomerKey,
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
    assert challenge.request.availablePaymentMethods == [PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto]


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
                        "payment_method": body.get("payment_method", "SBMD"),
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
                        "type": "SBMD",
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
        customerReference=credential.payload.customer_reference,
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
        assert receipt.paymentMethod == PaymentMethod.UPI_RESERVE_PAY
        assert receipt.settlement.amount == "150.00"
        assert receipt.settlement.currency == "INR"
        debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
        debit_body = json.loads(debit_request.content.decode() or "{}")
        token_request = next(req for req in transport.requests if req.url.path == "/api/v1/customer/mpp/token")
        token_body = json.loads(token_request.content.decode() or "{}")
        assert token_request.url.host == "api.test"
        assert debit_body["customer"] == {"mobile_number": "9876543210"}
        assert debit_body["payment_method"] == "SBMD"
        assert debit_body["payment_amount"] == {"value": 15000, "currency": "INR"}
        assert debit_body["challenge_id"] == token_body["challenge_id"]
        assert token_body["payment_method"] == "SBMD"
        assert token_request.headers["X-Customer-Key"] == "ck_smoke"
        assert "Authorization" not in token_request.headers
        assert token_body["customer"] == {"mobile_number": "9876543210"}
        assert token_body["challenge_id"]
        assert token_body["payment_amount"] == {"value": 15000, "currency": "INR"}
    finally:
        client.close()
