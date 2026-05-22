from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Optional

import httpx

from ..types.challenge import Challenge, Credential
from ..types.config import PluralBuyerConfig
from ..types.token import CreateTokenOptions
from .api_client import ApiClient
from .credential_builder import (
    build_credential,
    decode_challenge,
    decode_receipt,
    encode_credential_header,
)

def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        try:
            asyncio.get_event_loop().run_until_complete(result)
        except RuntimeError:
            asyncio.run(result)


class FetchInterceptor:
    """Wraps an httpx.Client to intercept HTTP 402 responses and transparently
    complete the MPP payment flow.
    """

    def __init__(
        self,
        config: PluralBuyerConfig,
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

        return self._handle_402(method, url, headers, kwargs, www_auth)

    # Convenience aliases
    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    # ── Credential building ─────────────────────────────────────

    def create_credential_for_challenge(self, challenge: Challenge) -> Credential:
        """Create a one-time MPP token and wrap it in a Payment credential."""
        token = self._api.create_token(
            CreateTokenOptions(
                customerReference=self._config.customerReference,
                challengeId=challenge.id,
            )
        )
        return build_credential(
            challenge,
            self._config.clientId,
            token.token,
            customer_reference=self._config.customerReference,
        )

    # ── Internal 402 flow ───────────────────────────────────────

    def _handle_402(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        kwargs: Dict[str, Any],
        www_auth_header: str,
    ) -> httpx.Response:
        challenge = decode_challenge(www_auth_header)

        if self._config.onChallenge is not None:
            _maybe_await(self._config.onChallenge(challenge))

        credential = self.create_credential_for_challenge(challenge)
        credential_header = encode_credential_header(credential)

        retry_headers: Dict[str, str] = dict(headers or {})
        retry_headers["Authorization"] = credential_header

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
