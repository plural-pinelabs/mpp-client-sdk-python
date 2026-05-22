from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from .challenge import Challenge, Receipt


class MppLogger(Protocol):
    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...
    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None: ...


@dataclass
class TokenDefaults:
    """Optional defaults used when the buyer SDK creates payment tokens automatically."""

    maxCharges: Optional[int] = None
    ttlSeconds: Optional[int] = None


@dataclass
class PluralBuyerConfig:
    """Configuration required to construct a buyer SDK instance.

    `clientId` and `clientSecret` are used for service authentication.
    `customerReference` identifies the buyer/customer when creating one-time
    payment tokens after a seller returns a 402 challenge.
    """

    clientId: str
    clientSecret: str
    customerReference: Optional[str] = None
    baseUrl: Optional[str] = None
    authBaseUrl: Optional[str] = None
    mppBaseUrl: Optional[str] = None
    autoHandlePayment: bool = True
    onChallenge: Optional[Callable[[Challenge], Any]] = None
    onPaymentComplete: Optional[Callable[[Receipt], Any]] = None
    tokenDefaults: Optional[TokenDefaults] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[MppLogger] = None
    accessToken: Optional[str] = None


# NOTE: BuyerMethods / PluralBuyerInstance are structural interfaces — the
# Python SDK exposes these via the PluralBuyer class directly.
BuyerMethods = object
PluralBuyerInstance = object

__all__ = [
    "BuyerMethods",
    "MppLogger",
    "PluralBuyerConfig",
    "PluralBuyerInstance",
    "TokenDefaults",
]
