from __future__ import annotations

import re
from typing import Optional

from ..config.environments import resolve_p3p_base_url
from ..types.config import P3PCustomerAuthMode, PineLabsOnlineClientConfig
from ..types.payment import PaymentMethod
from ..types.token import CreateTokenOptions

_E164_RE = re.compile(r"^\+\d{10,15}$")
_LOCAL_MOBILE_RE = re.compile(r"^\d{10}$")


def normalize_mandate_mobile_number(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) > 10:
        raise ValueError(f"mobileNumber must be at most 10 digits, got {len(digits)}")
    return digits


def validate_config(config: PineLabsOnlineClientConfig) -> None:
    if not _required_text(config.clientId) or not _required_text(config.clientSecret):
        raise ValueError("PineLabsOnlineClientConfig: clientId and clientSecret are required")
    if not _required_text(config.merchantId):
        raise ValueError("PineLabsOnlineClientConfig: merchantId is required")
    if config.env is not None:
        resolve_p3p_base_url(config.env)
    if config.requestTimeoutMs is not None and (not isinstance(config.requestTimeoutMs, int) or config.requestTimeoutMs <= 0):
        raise ValueError("PineLabsOnlineClientConfig: requestTimeoutMs must be a positive integer")
    if config.maxRetries is not None and (not isinstance(config.maxRetries, int) or config.maxRetries < 0):
        raise ValueError("PineLabsOnlineClientConfig: maxRetries must be a non-negative integer")
    if config.initialRetryDelayMs is not None and (not isinstance(config.initialRetryDelayMs, int) or config.initialRetryDelayMs <= 0):
        raise ValueError("PineLabsOnlineClientConfig: initialRetryDelayMs must be a positive integer")


def validate_create_token_options(
    options: CreateTokenOptions,
    customer_auth_mode: P3PCustomerAuthMode = P3PCustomerAuthMode.ClientCredentials,
) -> None:
    mobile_number = _required_text(options.mobileNumber)
    if customer_auth_mode == P3PCustomerAuthMode.CustomerKey:
        if not _required_text(options.customerKey):
            raise ValueError("CreateTokenOptions: customerKey is required when customerAuthMode is CUSTOMER_KEY")
        if not mobile_number:
            raise ValueError("CreateTokenOptions: mobileNumber is required when customerAuthMode is CUSTOMER_KEY")
    elif customer_auth_mode == P3PCustomerAuthMode.ClientCredentials:
        if not mobile_number:
            raise ValueError("CreateTokenOptions: mobileNumber is required when customerAuthMode is CLIENT_CREDENTIALS")
    else:
        raise ValueError("CreateTokenOptions: customerAuthMode must be CUSTOMER_KEY or CLIENT_CREDENTIALS")
    if not str(options.challengeId or "").strip():
        raise ValueError("CreateTokenOptions: challengeId is required")
    payment_value = options.paymentAmount.value if options.paymentAmount is not None else (
        options.usageLimits.maxAmount if options.usageLimits is not None else None
    )
    payment_currency = options.paymentAmount.currency if options.paymentAmount is not None else (
        options.usageLimits.currency if options.usageLimits is not None else None
    )
    if not isinstance(payment_value, int) or payment_value <= 0:
        raise ValueError("CreateTokenOptions: paymentAmount.value must be a positive integer")
    if not payment_currency:
        raise ValueError("CreateTokenOptions: paymentAmount.currency is required")
    if options.paymentMethod is None:
        raise ValueError("CreateTokenOptions: paymentMethod is required")
    if not is_supported_payment_method(options.paymentMethod):
        raise _unsupported_payment_method_error("CreateTokenOptions: paymentMethod", options.paymentMethod)


def is_supported_payment_method(value: object) -> bool:
    return value in (PaymentMethod.RESERVE_PAY, PaymentMethod.OTM, PaymentMethod.CARD, PaymentMethod.CREDIT_EMI)


def _unsupported_payment_method_error(context: str, value: object) -> ValueError:
    if value == PaymentMethod.Crypto:
        return ValueError(f"{context}: PaymentMethod.Crypto is currently not supported in SDKs")
    return ValueError(f"{context}: payment method must be RESERVE_PAY, OTM, CARD, or CREDIT_EMI")


def resolve_customer_auth_mode(config: PineLabsOnlineClientConfig) -> P3PCustomerAuthMode:
    raw_mode = config.customerAuthMode or P3PCustomerAuthMode.ClientCredentials
    mode = raw_mode.value if hasattr(raw_mode, "value") else str(raw_mode)
    if mode == P3PCustomerAuthMode.CustomerKey.value:
        return P3PCustomerAuthMode.CustomerKey
    if mode == P3PCustomerAuthMode.ClientCredentials.value:
        return P3PCustomerAuthMode.ClientCredentials
    raise ValueError("PineLabsOnlineClientConfig: customerAuthMode must be CUSTOMER_KEY or CLIENT_CREDENTIALS")


def _required_text(value: object) -> Optional[str]:
    trimmed = str(value or "").strip()
    return trimmed or None
