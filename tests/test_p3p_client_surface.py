from __future__ import annotations

import json

import httpx
import pytest

from pinelabs_p3p_client import (
    Amount,
    ClientRuntimeContext,
    CreateTokenOptions,
    P3PChallengeError,
    P3PCustomerAuthMode,
    P3PEnvironment,
    PaymentMethod,
    PineLabsOnlineClient,
    PineLabsOnlineClientConfig,
)
from pinelabs_p3p_client.client.credential_builder import encode_json, decode_json


class _ClientTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/premium":
            credential = request.headers.get("P3P-Credential", "")
            if not credential.startswith("Payment "):
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
                                    "availablePaymentMethods": ["RESERVE_PAY", "CRYPTO"],
                                },
                                "expires": "2030-01-01T00:00:00Z",
                            }
                        ),
                    },
                )
            return httpx.Response(200, json={"ok": True}, headers={"Payment-Receipt": ""})

        if request.url.path == "/api/v1/customer/mpp/token":
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

        if request.url.path == "/api/auth/v1/token":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "access_token": "client-access-token",
                        "expires_in": 300,
                    }
                },
            )

        if request.url.path == "/mpp/v1/token":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_token": "tok_client_credentials",
                        "expires_in": 300,
                        "type": "RESERVE_PAY",
                        "payment_method_reference_id": "auth_client_credentials",
                    }
                },
            )

        return httpx.Response(404, json={"error": {"message": request.url.path}})


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)


def test_client_uses_runtime_context_customer_token_endpoint_and_p3p_header(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ClientTransport()
    _patch_httpx_client(monkeypatch, transport)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            customerAuthMode=P3PCustomerAuthMode.CustomerKey,
            clientId="client-client",
            clientSecret="client-secret",
            env=P3PEnvironment.SANDBOX,
        )
    )
    try:
        response = client.get(
            "https://server.test/api/premium",
            context=ClientRuntimeContext(
                customerKey="ck_test",
                customerReference="9876543210",
                mobileNumber="9876543210",
            ),
        )
    finally:
        client.close()

    assert response.status_code == 200
    token_request = next(req for req in transport.requests if req.url.path == "/api/v1/customer/mpp/token")
    token_body = json.loads(token_request.content.decode() or "{}")
    assert token_request.url.host == "api-staging.pluralonline.com"
    assert token_request.headers["X-Customer-Key"] == "ck_test"
    assert token_request.headers["Authorization"] == "Bearer client-access-token"
    assert token_body == {
        "payment_method": "RESERVE_PAY",
        "customer": {"mobile_number": "9876543210"},
        "challenge_id": "ch_runtime",
        "payment_amount": {"value": 10000, "currency": "INR"},
    }

    paid_retry = next(
        req for req in reversed(transport.requests)
        if req.url.path == "/api/premium" and req.headers.get("P3P-Credential", "").startswith("Payment ")
    )
    assert "Authorization" not in paid_retry.headers
    credential = decode_json(paid_retry.headers["P3P-Credential"].removeprefix("Payment ").strip())
    assert credential["source"] == "9876543210"
    assert "paymentGateway" not in credential["challenge"]
    assert credential["payload"]["customer_reference"] == "9876543210"
    assert credential["payload"]["mobile_number"] == "9876543210"
    assert credential["payload"]["payment_method"] == "RESERVE_PAY"


def test_client_defaults_to_client_credentials_token_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ClientTransport()
    _patch_httpx_client(monkeypatch, transport)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            clientId="client-client",
            clientSecret="client-secret",
            env=P3PEnvironment.SANDBOX,
        )
    )
    try:
        token = client.methods.create_token(
            CreateTokenOptions(
                customerReference="cust-ref-default",
                challengeId="ch_default",
                paymentAmount=Amount(value=100, currency="INR"),
            )
        )
    finally:
        client.close()

    assert token.token == "tok_client_credentials"

    auth_request = next(req for req in transport.requests if req.url.path == "/api/auth/v1/token")
    auth_body = json.loads(auth_request.content.decode() or "{}")
    assert auth_body == {
        "grant_type": "client_credentials",
        "client_id": "client-client",
        "client_secret": "client-secret",
    }

    token_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/token")
    token_body = json.loads(token_request.content.decode() or "{}")
    assert token_request.url.host == "pluraluat.v2.pinepg.in"
    assert token_request.headers["Authorization"] == "Bearer client-access-token"
    assert "X-Customer-Key" not in token_request.headers
    assert token_body == {
        "payment_method": "RESERVE_PAY",
        "customer": {"merchant_customer_reference": "cust-ref-default"},
        "challenge_id": "ch_default",
        "payment_amount": {"value": 100, "currency": "INR"},
    }


def test_client_uses_separate_http_clients_for_internal_and_resource_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    created_kwargs: list[dict] = []

    class DummyClient:
        def __init__(self, *args, **kwargs):
            created_kwargs.append(dict(kwargs))

        def request(self, *args, **kwargs):
            raise AssertionError("request should not be called in this constructor test")

        def close(self):
            pass

    monkeypatch.setattr("pinelabs_p3p_client.client.pine_labs_online_client.httpx.Client", DummyClient)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            env=P3PEnvironment.SANDBOX,
            clientId="cid",
            clientSecret="secret",
            requestTimeoutMs=10_000,
        )
    )
    client.close()

    assert len(created_kwargs) == 2
    assert created_kwargs[0] == {}
    assert created_kwargs[1] == {}


def test_client_credentials_default_requires_client_credentials() -> None:
    with pytest.raises(ValueError, match="clientId and clientSecret"):
        PineLabsOnlineClient.create(
            PineLabsOnlineClientConfig(
                selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
                env=P3PEnvironment.SANDBOX,
            )
        )


def test_customer_key_mode_remains_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ClientTransport()
    _patch_httpx_client(monkeypatch, transport)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            customerAuthMode=P3PCustomerAuthMode.CustomerKey,
            clientId="client-client",
            clientSecret="client-secret",
            env=P3PEnvironment.SANDBOX,
        )
    )
    try:
        token = client.methods.create_token(
            CreateTokenOptions(
                customerKey="ck_test",
                mobileNumber="9876543210",
                challengeId="ch_customer_key",
                paymentAmount=Amount(value=100, currency="INR"),
            )
        )
    finally:
        client.close()

    assert token.token == "tok_runtime"
    token_request = next(req for req in transport.requests if req.url.path == "/api/v1/customer/mpp/token")
    token_body = json.loads(token_request.content.decode() or "{}")
    assert token_request.url.host == "api-staging.pluralonline.com"
    assert token_request.headers["X-Customer-Key"] == "ck_test"
    assert token_request.headers["Authorization"] == "Bearer client-access-token"
    assert token_body == {
        "payment_method": "RESERVE_PAY",
        "customer": {"mobile_number": "9876543210"},
        "challenge_id": "ch_customer_key",
        "payment_amount": {"value": 100, "currency": "INR"},
    }


def test_customer_key_mode_defaults_to_production_customer_token_host(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ClientTransport()
    _patch_httpx_client(monkeypatch, transport)

    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            customerAuthMode=P3PCustomerAuthMode.CustomerKey,
            clientId="client-client",
            clientSecret="client-secret",
        )
    )
    try:
        token = client.methods.create_token(
            CreateTokenOptions(
                customerKey="ck_test",
                mobileNumber="9876543210",
                challengeId="ch_customer_key",
                paymentAmount=Amount(value=100, currency="INR"),
            )
        )
    finally:
        client.close()

    assert token.token == "tok_runtime"
    auth_request = next(req for req in transport.requests if req.url.path == "/api/auth/v1/token")
    auth_body = json.loads(auth_request.content.decode() or "{}")
    assert auth_body == {
        "grant_type": "client_credentials",
        "client_id": "client-client",
        "client_secret": "client-secret",
    }
    token_request = next(req for req in transport.requests if req.url.path == "/api/v1/customer/mpp/token")
    assert token_request.url.host == "api.pluralonline.com"
    assert token_request.headers["Authorization"] == "Bearer client-access-token"


def test_client_requires_runtime_context_for_auto_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ClientTransport()
    _patch_httpx_client(monkeypatch, transport)
    client = PineLabsOnlineClient.create(
        PineLabsOnlineClientConfig(
            selectedPaymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            customerAuthMode=P3PCustomerAuthMode.CustomerKey,
            clientId="client-client",
            clientSecret="client-secret",
            env=P3PEnvironment.SANDBOX,
        )
    )
    try:
        with pytest.raises(RuntimeError, match="ClientRuntimeContext"):
            client.get("https://server.test/api/premium")
    finally:
        client.close()


def test_client_surface_has_no_mpp_aliases() -> None:
    import pinelabs_p3p_client as client

    assert hasattr(client, "P3PEnvironment")
    assert not hasattr(client, "MppEnvironment")
    assert hasattr(client, "P3PError")
    assert not hasattr(client, "MppError")
    assert P3PChallengeError.__name__ == "P3PChallengeError"
