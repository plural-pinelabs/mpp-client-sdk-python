from __future__ import annotations

import re

from ..types.config import PluralBuyerConfig
from ..types.mandate import CreateMandateOptions
from ..types.token import CreateTokenOptions

_E164_RE = re.compile(r"^\+\d{10,15}$")
_LOCAL_MOBILE_RE = re.compile(r"^\d{10}$")


def normalize_mandate_mobile_number(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) > 10:
        return digits[-10:]
    return digits


def validate_config(config: PluralBuyerConfig) -> None:
    if not config.clientId or not isinstance(config.clientId, str):
        raise ValueError("PluralBuyerConfig: clientId is required and must be a non-empty string")
    if not config.clientSecret or not isinstance(config.clientSecret, str):
        raise ValueError("PluralBuyerConfig: clientSecret is required and must be a non-empty string")
    if config.baseUrl is not None and not isinstance(config.baseUrl, str):
        raise ValueError("PluralBuyerConfig: baseUrl must be a string")
    if config.authBaseUrl is not None and not isinstance(config.authBaseUrl, str):
        raise ValueError("PluralBuyerConfig: authBaseUrl must be a string")
    if config.mppBaseUrl is not None and not isinstance(config.mppBaseUrl, str):
        raise ValueError("PluralBuyerConfig: mppBaseUrl must be a string")
    if config.accessToken is not None and not isinstance(config.accessToken, str):
        raise ValueError("PluralBuyerConfig: accessToken must be a string")
    if config.requestTimeoutMs is not None and (not isinstance(config.requestTimeoutMs, int) or config.requestTimeoutMs <= 0):
        raise ValueError("PluralBuyerConfig: requestTimeoutMs must be a positive integer")
    if config.maxRetries is not None and (not isinstance(config.maxRetries, int) or config.maxRetries < 0):
        raise ValueError("PluralBuyerConfig: maxRetries must be a non-negative integer")
    if config.initialRetryDelayMs is not None and (not isinstance(config.initialRetryDelayMs, int) or config.initialRetryDelayMs <= 0):
        raise ValueError("PluralBuyerConfig: initialRetryDelayMs must be a positive integer")


def validate_create_mandate_options(options: CreateMandateOptions) -> None:
    normalized_mobile = normalize_mandate_mobile_number(options.mobileNumber)
    if not options.mobileNumber or not (_E164_RE.match(options.mobileNumber) or _LOCAL_MOBILE_RE.match(normalized_mobile)):
        raise ValueError(
            "CreateMandateOptions: mobileNumber must be 10 digits or E.164 format (e.g., 9876543210 or +919876543210)"
        )
    if options.amount is None or not isinstance(options.amount.value, int) or options.amount.value < 100:
        raise ValueError("CreateMandateOptions: amount.value must be at least 100 paise (₹1)")
    if options.amount.currency != "INR":
        raise ValueError("CreateMandateOptions: only INR currency is supported")


def validate_create_token_options(options: CreateTokenOptions) -> None:
    if not (options.customerReference or options.customerId):
        raise ValueError("CreateTokenOptions: customerReference or customerId is required")
    if not options.paymentType:
        raise ValueError("CreateTokenOptions: paymentType is required")
