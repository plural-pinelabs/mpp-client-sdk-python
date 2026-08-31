from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

from ..config.environments import P3PEnvironment
from .challenge import Challenge, Receipt
from .payment import PaymentMethod

GRANTEX_TOKEN_HEADER = "X-Grantex-Token"


class P3PLogger(Protocol):
    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...


@dataclass
class GrantexVerificationResult:
    valid: bool
    grant: Optional[Any] = None
    error: Optional[str] = None


class GrantexVerifierLike(Protocol):
    def verify(self, token: str) -> GrantexVerificationResult: ...


@dataclass
class ClientGrantexConfig:
    """Optional delegated authorization token forwarding and verification."""

    grantToken: Optional[str] = None
    grant_token: Optional[str] = None
    baseUrl: Optional[str] = None
    jwksUri: Optional[str] = None
    jwksUrl: Optional[str] = None
    jwks_uri: Optional[str] = None
    jwks_url: Optional[str] = None
    requiredScopes: Optional[List[str]] = None
    required_scopes: Optional[List[str]] = None
    issuer: Optional[str] = None
    issuerDid: Optional[str] = None
    issuer_did: Optional[str] = None
    audience: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    clockTolerance: int = 0
    clock_tolerance: Optional[int] = None
    enforceGrant: bool = False
    enforce_grant: Optional[bool] = None
    verifier: Optional[GrantexVerifierLike] = None


class P3PCustomerAuthMode(str, Enum):
    """Customer authorization mode used when the client SDK creates P3P payment tokens."""

    CustomerKey = "CUSTOMER_KEY"
    ClientCredentials = "CLIENT_CREDENTIALS"


@dataclass
class TokenDefaults:
    """Optional defaults used when the client SDK creates payment tokens automatically."""

    maxCharges: Optional[int] = None
    ttlSeconds: Optional[int] = None


@dataclass
class PineLabsOnlineClientConfig:
    """Configuration required to construct a client SDK instance.

    Customer identity is supplied per request via `ClientRuntimeContext` so one
    client instance can serve multiple customers safely.
    """

    env: Optional[str] = P3PEnvironment.PRODUCTION
    customerAuthMode: Optional[P3PCustomerAuthMode] = P3PCustomerAuthMode.ClientCredentials
    clientId: str = ""
    clientSecret: str = ""
    merchantId: str = ""
    autoHandlePayment: bool = True
    onChallenge: Optional[Callable[[Challenge], Any]] = None
    onPaymentComplete: Optional[Callable[[Receipt], Any]] = None
    tokenDefaults: Optional[TokenDefaults] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[P3PLogger] = None
    grantex: Optional[ClientGrantexConfig] = None


@dataclass
class ClientRuntimeContext:
    """Per-request customer context for automatic 402 payment handling."""

    customerKey: Optional[str] = None
    customerReference: Optional[str] = None
    mobileNumber: Optional[str] = None
    paymentMethod: Optional[PaymentMethod] = None
    paymentMethodReferenceId: Optional[str] = None
    grantexToken: Optional[str] = None
    grantex_token: Optional[str] = None


# NOTE: ClientMethods / PineLabsOnlineClientInstance are structural interfaces — the
# Python SDK exposes these via the PineLabsOnlineClient class directly.
ClientMethods = object
PineLabsOnlineClientInstance = object

__all__ = [
    "ClientMethods",
    "ClientGrantexConfig",
    "ClientRuntimeContext",
    "GRANTEX_TOKEN_HEADER",
    "GrantexVerificationResult",
    "GrantexVerifierLike",
    "P3PLogger",
    "P3PCustomerAuthMode",
    "PineLabsOnlineClientConfig",
    "PineLabsOnlineClientInstance",
    "PaymentMethod",
    "TokenDefaults",
]
