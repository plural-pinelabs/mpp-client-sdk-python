from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class UsageLimits:
    """Token usage limits returned by older token APIs, preserved for compatibility."""

    max_amount: int
    currency: str
    expires_at: str
    max_charges: Optional[int] = None


@dataclass
class TokenUsage:
    """Usage counters returned with a payment token response when available."""

    amount_used: int
    charges_made: int


@dataclass
class TokenHold:
    """Hold information returned with a payment token response when available."""

    amount: int
    status: str  # active | released | claimed
    expires_at: str


@dataclass
class Token:
    """Normalized one-time MPP payment token response.

    The current MPP service contract returns `payment_token`, `expires_in`,
    `type`, and `authorization_id`; additional fields remain optional
    compatibility slots for older responses.
    """

    token_id: str
    object: str
    customer_reference: str
    customer_id: str
    mandate_id: str
    token: str
    challenge_id: Optional[str]
    hold: TokenHold
    usage_limits: UsageLimits
    usage: TokenUsage
    metadata: Optional[Dict[str, str]]
    created_at: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateTokenUsageLimits:
    """Legacy token-limit shape kept for backwards-compatible constructors."""

    maxAmount: int
    currency: str
    expiresAt: str
    maxCharges: Optional[int] = None


@dataclass
class CreateTokenOptions:
    """Input for `buyer.methods.create_token`.

    The current MPP contract requires only `type` and `customer_reference`.
    `mandateId` is intentionally not part of this object.
    """

    usageLimits: Optional[CreateTokenUsageLimits] = None
    customerReference: Optional[str] = None
    customerId: Optional[str] = None
    challengeId: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    paymentType: str = "SBMD"
