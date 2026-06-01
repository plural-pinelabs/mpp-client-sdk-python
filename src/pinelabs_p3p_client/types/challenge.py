from dataclasses import dataclass
from typing import List, Literal, Optional

from .payment import PaymentGateway, PaymentMethod


@dataclass
class ChallengeRequest:
    """Payment request embedded in a server's 402 challenge."""

    scheme: str
    amount: str
    currency: str
    resource: str
    availablePaymentMethods: List[PaymentMethod]


@dataclass
class Challenge:
    """Decoded server challenge from `WWW-Authenticate: Payment <payload>`."""

    id: str
    realm: str
    intent: str
    request: ChallengeRequest
    expires: str


@dataclass
class CredentialPayload:
    """Client payment credential payload sent back to the server."""

    type: Literal["token"]
    token: str
    payment_method: PaymentMethod
    customer_reference: Optional[str] = None
    mobile_number: Optional[str] = None


@dataclass
class Credential:
    """Payment credential sent as `P3P-Credential: Payment <payload>`."""

    challenge: Challenge
    source: str
    payload: CredentialPayload


@dataclass
class Settlement:
    """Settlement amount encoded in a server `Payment-Receipt` header."""

    amount: str
    currency: str


@dataclass
class Receipt:
    """Decoded `Payment-Receipt` data returned after a server capture succeeds."""

    status: Literal["success", "failure"]
    timestamp: str
    reference: str
    challengeId: str
    settlement: Settlement
    paymentGateway: Optional[PaymentGateway] = None
    paymentMethod: Optional[PaymentMethod] = None
