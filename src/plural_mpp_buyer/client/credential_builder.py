from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..types.challenge import Challenge, ChallengeRequest, Credential, CredentialPayload, Receipt, Settlement
from ..utils.base64url import decode_json, encode_json, is_base64_url
from ..utils.errors import MppChallengeError

PAYMENT_HEADER_PREFIX = "Payment "


def decode_challenge(www_authenticate_header: str) -> Challenge:
    """Decode and validate a seller `WWW-Authenticate: Payment ...` challenge."""
    encoded = _extract_base64_payload(www_authenticate_header)
    if not encoded:
        raise MppChallengeError("Invalid WWW-Authenticate header format", "")
    raw = decode_json(encoded)
    challenge = _dict_to_challenge(raw)
    validate_challenge(challenge)
    return challenge


def build_credential(
    challenge: Challenge,
    agent_id: str,
    token: str,
    customer_reference: Optional[str] = None,
) -> Credential:
    """Build the buyer credential object that authorizes one seller debit attempt."""
    return Credential(
        challenge=challenge,
        source=agent_id,
        payload=CredentialPayload(
            type="token",
            token=token,
            customer_reference=str(customer_reference or "").strip() or None,
        ),
    )


def encode_credential_header(credential: Credential) -> str:
    """Encode a credential as an `Authorization: Payment <base64url>` header value."""
    credential_payload = {"type": credential.payload.type, "token": credential.payload.token}
    if credential.payload.customer_reference:
        credential_payload["customer_reference"] = credential.payload.customer_reference
    payload = {
        "challenge": {
            "id": credential.challenge.id,
            "realm": credential.challenge.realm,
            "method": credential.challenge.method,
            "intent": credential.challenge.intent,
            "request": asdict(credential.challenge.request),
            "expires": credential.challenge.expires,
        },
        "source": credential.source,
        "payload": credential_payload,
    }
    return f"{PAYMENT_HEADER_PREFIX}{encode_json(payload)}"


def decode_receipt(payment_receipt_header: str) -> Receipt:
    """Decode a seller `Payment-Receipt` header into a typed receipt."""
    encoded = _extract_base64_payload(payment_receipt_header)
    if not encoded:
        raise ValueError("Invalid Payment-Receipt header format")
    raw = decode_json(encoded)
    settlement = raw.get("settlement") or {}
    return Receipt(
        status=raw.get("status", "failure"),
        method=raw.get("method", ""),
        timestamp=raw.get("timestamp", ""),
        reference=raw.get("reference", ""),
        challengeId=raw.get("challengeId", ""),
        settlement=Settlement(
            amount=settlement.get("amount", "0.00"),
            currency=settlement.get("currency", "INR"),
        ),
    )


def validate_challenge(challenge: Challenge) -> None:
    """Validate that a decoded challenge is usable and not expired."""
    if not challenge.id:
        raise MppChallengeError("Challenge missing id", "")
    if challenge.method != "plural":
        raise MppChallengeError(
            f'Unsupported payment method: {challenge.method}. Expected "plural"',
            challenge.id,
        )
    if not challenge.request or not challenge.request.amount or not challenge.request.currency:
        raise MppChallengeError("Challenge missing payment request details", challenge.id)
    try:
        expires_ms = _iso_to_epoch_ms(challenge.expires)
    except Exception as exc:
        raise MppChallengeError("Challenge has expired", challenge.id) from exc
    if expires_ms <= time.time() * 1000:
        raise MppChallengeError("Challenge has expired", challenge.id)


def extract_amount_paise(challenge: Challenge) -> int:
    """Return the challenge amount in paise for token creation."""
    try:
        major_units = float(challenge.request.amount)
    except (TypeError, ValueError) as exc:
        raise MppChallengeError(
            f"Invalid challenge amount: {challenge.request.amount}", challenge.id
        ) from exc
    if major_units <= 0:
        raise MppChallengeError(
            f"Invalid challenge amount: {challenge.request.amount}", challenge.id
        )
    return round(major_units * 100)


# ── Helpers ────────────────────────────────────────────────────────

def _extract_base64_payload(header: str) -> Optional[str]:
    trimmed = header.strip()
    if trimmed.startswith(PAYMENT_HEADER_PREFIX):
        payload = trimmed[len(PAYMENT_HEADER_PREFIX):].strip()
        return payload if is_base64_url(payload) else None
    return trimmed if is_base64_url(trimmed) else None


def _dict_to_challenge(raw: Dict[str, Any]) -> Challenge:
    req = raw.get("request") or {}
    return Challenge(
        id=raw.get("id", ""),
        realm=raw.get("realm", ""),
        method=raw.get("method", ""),
        intent=raw.get("intent", ""),
        request=ChallengeRequest(
            scheme=req.get("scheme", ""),
            amount=str(req.get("amount", "")),
            currency=req.get("currency", ""),
            resource=req.get("resource", ""),
        ),
        expires=raw.get("expires", ""),
    )


def _iso_to_epoch_ms(iso: str) -> float:
    # Accept trailing Z
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000
