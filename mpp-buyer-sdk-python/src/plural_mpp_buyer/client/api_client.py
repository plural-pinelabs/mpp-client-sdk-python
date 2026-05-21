from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from ..types.config import MppLogger
from ..types.mandate import Amount, CreateMandateOptions, Mandate, MandateChallenge
from ..types.token import (
    CreateTokenOptions,
    Token,
    TokenHold,
    TokenUsage,
    UsageLimits,
)
from ..utils.errors import MppError, MppNetworkError
from ..utils.fetch_helpers import request_with_retry
from ..utils.validation import (
    normalize_mandate_mobile_number,
    validate_create_mandate_options,
    validate_create_token_options,
)
from .auth_manager import AuthManager


def _amount_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(float(value or 0))


class ApiClient:
    """Low-level MPP service client used by `BuyerMethods` and the 402 interceptor."""

    def __init__(
        self,
        base_url: str,
        auth_manager: AuthManager,
        http_client: httpx.Client,
        timeout_ms: Optional[int] = None,
        logger: Optional[MppLogger] = None,
        max_retries: Optional[int] = None,
        initial_retry_delay_ms: Optional[int] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth_manager
        self._http = http_client
        self._timeout_ms = timeout_ms
        self._logger = logger
        self._max_retries = max_retries
        self._initial_retry_delay_ms = initial_retry_delay_ms

    # ── Public API ──────────────────────────────────────────────

    def create_mandate(self, options: CreateMandateOptions) -> Mandate:
        """Create an MPP mandate/pre-authorization.

        Maps `CreateMandateOptions` to the `/mpp/v1/pre-authorize` contract
        and normalizes the response into a `Mandate`.
        """
        validate_create_mandate_options(options)

        customer_reference = options.customerReference or options.customerId or normalize_mandate_mobile_number(options.mobileNumber)
        body: Dict[str, Any] = {
            "type": options.paymentType,
            "customer_reference": customer_reference,
            "amount": {"value": str(options.amount.value), "currency": options.amount.currency},
            "validity_in_days": int(options.validityInDays),
        }
        if options.description:
            body["description"] = options.description

        headers = {"Idempotency-Key": options.idempotencyKey or str(uuid.uuid4())}
        data = self._request("POST", "/mpp/v1/pre-authorize", body, headers)
        return _parse_mandate(data)

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch a mandate/pre-authorization by authorization id."""
        if not mandate_id:
            raise ValueError("mandate_id is required")
        data = self._request("GET", f"/mpp/v1/authorization/{quote(mandate_id, safe='')}")
        return _parse_mandate(data)

    def create_token(self, options: CreateTokenOptions) -> Token:
        """Create a one-time payment token for an active authorization.

        The current MPP contract requires `type` and `customer_reference`; the
        SDK intentionally does not send a mandate id in this request.
        """
        validate_create_token_options(options)

        customer_reference = options.customerReference or options.customerId
        body: Dict[str, Any] = {
            "type": options.paymentType,
            "customer_reference": customer_reference or "",
        }

        data = self._request("POST", "/mpp/v1/token", body)
        return _parse_token(data)

    # ── Internal ────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Send an authenticated MPP request and unwrap `{data: ...}` responses."""
        access_token = self._auth.get_access_token()
        url = f"{self._base_url}{path}"
        headers: Dict[str, str] = {
            "Accept": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
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
                raise MppNetworkError(f"Network error calling {method} {path}", exc) from exc
            raise

        if response.status_code >= 400:
            try:
                err_body = response.json()
            except Exception:
                err_body = {"error": {"code": "MPP_INTERNAL_ERROR", "message": f"HTTP {response.status_code}"}}
            raise MppError.from_response(response.status_code, err_body)

        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


# ── Parsers ────────────────────────────────────────────────────────

def _parse_mandate(data: Dict[str, Any]) -> Mandate:
    metadata = data.get("metadata") or {}
    sbmd_data = metadata.get("sbmd_data") or metadata.get("sbmdData") or {}
    challenge = data.get("challenge")
    mandate_challenge = None
    challenge_url = data.get("challenge_url") or data.get("challengeUrl")
    if challenge or challenge_url:
        challenge = challenge or {}
        mandate_challenge = MandateChallenge(
            type=challenge.get("type", sbmd_data.get("challenge_type", "")),
            qr_url=challenge.get("qr_url", challenge_url or ""),
            deep_link=challenge.get("deep_link", challenge_url or ""),
            expires_at=challenge.get("expires_at", data.get("expiry_at", sbmd_data.get("expires_at", ""))),
        )
    amt = data.get("amount") or {}
    amount_value = (
        amt.get("value", data.get("amount_value", metadata.get("amount", 0)))
        if isinstance(amt, dict)
        else data.get("amount_value", metadata.get("amount", 0))
    )
    amount_currency = (
        amt.get("currency", data.get("amount_currency", metadata.get("currency", "INR")))
        if isinstance(amt, dict)
        else data.get("amount_currency", metadata.get("currency", "INR"))
    )
    mandate_id = (
        data.get("authorization_id")
        or data.get("authorizationId")
        or data.get("mandate_id")
        or data.get("mandateId")
        or metadata.get("external_subscription_id")
        or ""
    )
    status = data.get("payment_status") or data.get("order_status") or data.get("status", "")
    return Mandate(
        mandate_id=mandate_id,
        object=data.get("object", "mandate"),
        order_id=data.get("order_id", sbmd_data.get("order_id", "")),
        order_status=data.get("order_status", status),
        payment_status=data.get("payment_status", status),
        customer_reference=data.get("customer_reference", data.get("customer_id", "")),
        customer_id=data.get("customer_id", data.get("customer_reference", "")),
        agent_id=data.get("agent_id", ""),
        amount=Amount(value=_amount_int(amount_value), currency=amount_currency),
        amount_blocked=data.get("amount_blocked", sbmd_data.get("amount_blocked", 0)),
        amount_debited=data.get("amount_debited", sbmd_data.get("amount_debited", 0)),
        amount_held=data.get("amount_held", sbmd_data.get("amount_held", 0)),
        amount_available=data.get("amount_available", sbmd_data.get("amount_available", 0)),
        mobile_number=data.get("mobile_number", ""),
        description=data.get("description", metadata.get("description")),
        metadata=data.get("metadata"),
        expires_at=data.get("expiry_at", data.get("expires_at", sbmd_data.get("expires_at", ""))),
        created_at=data.get("created_at", sbmd_data.get("created_at", "")),
        challenge=mandate_challenge,
        raw=data,
    )


def _parse_token(data: Dict[str, Any]) -> Token:
    hold = data.get("hold") or {}
    usage = data.get("usage") or {}
    ul = data.get("usage_limits") or {}
    payment_token = data.get("payment_token") or data.get("token") or data.get("token_id", "")
    authorization_id = data.get("authorization_id") or data.get("mandate_id", "")
    return Token(
        token_id=payment_token,
        object=data.get("object", "plural_payment_token"),
        customer_reference=data.get("customer_reference", data.get("customer_id", "")),
        customer_id=data.get("customer_id", data.get("customer_reference", "")),
        mandate_id=authorization_id,
        token=payment_token,
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
        metadata=data.get("metadata") or {"type": data.get("type", "SBMD")},
        created_at=data.get("created_at", ""),
        raw=data,
    )
