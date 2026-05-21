from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Optional

import httpx

from ..grantex.audit_logger import GrantAuditLogger
from ..grantex.grant_verifier import GrantVerifier
from ..grantex.scopes import check_payment_authorization
from ..types.challenge import Challenge, Credential, Receipt
from ..types.config import PluralBuyerConfig
from ..types.grantex import GrantTokenClaims
from ..types.token import CreateTokenOptions
from .api_client import ApiClient
from .credential_builder import (
    build_credential,
    decode_challenge,
    decode_receipt,
    encode_credential_header,
    extract_amount_paise,
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

        self._grant_verifier: Optional[GrantVerifier] = None
        self._audit_logger: Optional[GrantAuditLogger] = None
        if config.grantex is not None:
            self._grant_verifier = GrantVerifier(config.grantex.jwks, http_client)
            self._audit_logger = GrantAuditLogger(config.grantex)

        self._verified_claims: Optional[GrantTokenClaims] = None
        self._total_spent_paise: int = 0

    # ── Grantex ─────────────────────────────────────────────────

    def verify_grant(self) -> Optional[GrantTokenClaims]:
        """Verify the configured Grantex token and cache claims for later spend checks."""
        if self._config.grantex is None or self._grant_verifier is None:
            return None

        result = self._grant_verifier.verify(
            self._config.grantex.grantToken,
            self._config.grantex.agentId,
        )
        if not result.valid or result.claims is None:
            reason = result.error or "Unknown verification failure"
            if self._config.grantex.onGrantDenied is not None:
                from ..types.grantex import GrantDeniedContext
                ctx = GrantDeniedContext(
                    grantId="unknown",
                    agentId=self._config.grantex.agentId or "unknown",
                )
                _maybe_await(self._config.grantex.onGrantDenied(reason, ctx))
            raise RuntimeError(f"Grantex grant verification failed: {reason}")

        self._verified_claims = result.claims
        if self._audit_logger is not None:
            self._audit_logger.log_grant_verified(result.claims)
        return result.claims

    @property
    def grant_claims(self) -> Optional[GrantTokenClaims]:
        return self._verified_claims

    @property
    def grant_total_spent(self) -> int:
        return self._total_spent_paise

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

        # Grantex authorization pre-check
        if self._config.grantex is not None and self._verified_claims is not None:
            amount_paise = extract_amount_paise(challenge)
            resource = challenge.request.resource
            enforce = self._config.grantex.enforceSpendingLimits is not False

            auth_result = check_payment_authorization(
                self._verified_claims,
                amount_paise,
                self._total_spent_paise if enforce else 0,
            )

            if not auth_result.authorized:
                reason = auth_result.reason or "Payment not authorized by grant"
                if self._audit_logger is not None:
                    self._audit_logger.log_payment_denied(
                        self._verified_claims, amount_paise, resource, reason
                    )
                if self._config.grantex.onGrantDenied is not None:
                    from ..types.grantex import GrantDeniedContext
                    ctx = GrantDeniedContext(
                        grantId=self._verified_claims.grnt,
                        agentId=self._verified_claims.agt,
                        requestedAmount=amount_paise,
                        requestedResource=resource,
                        scopeViolation=reason,
                    )
                    _maybe_await(self._config.grantex.onGrantDenied(reason, ctx))
                raise RuntimeError(f"Grantex authorization denied: {reason}")

            if auth_result.spendingLimit is not None and self._audit_logger is not None:
                self._audit_logger.log_spending_limit_checked(
                    self._verified_claims,
                    amount_paise,
                    self._total_spent_paise,
                    auth_result.spendingLimit.maxAmountPaise,
                )
            if self._audit_logger is not None:
                self._audit_logger.log_payment_authorized(
                    self._verified_claims, amount_paise, resource
                )

        if self._config.onChallenge is not None:
            _maybe_await(self._config.onChallenge(challenge))

        credential = self.create_credential_for_challenge(challenge)
        credential_header = encode_credential_header(credential)

        retry_headers: Dict[str, str] = dict(headers or {})
        retry_headers["Authorization"] = credential_header
        if self._config.grantex is not None and self._config.grantex.grantToken:
            retry_headers["X-Grantex-Token"] = self._config.grantex.grantToken

        retry_response = self._http.request(method, url, headers=retry_headers, **kwargs)

        if retry_response.is_success:
            if self._verified_claims is not None:
                self._total_spent_paise += extract_amount_paise(challenge)

            if self._config.onPaymentComplete is not None:
                receipt_header = retry_response.headers.get("Payment-Receipt")
                if receipt_header:
                    try:
                        receipt = decode_receipt(receipt_header)
                        _maybe_await(self._config.onPaymentComplete(receipt))
                    except Exception:
                        pass  # receipt decode failure is non-fatal

        return retry_response
