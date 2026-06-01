from __future__ import annotations

import httpx

from ..config.environments import resolve_p3p_base_url
from ..types.challenge import Challenge, Credential
from ..types.config import ClientRuntimeContext, P3PCustomerAuthMode, PineLabsOnlineClientConfig
from ..types.token import CreateTokenOptions, Token
from ..utils.validation import resolve_customer_auth_mode, validate_config
from .api_client import ApiClient
from .auth_manager import AuthManager
from .fetch_interceptor import FetchInterceptor


class ClientMethods:
    """Direct P3P API methods exposed under `client.methods`.

    These methods call the P3P service directly and do not intercept server
    HTTP 402 responses. Use `client.get/post/request` for automatic 402 flows.
    """

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def create_token(self, options: CreateTokenOptions) -> Token:
        """Create a one-time payment token using the configured customer auth mode."""
        return self._api.create_token(options)


class PineLabsOnlineClientInstance:
    """Handle returned by :meth:`PineLabsOnlineClient.create`. Exposes:

    - `request`/`get`/`post`/... — fetch-like HTTP methods with 402 interception
    - `raw_request`/`raw_http` — the underlying httpx client (no interception)
    - `methods` — direct P3P API operations (create_token)
    - `create_credential(challenge)` — manually build a credential
    """

    def __init__(
        self,
        interceptor: FetchInterceptor,
        http_client: httpx.Client,
        methods: ClientMethods,
    ) -> None:
        self._interceptor = interceptor
        self._http = http_client
        self.methods = methods

    # ── Intercepting HTTP API ───────────────────────────────────

    def request(
        self,
        method: str,
        url: str,
        *,
        context: ClientRuntimeContext | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Send an HTTP request and automatically handle P3P 402 challenges."""
        return self._interceptor.request(method, url, context=context, **kwargs)

    def get(self, url: str, *, context: ClientRuntimeContext | None = None, **kwargs) -> httpx.Response:
        return self._interceptor.get(url, context=context, **kwargs)

    def post(self, url: str, *, context: ClientRuntimeContext | None = None, **kwargs) -> httpx.Response:
        return self._interceptor.post(url, context=context, **kwargs)

    def put(self, url: str, *, context: ClientRuntimeContext | None = None, **kwargs) -> httpx.Response:
        return self._interceptor.put(url, context=context, **kwargs)

    def delete(self, url: str, *, context: ClientRuntimeContext | None = None, **kwargs) -> httpx.Response:
        return self._interceptor.delete(url, context=context, **kwargs)

    def patch(self, url: str, *, context: ClientRuntimeContext | None = None, **kwargs) -> httpx.Response:
        return self._interceptor.patch(url, context=context, **kwargs)

    # Alias matching the Node SDK's `fetch` naming
    def fetch(
        self,
        url: str,
        method: str = "GET",
        *,
        context: ClientRuntimeContext | None = None,
        **kwargs,
    ) -> httpx.Response:
        """Fetch-style alias for `request`, matching the TypeScript SDK naming."""
        return self._interceptor.request(method, url, context=context, **kwargs)

    @property
    def raw_http(self) -> httpx.Client:
        return self._http

    def raw_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an HTTP request without automatic 402 payment handling."""
        return self._http.request(method, url, **kwargs)

    # ── Credential helpers ──────────────────────────────────────

    def create_credential(
        self,
        challenge: Challenge,
        context: ClientRuntimeContext | None = None,
    ) -> Credential:
        """Manually create a Payment credential for a decoded server challenge."""
        return self._interceptor.create_credential_for_challenge(challenge, context)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PineLabsOnlineClientInstance":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class PineLabsOnlineClient:
    """Factory for client SDK instances."""

    @staticmethod
    def create(config: PineLabsOnlineClientConfig) -> PineLabsOnlineClientInstance:
        """Create a client SDK instance from `PineLabsOnlineClientConfig`."""
        validate_config(config)

        request_timeout = (config.requestTimeoutMs / 1000.0) if config.requestTimeoutMs else None
        http_client = httpx.Client(timeout=request_timeout)

        auth = (
            AuthManager(
                config,
                resolve_p3p_base_url(config.env),
                http_client,
                config.requestTimeoutMs,
                config.logger,
                config.maxRetries,
                config.initialRetryDelayMs,
            )
            if resolve_customer_auth_mode(config) == P3PCustomerAuthMode.ClientCredentials
            else None
        )

        api_client = ApiClient(
            config,
            resolve_p3p_base_url(config.env),
            http_client,
            config.requestTimeoutMs,
            config.logger,
            config.maxRetries,
            config.initialRetryDelayMs,
            auth,
        )

        interceptor = FetchInterceptor(config, api_client, http_client)
        methods = ClientMethods(api_client)
        return PineLabsOnlineClientInstance(interceptor, http_client, methods)
