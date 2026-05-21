from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class ChallengeRequest:
    """Payment request embedded in a seller's 402 challenge."""

    scheme: str
    amount: str
    currency: str
    resource: str


@dataclass
class Challenge:
    """Decoded seller challenge from `WWW-Authenticate: Payment <payload>`."""

    id: str
    realm: str
    method: str
    intent: str
    request: ChallengeRequest
    expires: str


@dataclass
class CredentialPayload:
    """Buyer payment credential payload sent back to the seller."""

    type: Literal["token"]
    token: str
    customer_reference: Optional[str] = None


@dataclass
class Credential:
    """Payment credential sent as `Authorization: Payment <payload>`."""

    challenge: Challenge
    source: str
    payload: CredentialPayload


@dataclass
class Settlement:
    """Settlement amount encoded in a seller `Payment-Receipt` header."""

    amount: str
    currency: str


@dataclass
class Receipt:
    """Decoded `Payment-Receipt` data returned after a seller capture succeeds."""

    status: Literal["success", "failure"]
    method: str
    timestamp: str
    reference: str
    challengeId: str
    settlement: Settlement
