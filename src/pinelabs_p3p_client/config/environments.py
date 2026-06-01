"""Pine Labs Online P3P environment base URLs."""
from __future__ import annotations


class P3PEnvironment:
    SANDBOX: str = "https://pluraluat.v2.pinepg.in"
    PRODUCTION: str = "https://api.pluralpay.in"


DEFAULT_BASE_URL: str = P3PEnvironment.PRODUCTION


def is_p3p_environment(value: object) -> bool:
    if value in (P3PEnvironment.SANDBOX, P3PEnvironment.PRODUCTION):
        return True
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def resolve_p3p_base_url(env: str | None = None) -> str:
    resolved = env or DEFAULT_BASE_URL
    if not is_p3p_environment(resolved):
        raise ValueError("env must be P3PEnvironment.SANDBOX, P3PEnvironment.PRODUCTION, or an HTTP URL")
    return resolved
