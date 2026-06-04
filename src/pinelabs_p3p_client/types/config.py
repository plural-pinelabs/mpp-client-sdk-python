from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol

from ..config.environments import P3PEnvironment
from .challenge import Challenge, Receipt
from .payment import PaymentMethod


class P3PLogger(Protocol):
    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...


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

    selectedPaymentMethod: PaymentMethod
    env: Optional[str] = P3PEnvironment.PRODUCTION
    customerAuthMode: Optional[P3PCustomerAuthMode] = P3PCustomerAuthMode.ClientCredentials
    clientId: str = ""
    clientSecret: str = ""
    autoHandlePayment: bool = True
    onChallenge: Optional[Callable[[Challenge], Any]] = None
    onPaymentComplete: Optional[Callable[[Receipt], Any]] = None
    tokenDefaults: Optional[TokenDefaults] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[P3PLogger] = None


@dataclass
class ClientRuntimeContext:
    """Per-request customer context for automatic 402 payment handling."""

    customerKey: Optional[str] = None
    customerReference: Optional[str] = None
    mobileNumber: Optional[str] = None


# NOTE: ClientMethods / PineLabsOnlineClientInstance are structural interfaces — the
# Python SDK exposes these via the PineLabsOnlineClient class directly.
ClientMethods = object
PineLabsOnlineClientInstance = object

__all__ = [
    "ClientMethods",
    "ClientRuntimeContext",
    "P3PLogger",
    "P3PCustomerAuthMode",
    "PineLabsOnlineClientConfig",
    "PineLabsOnlineClientInstance",
    "PaymentMethod",
    "TokenDefaults",
]
