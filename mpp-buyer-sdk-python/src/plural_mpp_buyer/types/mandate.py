from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Amount:
    """Money amount expressed in the smallest unit for the currency.

    For INR this is paise, so Rs 78 is represented as `value=7800`.
    """

    value: int
    currency: str


@dataclass
class MandateChallenge:
    """UPI challenge details returned while a mandate/pre-authorization is pending."""

    type: str
    qr_url: str
    deep_link: str
    expires_at: str


@dataclass
class Mandate:
    """Normalized mandate/pre-authorization response returned by the MPP service."""

    mandate_id: str
    object: str
    order_id: str
    order_status: str
    payment_status: str
    customer_reference: str
    customer_id: str
    agent_id: str
    amount: Amount
    amount_blocked: int
    amount_debited: int
    amount_held: int
    amount_available: int
    mobile_number: str
    description: Optional[str]
    metadata: Optional[Dict[str, str]]
    expires_at: str
    created_at: str
    challenge: Optional[MandateChallenge] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateMandateOptions:
    """Input for `buyer.methods.create_mandate`.

    The SDK maps this to `POST /mpp/v1/pre-authorize`. `customerReference`
    is preferred; if absent the SDK falls back to `customerId` and then the
    normalized mobile number for local compatibility.
    """

    mobileNumber: str
    amount: Amount
    customerReference: Optional[str] = None
    customerId: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    expiry: Optional[str] = None
    idempotencyKey: Optional[str] = None
    paymentType: str = "SBMD"
    validityInDays: int = 7
