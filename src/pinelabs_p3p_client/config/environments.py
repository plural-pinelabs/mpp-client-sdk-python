"""Pine Labs Online P3P environment base URLs."""
from __future__ import annotations


class P3PEnvironment:
    SANDBOX: str = "https://pluraluat.v2.pinepg.in"
    PRODUCTION: str = "https://api.pluralpay.in"


P3PEnvironmentDefaults = {
    P3PEnvironment.SANDBOX: {
        "requestTimeoutMs": 60_000,
        "maxRetries": 3,
        "initialRetryDelayMs": 500,
    },
    P3PEnvironment.PRODUCTION: {
        "requestTimeoutMs": 45_000,
        "maxRetries": 3,
        "initialRetryDelayMs": 500,
    },
}


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


def with_p3p_environment_defaults(config):
    env = config.env or DEFAULT_BASE_URL
    defaults = P3PEnvironmentDefaults.get(env, P3PEnvironmentDefaults[P3PEnvironment.SANDBOX])
    config.env = env
    config.requestTimeoutMs = config.requestTimeoutMs or defaults["requestTimeoutMs"]
    config.maxRetries = defaults["maxRetries"] if config.maxRetries is None else config.maxRetries
    config.initialRetryDelayMs = config.initialRetryDelayMs or defaults["initialRetryDelayMs"]
    return config
