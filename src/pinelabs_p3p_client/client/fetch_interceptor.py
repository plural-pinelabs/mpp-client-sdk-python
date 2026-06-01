from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Any, Dict, Optional

import httpx

from ..types.challenge import Challenge, Credential
from ..types.config import ClientRuntimeContext, P3PCustomerAuthMode, PineLabsOnlineClientConfig
from ..types.token import CreateTokenOptions
from ..utils.validation import resolve_customer_auth_mode
from .api_client import ApiClient
from .credential_builder import (
    build_credential,
    decode_challenge,
    decode_receipt,
    encode_credential_header,
    extract_amount_paise,
    select_payment_method,
)
from ..types.mandate import Amount

def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        try:
            asyncio.get_event_loop().run_until_complete(result)
        except RuntimeError:
            asyncio.run(result)


class FetchInterceptor:
    """Wraps an httpx.Client to intercept HTTP 402 responses and transparently
    complete the P3P payment flow.
    """

    def __init__(
        self,
        config: PineLabsOnlineClientConfig,
        api_client: ApiClient,
        http_client: httpx.Client,
    ) -> None:
        self._config = config
        self._api = api_client
        self._http = http_client

    # ── Fetch wrapper ───────────────────────────────────────────

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        context: Optional[ClientRuntimeContext] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """HTTP request with automatic 402-challenge handling."""
        auto_handle = self._config.autoHandlePayment is not False
        response = self._http.request(method, url, headers=headers, **kwargs)

        if response.status_code != 402 or not auto_handle:
            return response

        www_auth = response.headers.get("WWW-Authenticate")
        if not www_auth or not www_auth.startswith("Payment "):
            return response

        return self._handle_402(method, url, headers, kwargs, www_auth, context)

    # Convenience aliases
    def get(self, url: str, *, context: Optional[ClientRuntimeContext] = None, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, context=context, **kwargs)

    def post(self, url: str, *, context: Optional[ClientRuntimeContext] = None, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, context=context, **kwargs)

    def put(self, url: str, *, context: Optional[ClientRuntimeContext] = None, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, context=context, **kwargs)

    def delete(self, url: str, *, context: Optional[ClientRuntimeContext] = None, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, context=context, **kwargs)

    def patch(self, url: str, *, context: Optional[ClientRuntimeContext] = None, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, context=context, **kwargs)

    # ── Credential building ─────────────────────────────────────

    def create_credential_for_challenge(
        self,
        challenge: Challenge,
        context: Optional[ClientRuntimeContext] = None,
    ) -> Credential:
        """Create a one-time P3P token and wrap it in a Payment credential."""
        payment_method = select_payment_method(challenge, self._config.selectedPaymentMethod)
        customer_context = _resolve_customer_context(context, resolve_customer_auth_mode(self._config))
        token = self._api.create_token(
            CreateTokenOptions(
                customerKey=customer_context.customerKey,
                customerReference=customer_context.customerReference,
                mobileNumber=customer_context.mobileNumber,
                challengeId=challenge.id,
                paymentAmount=Amount(value=extract_amount_paise(challenge), currency=challenge.request.currency),
                paymentMethod=payment_method,
            )
        )
        return build_credential(
            challenge,
            customer_context.credential_source,
            token.token,
            payment_method,
            customer_reference=customer_context.customerReference,
            mobile_number=customer_context.mobileNumber,
        )

    # ── Internal 402 flow ───────────────────────────────────────

    def _handle_402(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        kwargs: Dict[str, Any],
        www_auth_header: str,
        context: Optional[ClientRuntimeContext],
    ) -> httpx.Response:
        challenge = decode_challenge(www_auth_header)

        if self._config.onChallenge is not None:
            _maybe_await(self._config.onChallenge(challenge))

        credential = self.create_credential_for_challenge(challenge, context)
        credential_header = encode_credential_header(credential)

        retry_headers: Dict[str, str] = dict(headers or {})
        retry_headers["P3P-Credential"] = credential_header

        retry_response = self._http.request(method, url, headers=retry_headers, **kwargs)

        if retry_response.is_success:
            if self._config.onPaymentComplete is not None:
                receipt_header = retry_response.headers.get("Payment-Receipt")
                if receipt_header:
                    try:
                        receipt = decode_receipt(receipt_header)
                        _maybe_await(self._config.onPaymentComplete(receipt))
                    except Exception:
                        pass  # receipt decode failure is non-fatal

        return retry_response


@dataclass
class _ResolvedClientRuntimeContext:
    customerKey: Optional[str] = None
    customerReference: Optional[str] = None
    mobileNumber: Optional[str] = None
    credential_source: str = ""


def _resolve_customer_context(
    context: Optional[ClientRuntimeContext],
    customer_auth_mode: P3PCustomerAuthMode,
) -> _ResolvedClientRuntimeContext:
    customer_key = _required_text(getattr(context, "customerKey", None))
    customer_reference = _required_text(getattr(context, "customerReference", None))
    mobile_number = _required_text(getattr(context, "mobileNumber", None))
    if customer_auth_mode == P3PCustomerAuthMode.CustomerKey:
        if not customer_key or not mobile_number:
            raise RuntimeError(
                "ClientRuntimeContext: customerKey and mobileNumber are required when customerAuthMode is CUSTOMER_KEY"
            )
        return _ResolvedClientRuntimeContext(
            customerKey=customer_key,
            customerReference=customer_reference,
            mobileNumber=mobile_number,
            credential_source=customer_reference or mobile_number,
        )

    if not customer_reference and not mobile_number:
        raise RuntimeError(
            "ClientRuntimeContext: customerReference or mobileNumber is required when customerAuthMode is CLIENT_CREDENTIALS"
        )
    return _ResolvedClientRuntimeContext(
        customerReference=customer_reference,
        mobileNumber=mobile_number,
        credential_source=customer_reference or mobile_number or "",
    )


def _required_text(value: Optional[str]) -> Optional[str]:
    trimmed = str(value or "").strip()
    return trimmed or None
