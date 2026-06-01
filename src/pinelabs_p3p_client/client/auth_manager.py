from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Optional

import httpx

from ..types.config import P3PLogger, PineLabsOnlineClientConfig
from ..utils.errors import P3PError
from ..utils.fetch_helpers import request_with_retry

REFRESH_SKEW_MS = 5 * 60_000


@dataclass
class _AuthState:
    access_token: str
    expires_at: float


class AuthManager:
    """Client-credentials token cache for client SDK central token calls."""

    def __init__(
        self,
        config: PineLabsOnlineClientConfig,
        base_url: str,
        http_client: httpx.Client,
        timeout_ms: Optional[int] = None,
        logger: Optional[P3PLogger] = None,
        max_retries: Optional[int] = None,
        initial_retry_delay_ms: Optional[int] = None,
    ) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._http = http_client
        self._timeout_ms = timeout_ms
        self._logger = logger
        self._max_retries = max_retries
        self._initial_retry_delay_ms = initial_retry_delay_ms
        self._state: Optional[_AuthState] = None
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        with self._lock:
            if self._state and time.time() * 1000 < self._refresh_at_ms():
                return self._state.access_token
            return self._exchange_token()

    def _exchange_token(self) -> str:
        response = request_with_retry(
            self._http,
            "POST",
            f"{self._base_url}/api/auth/v1/token",
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "client_id": self._config.clientId,
                "client_secret": self._config.clientSecret,
            },
            timeout_ms=self._timeout_ms,
            logger=self._logger,
            max_retries=self._max_retries,
            initial_retry_delay_ms=self._initial_retry_delay_ms,
        )

        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {
                    "error": {
                        "code": "P3P_AUTHENTICATION_FAILED",
                        "message": "Client token exchange failed",
                    }
                }
            raise P3PError.from_response(response.status_code, body)

        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        access_token = str(data.get("access_token") or "")
        if not access_token:
            raise P3PError(
                "P3P_AUTHENTICATION_FAILED",
                "Token exchange response missing access_token",
                response.status_code,
            )

        expires_at_ms = _parse_expires_at(data.get("expires_at"))
        if expires_at_ms is None:
            expires_at_ms = time.time() * 1000 + int(data.get("expires_in") or 3600) * 1000

        self._state = _AuthState(access_token=access_token, expires_at=expires_at_ms)
        return access_token

    def _refresh_at_ms(self) -> float:
        if self._state is None:
            return 0
        ttl_ms = self._state.expires_at - time.time() * 1000
        skew_ms = min(REFRESH_SKEW_MS, max(0, ttl_ms / 2))
        return self._state.expires_at - skew_ms


def _parse_expires_at(value: object) -> Optional[float]:
    if not value:
        return None
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .timestamp()
            * 1000
        )
    except Exception:
        return None
