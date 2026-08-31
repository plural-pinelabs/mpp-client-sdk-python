from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from ..config.environments import P3PEnvironment
from ..types.config import P3PLogger, PineLabsOnlineClientConfig
from ..types.config import P3PCustomerAuthMode
from ..types.mandate import Amount
from ..types.payment import PaymentMethod
from ..types.token import (
    CreateTokenOptions,
    Token,
    TokenHold,
    TokenUsage,
    UsageLimits,
)
from ..utils.errors import P3PError, P3PNetworkError
from ..utils.fetch_helpers import request_with_retry
from ..utils.validation import resolve_customer_auth_mode, validate_create_token_options
from .auth_manager import AuthManager

CUSTOMER_TOKEN_PATH = "/api/v1/customer/mpp/token"
CENTRAL_TOKEN_PATH = "/mpp/v1/token"
CUSTOMER_TOKEN_SANDBOX_BASE_URL = "https://api-staging.pluralonline.com"
CUSTOMER_TOKEN_PRODUCTION_BASE_URL = "https://api.pluralonline.com"


def _amount_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(float(value or 0))


def _payment_method_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _customer_payload(mobile_number: str, customer_auth_mode: P3PCustomerAuthMode) -> Dict[str, str]:
    if customer_auth_mode == P3PCustomerAuthMode.CustomerKey:
        return {"mobile_number": mobile_number}
    return {"mobile_number": mobile_number}


def _amount_payload(amount: Amount) -> Dict[str, Any]:
    return {"value": int(amount.value), "currency": amount.currency}


def _customer_token_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized == P3PEnvironment.SANDBOX:
        return CUSTOMER_TOKEN_SANDBOX_BASE_URL
    if normalized == P3PEnvironment.PRODUCTION:
        return CUSTOMER_TOKEN_PRODUCTION_BASE_URL
    return normalized


class ApiClient:
    """Low-level P3P service client used by `ClientMethods` and the 402 interceptor."""

    def __init__(
        self,
        config: PineLabsOnlineClientConfig,
        base_url: str,
        http_client: httpx.Client,
        timeout_ms: Optional[int] = None,
        logger: Optional[P3PLogger] = None,
        max_retries: Optional[int] = None,
        initial_retry_delay_ms: Optional[int] = None,
        auth: AuthManager | None = None,
    ) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._http = http_client
        self._timeout_ms = timeout_ms
        self._logger = logger
        self._max_retries = max_retries
        self._initial_retry_delay_ms = initial_retry_delay_ms
        self._auth = auth

    # ── Public API ──────────────────────────────────────────────

    def create_token(self, options: CreateTokenOptions) -> Token:
        """Create a one-time payment token for an active authorization.

        The current P3P contract requires `type`, nested `customer`,
        `challenge_id`, and `payment_amount`.
        """
        customer_auth_mode = resolve_customer_auth_mode(self._config)
        validate_create_token_options(options, customer_auth_mode)

        payment_method = options.paymentMethod
        mobile_number = options.mobileNumber or ""
        payment_amount = options.paymentAmount or Amount(
            value=options.usageLimits.maxAmount,
            currency=options.usageLimits.currency,
        )
        body: Dict[str, Any] = {
            "payment_method": _payment_method_value(payment_method),
            "customer": _customer_payload(mobile_number, customer_auth_mode),
            "challenge_id": options.challengeId,
            "payment_amount": _amount_payload(payment_amount),
        }
        payment_method_reference_id = str(options.paymentMethodReferenceId or "").strip()
        if payment_method_reference_id:
            body["payment_method_reference_id"] = payment_method_reference_id
        headers = self._auth_headers(customer_auth_mode, options.customerKey)

        is_customer_key_mode = customer_auth_mode == P3PCustomerAuthMode.CustomerKey
        token_path = CUSTOMER_TOKEN_PATH if is_customer_key_mode else CENTRAL_TOKEN_PATH
        base_url = _customer_token_base_url(self._base_url) if is_customer_key_mode else self._base_url
        data = self._request("POST", token_path, body, headers, base_url=base_url)
        return _parse_token(data)

    def _auth_headers(self, customer_auth_mode: P3PCustomerAuthMode, customer_key: Optional[str]) -> Dict[str, str]:
        if self._auth is None:
            raise P3PError(
                "P3P_AUTHENTICATION_FAILED",
                "Auth manager is not configured",
                500,
            )
        headers = {"Authorization": f"Bearer {self._auth.get_access_token()}"}
        if customer_auth_mode == P3PCustomerAuthMode.CustomerKey:
            value = str(customer_key or "").strip()
            if value:
                headers["X-Customer-Key"] = value
        return headers

    # ── Internal ────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        base_url: Optional[str] = None,
    ) -> Any:
        """Send a P3P request and unwrap `{data: ...}` responses."""
        url = f"{(base_url or self._base_url).rstrip('/')}{path}"
        headers: Dict[str, str] = {
            "Accept": "application/json",
        }
        headers["Merchant-ID"] = self._config.merchantId
        if extra_headers:
            headers.update(extra_headers)

        json_body = None
        if body is not None and method != "GET":
            headers["Content-Type"] = "application/json"
            json_body = body

        try:
            response = request_with_retry(
                self._http,
                method,
                url,
                headers=headers,
                json=json_body,
                timeout_ms=self._timeout_ms,
                logger=self._logger,
                max_retries=self._max_retries,
                initial_retry_delay_ms=self._initial_retry_delay_ms,
            )
        except Exception as exc:
            if isinstance(exc, (httpx.HTTPError, TimeoutError)):
                raise P3PNetworkError(f"Network error calling {method} {path}", exc) from exc
            raise

        if response.status_code >= 400:
            try:
                err_body = response.json()
            except Exception:
                err_body = {"error": {"code": "MPP_INTERNAL_ERROR", "message": f"HTTP {response.status_code}"}}
            raise P3PError.from_response(response.status_code, err_body)

        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


# ── Parsers ────────────────────────────────────────────────────────

def _parse_token(data: Dict[str, Any]) -> Token:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    hold = data.get("hold") or {}
    usage = data.get("usage") or {}
    ul = data.get("usage_limits") or {}
    payment_token = data.get("payment_token") or data.get("token") or data.get("token_id", "")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    authorization_id = (
        data.get("payment_method_reference_id")
        or data.get("authorization_id")
        or data.get("authorizationId")
        or data.get("mandate_id")
        or data.get("mandateId")
        or data.get("pre_authorization_id")
        or data.get("preAuthorizationId")
        or data.get("order_id")
        or data.get("orderId")
        or metadata.get("payment_method_reference_id")
        or metadata.get("authorization_id")
        or metadata.get("authorizationId")
        or metadata.get("pre_authorization_id")
        or metadata.get("preAuthorizationId")
        or metadata.get("external_subscription_id")
        or ""
    )
    payment_amount = data.get("payment_amount") or data.get("paymentAmount")
    return Token(
        token_id=payment_token,
        object=data.get("object", "p3p_payment_token"),
        customer_reference=customer.get("merchant_customer_reference", data.get("merchant_customer_reference", data.get("customer_reference", data.get("customer_id", "")))),
        customer_id=customer.get("customer_id", data.get("customer_id", data.get("customer_reference", ""))),
        mobile_number=customer.get("mobile_number", data.get("mobile_number")),
        mandate_id=authorization_id,
        token=payment_token,
        payment_method=_parse_payment_method(data.get("payment_method", data.get("type"))),
        payment_amount=Amount(
            value=_amount_int(payment_amount.get("value", 0)),
            currency=payment_amount.get("currency", "INR"),
        ) if isinstance(payment_amount, dict) else None,
        challenge_id=data.get("challenge_id"),
        hold=TokenHold(
            amount=hold.get("amount", 0),
            status=hold.get("status", ""),
            expires_at=hold.get("expires_at", ""),
        ),
        usage_limits=UsageLimits(
            max_amount=ul.get("max_amount", 0),
            currency=ul.get("currency", "INR"),
            expires_at=ul.get("expires_at", ""),
            max_charges=ul.get("max_charges"),
        ),
        usage=TokenUsage(
            amount_used=usage.get("amount_used", 0),
            charges_made=usage.get("charges_made", 0),
        ),
        expires_in=int(data.get("expires_in", 0) or 0),
        metadata=data.get("metadata") or {"type": data.get("type", "RESERVE_PAY")},
        created_at=data.get("created_at", ""),
        raw=data,
    )


def _parse_payment_method(value: Any) -> Optional[PaymentMethod]:
    if value == PaymentMethod.RESERVE_PAY.value:
        return PaymentMethod.RESERVE_PAY
    if value == PaymentMethod.OTM.value:
        return PaymentMethod.OTM
    if value == PaymentMethod.CARD.value:
        return PaymentMethod.CARD
    if value == PaymentMethod.CREDIT_EMI.value:
        return PaymentMethod.CREDIT_EMI
    if value == PaymentMethod.Crypto.value:
        return PaymentMethod.Crypto
    return None
