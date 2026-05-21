from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from jwt import PyJWKClient

from ..types.grantex import GrantTokenClaims, GrantVerificationResult, JwksConfig

DEFAULT_JWKS_CACHE_TTL_MS = 3_600_000  # 1 hour


class GrantVerifier:
    """Verifies Grantex RS256 JWT grant tokens via JWKS."""

    def __init__(self, jwks: JwksConfig, http_client: Optional[httpx.Client] = None) -> None:
        self._jwks_url = jwks.jwksUrl
        self._cache_ttl_ms = jwks.cacheTtlMs or DEFAULT_JWKS_CACHE_TTL_MS
        self._http = http_client  # reserved for future use (PyJWKClient handles fetch)
        self._jwk_client: Optional[PyJWKClient] = None
        self._cache_expires_at: float = 0
        self._lock = threading.Lock()

    def verify(self, grant_token: str, expected_agent_id: Optional[str] = None) -> GrantVerificationResult:
        """Verify signature, time claims, required claims, and optional agent id."""
        try:
            header = jwt.get_unverified_header(grant_token)
            if header.get("alg") != "RS256":
                return GrantVerificationResult(
                    valid=False,
                    error=f"Unsupported algorithm: {header.get('alg')}. Expected RS256",
                )

            signing_key = self._get_signing_key(header.get("kid"))
            if signing_key is None:
                return GrantVerificationResult(
                    valid=False,
                    error=f"No matching key found for kid: {header.get('kid') or 'none'}",
                )

            decoded = jwt.decode(
                grant_token,
                signing_key,
                algorithms=["RS256"],
                # Grantex JWTs have no audience / issuer fields we enforce here —
                # we validate claims manually below to mirror the Node SDK.
                options={
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_exp": False,
                    "verify_nbf": False,
                },
            )
        except jwt.InvalidSignatureError:
            return GrantVerificationResult(valid=False, error="Invalid signature")
        except jwt.DecodeError as exc:
            return GrantVerificationResult(
                valid=False, error=f"Grant verification failed: {exc}"
            )
        except Exception as exc:
            return GrantVerificationResult(
                valid=False, error=f"Grant verification failed: {exc}"
            )

        claims = _dict_to_claims(decoded)
        err = _validate_claims(claims, expected_agent_id)
        if err is not None:
            return GrantVerificationResult(valid=False, error=err)
        return GrantVerificationResult(valid=True, claims=claims)

    @staticmethod
    def decode_claims(grant_token: str) -> Optional[GrantTokenClaims]:
        """Decode claims without verifying signature (for logging/debugging)."""
        try:
            decoded = jwt.decode(
                grant_token,
                options={"verify_signature": False, "verify_exp": False, "verify_nbf": False},
            )
            return _dict_to_claims(decoded)
        except Exception:
            return None

    # ── Internal ────────────────────────────────────────────────

    def _get_signing_key(self, kid: Optional[str]):
        with self._lock:
            now = time.time() * 1000
            if self._jwk_client is None or now >= self._cache_expires_at:
                self._jwk_client = PyJWKClient(self._jwks_url, cache_keys=True)
                self._cache_expires_at = now + self._cache_ttl_ms

        if kid is None:
            # Fetch raw JWKS and return the single key if there's only one.
            try:
                jwk_set = self._jwk_client.get_jwk_set()
                if len(jwk_set.keys) == 1:
                    return jwk_set.keys[0].key
                return None
            except Exception:
                return None

        try:
            return self._jwk_client.get_signing_key(kid).key
        except Exception:
            return None


def _dict_to_claims(raw: Dict[str, Any]) -> GrantTokenClaims:
    return GrantTokenClaims(
        iss=raw.get("iss", ""),
        sub=raw.get("sub", ""),
        agt=raw.get("agt", ""),
        scp=list(raw.get("scp") or []),
        grnt=raw.get("grnt", ""),
        iat=int(raw.get("iat", 0)),
        exp=int(raw.get("exp", 0)),
        dev=raw.get("dev"),
        nbf=raw.get("nbf"),
        parentAgt=raw.get("parentAgt"),
        parentGrnt=raw.get("parentGrnt"),
        delegationDepth=raw.get("delegationDepth"),
        raw=raw,
    )


def _validate_claims(claims: GrantTokenClaims, expected_agent_id: Optional[str]) -> Optional[str]:
    now = int(time.time())
    if not claims.grnt:
        return "Missing grant ID (grnt)"
    if not claims.sub:
        return "Missing subject (sub)"
    if not claims.agt:
        return "Missing agent ID (agt)"
    if not claims.iss:
        return "Missing issuer (iss)"
    if not claims.scp or not isinstance(claims.scp, list):
        return "Missing or empty scopes (scp)"

    if claims.exp and claims.exp < now:
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims.exp))
        return f"Grant expired at {iso}"
    if claims.nbf and claims.nbf > now:
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims.nbf))
        return f"Grant not yet valid until {iso}"
    if expected_agent_id and claims.agt != expected_agent_id:
        return f"Agent ID mismatch: expected {expected_agent_id}, got {claims.agt}"
    return None
