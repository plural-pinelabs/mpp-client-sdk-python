from __future__ import annotations

from typing import Iterable, Optional

from grantex import VerifyGrantTokenOptions, verify_grant_token

from .types.config import ClientGrantexConfig, GrantexVerificationResult


DEFAULT_GRANTEX_JWKS_URI = "https://api.grantex.dev/.well-known/jwks.json"
_GRANTEX_JWKS_PATH = "/.well-known/jwks.json"
_DEFAULT_GRANTEX_BASE_URL = "https://api.grantex.dev"


class GrantTokenVerifier:
    """Verify Grantex grant tokens using the published `grantex` package."""

    def __init__(self, config: ClientGrantexConfig) -> None:
        self._config = config

    def verify(self, token: str) -> GrantexVerificationResult:
        trimmed = (token or "").strip()
        if not trimmed:
            return GrantexVerificationResult(valid=False, error="Missing grant token")

        if self._config.verifier is not None:
            return _post_validate(self._config.verifier.verify(trimmed), self._config)

        jwks_uri = _jwks_uri(self._config) or DEFAULT_GRANTEX_JWKS_URI

        if not _is_https_url(jwks_uri):
            return GrantexVerificationResult(
                valid=False,
                error="ClientGrantexConfig: jwksUri must use HTTPS",
            )

        try:
            grant = verify_grant_token(
                trimmed,
                VerifyGrantTokenOptions(
                    jwks_uri=jwks_uri,
                    issuer=self._config.issuer,
                    issuer_did=self._config.issuerDid or self._config.issuer_did,
                    audience=self._config.audience,
                    clock_tolerance=self._config.clock_tolerance
                    if self._config.clock_tolerance is not None
                    else self._config.clockTolerance,
                ),
            )
            return _post_validate(GrantexVerificationResult(valid=True, grant=grant), self._config)
        except Exception as exc:
            return GrantexVerificationResult(valid=False, error=str(exc))


def has_grant_scope(scopes: Iterable[str], required_scope: str) -> bool:
    return any(_scope_covers(scope, required_scope) for scope in scopes)


def missing_grant_scopes(scopes: Iterable[str], required_scopes: Optional[Iterable[str]] = None) -> list[str]:
    return [scope for scope in (required_scopes or []) if not has_grant_scope(scopes, scope)]


def _post_validate(result: GrantexVerificationResult, config: ClientGrantexConfig) -> GrantexVerificationResult:
    if not result.valid or result.grant is None:
        return result

    expected_agent = config.agentId or config.agent_id
    agent_did = getattr(result.grant, "agent_did", None) or getattr(result.grant, "agentDid", None)
    if expected_agent and agent_did != expected_agent:
        return GrantexVerificationResult(
            valid=False,
            grant=result.grant,
            error=f'Grant agent mismatch. Expected "{expected_agent}", got "{agent_did}"',
        )

    grant_scopes = list(getattr(result.grant, "scopes", []) or [])
    required_scopes = config.requiredScopes if config.requiredScopes is not None else config.required_scopes
    missing = missing_grant_scopes(grant_scopes, required_scopes)
    if missing:
        return GrantexVerificationResult(
            valid=False,
            grant=result.grant,
            error=f"Grant token is missing required scopes: {', '.join(missing)}",
        )
    return result


def _jwks_uri(config: ClientGrantexConfig) -> Optional[str]:
    if (config.jwksUri or "").strip():
        return config.jwksUri.strip()
    if (config.jwksUrl or "").strip():
        return config.jwksUrl.strip()
    if (config.jwks_uri or "").strip():
        return config.jwks_uri.strip()
    if (config.jwks_url or "").strip():
        return config.jwks_url.strip()
    base = (config.baseUrl or "").strip().rstrip("/")
    if base:
        return base + _GRANTEX_JWKS_PATH
    return None


def _is_https_url(url: str) -> bool:
    return url.startswith("https://") or _is_localhost_url_grantex(url)


def _is_localhost_url_grantex(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        return (
            hostname in ("localhost", "127.0.0.1", "::1", "host.docker.internal")
            or "." not in hostname
        )
    except Exception:
        return False


def _scope_covers(granted_scope: str, required_scope: str) -> bool:
    if granted_scope == required_scope:
        return True
    if granted_scope.endswith(":*"):
        return required_scope.startswith(granted_scope[:-1])
    return False
