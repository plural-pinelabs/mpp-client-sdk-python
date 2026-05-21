from __future__ import annotations

from typing import Optional

import httpx

from ..config.environments import DEFAULT_BASE_URL
from ..types.challenge import Challenge, Credential
from ..types.config import PluralBuyerConfig
from ..types.grantex import GrantTokenClaims
from ..types.mandate import CreateMandateOptions, Mandate
from ..types.token import CreateTokenOptions, Token
from ..utils.validation import validate_config
from .api_client import ApiClient
from .auth_manager import AuthManager
from .fetch_interceptor import FetchInterceptor


class BuyerMethods:
    """Direct MPP API methods exposed under `buyer.methods`.

    These methods call the MPP service directly and do not intercept seller
    HTTP 402 responses. Use `buyer.get/post/request` for automatic 402 flows.
    """

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def create_mandate(self, options: CreateMandateOptions) -> Mandate:
        """Create a mandate/pre-authorization via `POST /mpp/v1/pre-authorize`."""
        return self._api.create_mandate(options)

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch mandate/pre-authorization status via `GET /mpp/v1/authorization/{id}`."""
        return self._api.get_mandate(mandate_id)

    def create_token(self, options: CreateTokenOptions) -> Token:
        """Create a one-time payment token via `POST /mpp/v1/token`."""
        return self._api.create_token(options)


class PluralBuyerInstance:
    """Handle returned by :meth:`PluralBuyer.create`. Exposes:

    - `request`/`get`/`post`/... — fetch-like HTTP methods with 402 interception
    - `raw_request`/`raw_http` — the underlying httpx client (no interception)
    - `methods` — direct MPP API operations (create_mandate, create_token, ...)
    - `create_credential(challenge)` — manually build a credential
    - `grant_claims` / `verify_grant()` — Grantex helpers
    """

    def __init__(
        self,
        interceptor: FetchInterceptor,
        http_client: httpx.Client,
        methods: BuyerMethods,
    ) -> None:
        self._interceptor = interceptor
        self._http = http_client
        self.methods = methods
        self.grant_claims: Optional[GrantTokenClaims] = None

    # ── Intercepting HTTP API ───────────────────────────────────

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an HTTP request and automatically handle MPP 402 challenges."""
        return self._interceptor.request(method, url, **kwargs)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self._interceptor.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self._interceptor.post(url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self._interceptor.put(url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self._interceptor.delete(url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self._interceptor.patch(url, **kwargs)

    # Alias matching the Node SDK's `fetch` naming
    def fetch(self, url: str, method: str = "GET", **kwargs) -> httpx.Response:
        """Fetch-style alias for `request`, matching the TypeScript SDK naming."""
        return self._interceptor.request(method, url, **kwargs)

    @property
    def raw_http(self) -> httpx.Client:
        return self._http

    def raw_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an HTTP request without automatic 402 payment handling."""
        return self._http.request(method, url, **kwargs)

    # ── Credential / Grantex helpers ────────────────────────────

    def create_credential(self, challenge: Challenge) -> Credential:
        """Manually create a Payment credential for a decoded seller challenge."""
        return self._interceptor.create_credential_for_challenge(challenge)

    def verify_grant(self) -> Optional[GrantTokenClaims]:
        """Verify the configured Grantex grant token and cache its claims."""
        claims = self._interceptor.verify_grant()
        self.grant_claims = claims
        return claims

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PluralBuyerInstance":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class PluralBuyer:
    """Factory for buyer SDK instances."""

    @staticmethod
    def create(config: PluralBuyerConfig) -> PluralBuyerInstance:
        """Create a buyer SDK instance from `PluralBuyerConfig`."""
        validate_config(config)

        auth_base_url = config.authBaseUrl or config.baseUrl or DEFAULT_BASE_URL
        mpp_base_url = config.mppBaseUrl or config.baseUrl or DEFAULT_BASE_URL
        request_timeout = (config.requestTimeoutMs / 1000.0) if config.requestTimeoutMs else None
        http_client = httpx.Client(timeout=request_timeout)

        auth_manager = AuthManager(
            config.clientId,
            config.clientSecret,
            auth_base_url,
            http_client,
            config.requestTimeoutMs,
            config.logger,
            config.maxRetries,
            config.initialRetryDelayMs,
            config.accessToken,
        )

        api_client = ApiClient(
            mpp_base_url,
            auth_manager,
            http_client,
            config.requestTimeoutMs,
            config.logger,
            config.maxRetries,
            config.initialRetryDelayMs,
        )

        interceptor = FetchInterceptor(config, api_client, http_client)
        methods = BuyerMethods(api_client)
        return PluralBuyerInstance(interceptor, http_client, methods)

    @staticmethod
    def create_verified(config: PluralBuyerConfig) -> PluralBuyerInstance:
        """Create an instance and verify the Grantex grant token immediately.

        Raises if verification fails.
        """
        instance = PluralBuyer.create(config)
        if config.grantex is not None:
            instance.verify_grant()
        return instance
