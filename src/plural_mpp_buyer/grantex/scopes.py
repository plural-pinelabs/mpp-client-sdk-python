from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from ..types.grantex import GrantTokenClaims, ParsedScope, SpendingLimit


class MppScopes:
    PAYMENT_INITIATE = "mpp:payment:initiate"
    MANDATE_READ = "mpp:mandate:read"
    MANDATE_CREATE = "mpp:mandate:create"
    TOKEN_READ = "mpp:token:read"
    TOKEN_CREATE = "mpp:token:create"
    TOKEN_REVOKE = "mpp:token:revoke"
    PAYMENT_ALL = "mpp:payment:*"
    MANDATE_ALL = "mpp:mandate:*"
    ALL = "mpp:*"


def parse_scope(scope: str) -> Optional[ParsedScope]:
    """Parse a Grantex scope such as `mpp:payment:initiate:max_500`."""
    parts = scope.split(":")
    if len(parts) < 3:
        return None
    resource = f"{parts[0]}:{parts[1]}"
    action = parts[2]
    constraint = ":".join(parts[3:]) if len(parts) > 3 else None
    return ParsedScope(resource=resource, action=action, constraint=constraint)


def has_scope(grant_scopes: List[str], required_scope: str) -> bool:
    """Return whether any grant scope satisfies a required scope."""
    required = parse_scope(required_scope)
    if required is None:
        return False
    required_namespace = required.resource.split(":")[0]

    for scope in grant_scopes:
        if scope == required_scope:
            return True
        if scope == f"{required_namespace}:*":
            return True
        parsed = parse_scope(scope)
        if parsed is None:
            continue
        if parsed.resource == required.resource and parsed.action == "*":
            return True
        if parsed.resource == required.resource and parsed.action == required.action:
            return True
    return False


def extract_spending_limit(scopes: List[str]) -> Optional[SpendingLimit]:
    """Extract cumulative spend limit from `mpp:payment:initiate:max_N`."""
    for scope in scopes:
        parsed = parse_scope(scope)
        if parsed is None or parsed.resource != "mpp:payment" or parsed.action != "initiate":
            continue
        if not parsed.constraint:
            continue
        m = re.match(r"^max_(\d+)$", parsed.constraint)
        if m:
            major = int(m.group(1))
            return SpendingLimit(maxAmountPaise=major * 100, currency="INR")
    return None


def extract_per_transaction_limit(scopes: List[str]) -> Optional[SpendingLimit]:
    """Extract per-transaction limit from `mpp:payment:initiate:per_tx_max_N`."""
    for scope in scopes:
        parsed = parse_scope(scope)
        if parsed is None or parsed.resource != "mpp:payment" or parsed.action != "initiate":
            continue
        if not parsed.constraint:
            continue
        m = re.match(r"^per_tx_max_(\d+)$", parsed.constraint)
        if m:
            major = int(m.group(1))
            return SpendingLimit(maxAmountPaise=major * 100, currency="INR")
    return None


@dataclass
class AuthorizationCheckResult:
    authorized: bool
    reason: Optional[str] = None
    spendingLimit: Optional[SpendingLimit] = None
    perTransactionLimit: Optional[SpendingLimit] = None


def check_payment_authorization(
    claims: GrantTokenClaims,
    amount_paise: int,
    total_spent_paise: int = 0,
) -> AuthorizationCheckResult:
    """Check whether verified grant claims authorize a payment amount."""
    if not has_scope(claims.scp, MppScopes.PAYMENT_INITIATE):
        return AuthorizationCheckResult(
            authorized=False,
            reason=f"Grant {claims.grnt} does not include payment:initiate scope",
        )

    per_tx = extract_per_transaction_limit(claims.scp)
    if per_tx and amount_paise > per_tx.maxAmountPaise:
        return AuthorizationCheckResult(
            authorized=False,
            reason=(
                f"Amount ₹{amount_paise / 100} exceeds per-transaction limit "
                f"₹{per_tx.maxAmountPaise / 100}"
            ),
            perTransactionLimit=per_tx,
        )

    spending = extract_spending_limit(claims.scp)
    if spending and (total_spent_paise + amount_paise) > spending.maxAmountPaise:
        return AuthorizationCheckResult(
            authorized=False,
            reason=(
                f"Cumulative spend ₹{(total_spent_paise + amount_paise) / 100} "
                f"exceeds grant limit ₹{spending.maxAmountPaise / 100}"
            ),
            spendingLimit=spending,
        )

    return AuthorizationCheckResult(
        authorized=True,
        spendingLimit=spending,
        perTransactionLimit=per_tx,
    )
