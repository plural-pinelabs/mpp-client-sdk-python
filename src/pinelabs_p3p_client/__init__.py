"""Pine Labs Online P3P Client SDK — Python port of `p3p-client-sdk`.

Automatically intercepts HTTP 402 Payment Required responses, constructs
P3P payment credentials, and completes the payment flow.
"""
from .client import (
    PineLabsOnlineClient,
    PineLabsOnlineClientInstance,
    build_credential,
    decode_challenge,
    decode_receipt,
    encode_credential_header,
    extract_amount_paise,
    select_payment_method,
    validate_challenge,
)
from .config.environments import DEFAULT_BASE_URL, P3PEnvironment
from .grantex import GrantTokenVerifier, has_grant_scope, missing_grant_scopes
from .types import (
    Amount,
    ClientGrantexConfig,
    ClientRuntimeContext,
    Challenge,
    ChallengeRequest,
    CreateTokenOptions,
    Credential,
    CredentialPayload,
    GRANTEX_TOKEN_HEADER,
    GrantexVerificationResult,
    GrantexVerifierLike,
    P3PCustomerAuthMode,
    P3PErrorCode,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineClientConfig,
    Receipt,
    Token,
    TokenDefaults,
)
from .utils.errors import P3PChallengeError, P3PError, P3PNetworkError

__all__ = [
    "Amount",
    "ClientGrantexConfig",
    "ClientRuntimeContext",
    "Challenge",
    "ChallengeRequest",
    "CreateTokenOptions",
    "Credential",
    "CredentialPayload",
    "DEFAULT_BASE_URL",
    "GRANTEX_TOKEN_HEADER",
    "GrantTokenVerifier",
    "GrantexVerificationResult",
    "GrantexVerifierLike",
    "P3PChallengeError",
    "P3PCustomerAuthMode",
    "P3PEnvironment",
    "P3PError",
    "P3PErrorCode",
    "P3PNetworkError",
    "PaymentGateway",
    "PaymentMethod",
    "PineLabsOnlineClient",
    "PineLabsOnlineClientConfig",
    "PineLabsOnlineClientInstance",
    "Receipt",
    "Token",
    "TokenDefaults",
    "build_credential",
    "decode_challenge",
    "decode_receipt",
    "encode_credential_header",
    "extract_amount_paise",
    "has_grant_scope",
    "missing_grant_scopes",
    "select_payment_method",
    "validate_challenge",
]

__version__ = "1.1.0"
