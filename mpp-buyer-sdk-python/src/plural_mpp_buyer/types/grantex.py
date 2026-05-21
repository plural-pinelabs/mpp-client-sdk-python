from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union


@dataclass
class GrantTokenClaims:
    """Verified Grantex JWT claims used for payment authorization decisions."""

    iss: str
    sub: str
    agt: str
    scp: List[str]
    grnt: str
    iat: int
    exp: int
    dev: Optional[str] = None
    nbf: Optional[int] = None
    parentAgt: Optional[str] = None
    parentGrnt: Optional[str] = None
    delegationDepth: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedScope:
    """Parsed representation of a colon-delimited Grantex scope."""

    resource: str
    action: str
    constraint: Optional[str] = None


@dataclass
class SpendingLimit:
    """Payment spend limit extracted from a Grantex scope constraint."""

    maxAmountPaise: int
    currency: str


@dataclass
class GrantVerificationResult:
    """Result of verifying a Grantex grant token."""

    valid: bool
    claims: Optional[GrantTokenClaims] = None
    error: Optional[str] = None


@dataclass
class JwksConfig:
    """JWKS endpoint configuration used to verify Grantex RS256 grant tokens."""

    jwksUrl: str
    cacheTtlMs: Optional[int] = None


@dataclass
class GrantDeniedContext:
    """Context passed to `onGrantDenied` callbacks."""

    grantId: str
    agentId: str
    requestedAmount: Optional[int] = None
    requestedResource: Optional[str] = None
    scopeViolation: Optional[str] = None


@dataclass
class GrantAuditEvent:
    """Audit event emitted by buyer-side Grantex hooks."""

    timestamp: str
    action: str
    grantId: str
    agentId: str
    userId: str
    details: Dict[str, Any]


# Callbacks can be sync or async; we accept either
GrantDeniedCallback = Callable[[str, GrantDeniedContext], Union[None, Awaitable[None]]]
GrantAuditCallback = Callable[[GrantAuditEvent], Union[None, Awaitable[None]]]


@dataclass
class GrantexConfig:
    """Buyer-side Grantex authorization settings.

    When configured, the SDK can verify the grant token locally, enforce MPP
    payment scopes/spend limits before creating a payment credential, and
    forward the grant token to the seller in `X-Grantex-Token`.
    """

    grantToken: str
    jwks: JwksConfig
    agentId: Optional[str] = None
    enforceSpendingLimits: bool = True
    onGrantDenied: Optional[GrantDeniedCallback] = None
    onAuditEvent: Optional[GrantAuditCallback] = None
