from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..types.grantex import GrantAuditEvent, GrantexConfig, GrantTokenClaims


class GrantAuditLogger:
    """Emits optional buyer-side audit callbacks for Grantex authorization events."""

    def __init__(self, config: GrantexConfig) -> None:
        self._callback = config.onAuditEvent

    def log(
        self,
        action: str,
        claims: GrantTokenClaims,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an audit event to the configured callback, ignoring callback failures."""
        if self._callback is None:
            return
        event = GrantAuditEvent(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            action=action,
            grantId=claims.grnt,
            agentId=claims.agt,
            userId=claims.sub,
            details=details or {},
        )
        try:
            result = self._callback(event)
            if inspect.isawaitable(result):
                # Run the coroutine to completion synchronously if possible.
                try:
                    asyncio.get_event_loop().run_until_complete(result)  # type: ignore[arg-type]
                except RuntimeError:
                    # Fallback: fire-and-forget in a new loop
                    asyncio.run(result)  # type: ignore[arg-type]
        except Exception:
            # Audit failures are non-fatal
            pass

    def log_grant_verified(self, claims: GrantTokenClaims) -> None:
        expires_iso = datetime.fromtimestamp(claims.exp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        self.log(
            "grant.verified",
            claims,
            {
                "scopes": claims.scp,
                "expiresAt": expires_iso,
                "delegationDepth": claims.delegationDepth or 0,
            },
        )

    def log_grant_denied(self, claims: GrantTokenClaims, reason: str) -> None:
        self.log("grant.denied", claims, {"reason": reason})

    def log_payment_authorized(self, claims: GrantTokenClaims, amount_paise: int, resource: str) -> None:
        self.log(
            "payment.authorized",
            claims,
            {
                "amountPaise": amount_paise,
                "amountDisplay": f"₹{amount_paise / 100}",
                "resource": resource,
            },
        )

    def log_payment_denied(
        self, claims: GrantTokenClaims, amount_paise: int, resource: str, reason: str
    ) -> None:
        self.log(
            "payment.denied",
            claims,
            {
                "amountPaise": amount_paise,
                "amountDisplay": f"₹{amount_paise / 100}",
                "resource": resource,
                "reason": reason,
            },
        )

    def log_spending_limit_checked(
        self, claims: GrantTokenClaims, amount_paise: int, total_spent: int, limit: int
    ) -> None:
        self.log(
            "spending_limit.checked",
            claims,
            {
                "amountPaise": amount_paise,
                "totalSpentPaise": total_spent,
                "limitPaise": limit,
                "remainingPaise": limit - total_spent,
            },
        )

    def log_spending_limit_exceeded(
        self, claims: GrantTokenClaims, amount_paise: int, total_spent: int, limit: int
    ) -> None:
        self.log(
            "spending_limit.exceeded",
            claims,
            {
                "amountPaise": amount_paise,
                "totalSpentPaise": total_spent,
                "limitPaise": limit,
                "overagesPaise": (total_spent + amount_paise) - limit,
            },
        )
