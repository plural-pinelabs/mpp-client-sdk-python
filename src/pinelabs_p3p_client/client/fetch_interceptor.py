from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Any, Dict, Optional

import httpx

from ..grantex import GrantTokenVerifier
from ..types.challenge import Challenge, Credential
from ..types.config import GRANTEX_TOKEN_HEADER, ClientRuntimeContext, P3PCustomerAuthMode, PineLabsOnlineClientConfig
from ..config.environments import P3PEnvironment
from ..types.token import CreateTokenOptions
from ..types.payment import PaymentMethod
from ..utils.validation import is_supported_payment_method, resolve_customer_auth_mode
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
        request_headers = dict(headers or {})
        _assert_secure_resource_url(url, self._config.env)
        _attach_grantex_header(request_headers, _resolve_grantex_token(self._config, context))
        response = self._http.request(method, url, headers=request_headers or None, **kwargs)

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
        customer_context = _resolve_customer_context(context, resolve_customer_auth_mode(self._config))
        self._verify_grantex_for_payment(context)
        payment_method = select_payment_method(challenge, customer_context.paymentMethod)
        token = self._api.create_token(
            CreateTokenOptions(
                customerKey=customer_context.customerKey,
                mobileNumber=customer_context.mobileNumber,
                challengeId=challenge.id,
                paymentAmount=Amount(value=extract_amount_paise(challenge), currency=challenge.request.currency),
                paymentMethod=payment_method,
                paymentMethodReferenceId=customer_context.paymentMethodReferenceId,
            )
        )
        return build_credential(
            challenge,
            customer_context.credential_source,
            token.token,
            payment_method,
            mobile_number=customer_context.mobileNumber,
            payment_method_reference_id=token.mandate_id or customer_context.paymentMethodReferenceId,
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
        _attach_grantex_header(retry_headers, _resolve_grantex_token(self._config, context))
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

    def _verify_grantex_for_payment(self, context: Optional[ClientRuntimeContext]) -> None:
        if self._config.grantex is None:
            return
        token = _resolve_grantex_token(self._config, context)
        enforce_grant = (
            self._config.grantex.enforce_grant
            if self._config.grantex.enforce_grant is not None
            else self._config.grantex.enforceGrant
        )
        if not token:
            if enforce_grant:
                raise RuntimeError(f"ClientGrantexConfig: {GRANTEX_TOKEN_HEADER} grant token is required")
            return
        if (
            self._config.grantex.verifier is None
            and not self._config.grantex.jwksUri
            and not self._config.grantex.jwksUrl
            and not self._config.grantex.jwks_uri
            and not self._config.grantex.jwks_url
        ):
            if not enforce_grant:
                return  # No verifier and not enforcing — skip client-side verification
            # enforceGrant=True + no explicit verifier → GrantTokenVerifier uses default Grantex JWKS
        result = GrantTokenVerifier(self._config.grantex).verify(token)
        if not result.valid:
            if self._config.logger is not None:
                self._config.logger.error("Grantex grant verification failed", {"error": result.error})
            if enforce_grant:
                raise RuntimeError(result.error or "Grantex grant verification failed")


@dataclass
class _ResolvedClientRuntimeContext:
    customerKey: Optional[str] = None
    mobileNumber: Optional[str] = None
    paymentMethod: Optional[PaymentMethod] = None
    paymentMethodReferenceId: Optional[str] = None
    credential_source: str = ""


def _resolve_customer_context(
    context: Optional[ClientRuntimeContext],
    customer_auth_mode: P3PCustomerAuthMode,
) -> _ResolvedClientRuntimeContext:
    customer_key = _required_text(getattr(context, "customerKey", None))
    mobile_number = _required_text(getattr(context, "mobileNumber", None))
    payment_method = getattr(context, "paymentMethod", None)
    payment_method_reference_id = _required_text(getattr(context, "paymentMethodReferenceId", None))
    if payment_method is None:
        raise RuntimeError("ClientRuntimeContext: paymentMethod is required")
    if not is_supported_payment_method(payment_method):
        raise RuntimeError(_unsupported_payment_method_message("ClientRuntimeContext: paymentMethod", payment_method))
    if customer_auth_mode == P3PCustomerAuthMode.CustomerKey:
        if not customer_key or not mobile_number:
            raise RuntimeError(
                "ClientRuntimeContext: customerKey and mobileNumber are required when customerAuthMode is CUSTOMER_KEY"
            )
        return _ResolvedClientRuntimeContext(
            customerKey=customer_key,
            mobileNumber=mobile_number,
            paymentMethod=payment_method,
            paymentMethodReferenceId=payment_method_reference_id,
            credential_source=mobile_number,
        )

    if not mobile_number:
        raise RuntimeError(
            "ClientRuntimeContext: mobileNumber is required when customerAuthMode is CLIENT_CREDENTIALS"
        )
    return _ResolvedClientRuntimeContext(
        mobileNumber=mobile_number,
        paymentMethod=payment_method,
        paymentMethodReferenceId=payment_method_reference_id,
        credential_source=mobile_number,
    )


def _required_text(value: Optional[str]) -> Optional[str]:
    trimmed = str(value or "").strip()
    return trimmed or None


def _unsupported_payment_method_message(context: str, value: object) -> str:
    if value == PaymentMethod.Crypto:
        return f"{context}: PaymentMethod.Crypto is currently not supported in SDKs"
    return f"{context}: payment method must be RESERVE_PAY, OTM, CARD, or CREDIT_EMI"


def _resolve_grantex_token(
    config: PineLabsOnlineClientConfig,
    context: Optional[ClientRuntimeContext],
) -> Optional[str]:
    value = getattr(context, "grantexToken", None) or getattr(context, "grantex_token", None)
    if value is None and config.grantex is not None:
        value = getattr(config.grantex, "grantToken", None)
    if value is None and config.grantex is not None:
        value = getattr(config.grantex, "grant_token", None)
    trimmed = str(value or "").strip()
    return trimmed or None


def _attach_grantex_header(headers: Dict[str, str], token: Optional[str]) -> None:
    if not token:
        return
    existing_key = next((key for key in headers if key.lower() == GRANTEX_TOKEN_HEADER.lower()), None)
    headers[existing_key or GRANTEX_TOKEN_HEADER] = token


def _assert_secure_resource_url(url: str, env: Optional[str]) -> None:
    if env != P3PEnvironment.PRODUCTION:
        return
    lower = url.lower()
    if not lower.startswith("https://") and not _is_localhost_url(url):
        raise RuntimeError(
            f"P3P credentials must not be sent over plain HTTP in production. Use HTTPS: {url}"
        )


def _is_localhost_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        return (
            hostname in ("localhost", "127.0.0.1", "::1", "host.docker.internal")
            or "." not in hostname
        )
    except Exception:
        return False
