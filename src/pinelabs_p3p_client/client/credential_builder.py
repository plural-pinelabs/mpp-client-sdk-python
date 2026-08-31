from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..types.challenge import Challenge, ChallengeRequest, Credential, CredentialPayload, Receipt, Settlement
from ..types.payment import PaymentGateway, PaymentMethod
from ..utils.base64url import decode_json, encode_json, is_base64_url
from ..utils.errors import P3PChallengeError

PAYMENT_HEADER_PREFIX = "Payment "


def decode_challenge(www_authenticate_header: str) -> Challenge:
    """Decode and validate a server `WWW-Authenticate: Payment ...` challenge."""
    encoded = _extract_base64_payload(www_authenticate_header)
    if not encoded:
        raise P3PChallengeError("Invalid WWW-Authenticate header format", "")
    raw = decode_json(encoded)
    challenge = _dict_to_challenge(raw)
    validate_challenge(challenge)
    return challenge


def build_credential(
    challenge: Challenge,
    agent_id: str,
    token: str,
    payment_method: PaymentMethod,
    mobile_number: Optional[str] = None,
    payment_method_reference_id: Optional[str] = None,
) -> Credential:
    """Build the client credential object that authorizes one server debit attempt."""
    return Credential(
        challenge=challenge,
        source=agent_id,
        payload=CredentialPayload(
            type="token",
            token=token,
            payment_method_reference_id=str(payment_method_reference_id or "").strip() or None,
            mobile_number=str(mobile_number or "").strip() or None,
            payment_method=payment_method,
        ),
    )


def encode_credential_header(credential: Credential) -> str:
    """Encode a credential as a `Payment <base64url>` value for `P3P-Credential`."""
    credential_payload = {"type": credential.payload.type, "token": credential.payload.token}
    if credential.payload.payment_method_reference_id:
        credential_payload["payment_method_reference_id"] = credential.payload.payment_method_reference_id
    if credential.payload.mobile_number:
        credential_payload["mobile_number"] = credential.payload.mobile_number
    credential_payload["payment_method"] = _payment_method_value(credential.payload.payment_method)
    payload = {
        "challenge": {
            "id": credential.challenge.id,
            "realm": credential.challenge.realm,
            "intent": credential.challenge.intent,
            "request": _challenge_request_to_dict(credential.challenge.request),
            "expires": credential.challenge.expires,
        },
        "source": credential.source,
        "payload": credential_payload,
    }
    return f"{PAYMENT_HEADER_PREFIX}{encode_json(payload)}"


def decode_receipt(payment_receipt_header: str) -> Receipt:
    """Decode a server `Payment-Receipt` header into a typed receipt."""
    encoded = _extract_base64_payload(payment_receipt_header)
    if not encoded:
        raise ValueError("Invalid Payment-Receipt header format")
    raw = decode_json(encoded)
    settlement = raw.get("settlement") or {}
    payment_gateway = raw.get("paymentGateway", raw.get("payment_gateway"))
    payment_method = raw.get("paymentMethod", raw.get("payment_method"))
    return Receipt(
        status=raw.get("status", "failure"),
        timestamp=raw.get("timestamp", ""),
        reference=raw.get("reference", ""),
        challengeId=raw.get("challengeId", ""),
        settlement=Settlement(
            amount=settlement.get("amount", "0.00"),
            currency=settlement.get("currency", "INR"),
        ),
        paymentGateway=_parse_payment_gateway(payment_gateway) if payment_gateway is not None else None,
        paymentMethod=_parse_payment_method(payment_method) if payment_method is not None else None,
    )


def validate_challenge(challenge: Challenge) -> None:
    """Validate that a decoded challenge is usable and not expired."""
    if not challenge.id:
        raise P3PChallengeError("Challenge missing id", "")
    if not challenge.request or not challenge.request.amount or not challenge.request.currency:
        raise P3PChallengeError("Challenge missing payment request details", challenge.id)
    if not challenge.request.availablePaymentMethods:
        raise P3PChallengeError("Challenge missing available payment methods", challenge.id)
    try:
        expires_ms = _iso_to_epoch_ms(challenge.expires)
    except Exception as exc:
        raise P3PChallengeError("Challenge has expired", challenge.id) from exc
    if expires_ms <= time.time() * 1000:
        raise P3PChallengeError("Challenge has expired", challenge.id)


def extract_amount_paise(challenge: Challenge) -> int:
    """Return the challenge amount in paise for token creation."""
    try:
        major_units = float(challenge.request.amount)
    except (TypeError, ValueError) as exc:
        raise P3PChallengeError(
            f"Invalid challenge amount: {challenge.request.amount}", challenge.id
        ) from exc
    if major_units <= 0:
        raise P3PChallengeError(
            f"Invalid challenge amount: {challenge.request.amount}", challenge.id
        )
    return round(major_units * 100)


def select_payment_method(challenge: Challenge, selected_payment_method: PaymentMethod) -> PaymentMethod:
    """Return the client-selected method if it is accepted by the server challenge."""
    accepted = [_payment_method_value(method) for method in challenge.request.availablePaymentMethods]
    selected = _payment_method_value(selected_payment_method)
    if selected not in accepted:
        raise P3PChallengeError(
            f"Selected payment method {selected} is not accepted by this server challenge",
            challenge.id,
        )
    return selected_payment_method


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
        intent=raw.get("intent", ""),
        request=ChallengeRequest(
            scheme=req.get("scheme", ""),
            amount=str(req.get("amount", "")),
            currency=req.get("currency", ""),
            resource=req.get("resource", ""),
            availablePaymentMethods=_parse_payment_methods(
                req.get("availablePaymentMethods", req.get("available_payment_methods"))
            ),
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


def _parse_payment_gateway(value: Any) -> Optional[PaymentGateway]:
    if value is None:
        return None
    return PaymentGateway.PineLabsOnline if value == PaymentGateway.PineLabsOnline.value else value


def _parse_payment_method(value: Any) -> PaymentMethod:
    if value == PaymentMethod.RESERVE_PAY.value:
        return PaymentMethod.RESERVE_PAY
    if value == PaymentMethod.OTM.value:
        return PaymentMethod.OTM
    if value == PaymentMethod.CARD.value:
        return PaymentMethod.CARD
    if value == PaymentMethod.CREDIT_EMI.value:
        return PaymentMethod.CREDIT_EMI
    if value == PaymentMethod.Crypto.value:
        return PaymentMethod.Crypto
    return value or ""


def _parse_payment_methods(value: Any) -> List[PaymentMethod]:
    if not isinstance(value, list):
        return []
    return [_parse_payment_method(item) for item in value]


def _payment_method_value(value: Any) -> str:
    return value.value if isinstance(value, PaymentMethod) else str(value or "")


def _payment_method_values(values: Iterable[Any]) -> List[str]:
    return [_payment_method_value(value) for value in values]


def _challenge_request_to_dict(request: ChallengeRequest) -> Dict[str, Any]:
    data = asdict(request)
    data["availablePaymentMethods"] = _payment_method_values(request.availablePaymentMethods)
    return data
