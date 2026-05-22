"""Plural MPP Buyer SDK — Python port of `@plural/mpp-buyer-sdk`.

Automatically intercepts HTTP 402 Payment Required responses, constructs
UPI SBMD credentials, and completes the payment flow.
"""
from .client import (
    PluralBuyer,
    PluralBuyerInstance,
    build_credential,
    decode_challenge,
    decode_receipt,
    encode_credential_header,
    extract_amount_paise,
    validate_challenge,
)
from .config.environments import DEFAULT_BASE_URL, MppEnvironment
from .types import (
    Amount,
    Challenge,
    ChallengeRequest,
    CreateMandateOptions,
    CreateTokenOptions,
    Credential,
    CredentialPayload,
    Mandate,
    MppErrorCode,
    PluralBuyerConfig,
    Receipt,
    Token,
    TokenDefaults,
)
from .utils.errors import MppChallengeError, MppError, MppNetworkError

__all__ = [
    "Amount",
    "Challenge",
    "ChallengeRequest",
    "CreateMandateOptions",
    "CreateTokenOptions",
    "Credential",
    "CredentialPayload",
    "DEFAULT_BASE_URL",
    "Mandate",
    "MppChallengeError",
    "MppEnvironment",
    "MppError",
    "MppErrorCode",
    "MppNetworkError",
    "MppScopes",
    "PluralBuyer",
    "PluralBuyerConfig",
    "PluralBuyerInstance",
    "Receipt",
    "Token",
    "TokenDefaults",
    "build_credential",
    "decode_challenge",
    "decode_receipt",
    "encode_credential_header",
    "extract_amount_paise",
    "validate_challenge",
]

__version__ = "0.1.0"
