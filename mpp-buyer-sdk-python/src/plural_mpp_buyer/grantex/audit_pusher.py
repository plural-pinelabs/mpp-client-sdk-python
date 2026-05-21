from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Optional

import httpx

from ..types.grantex import GrantAuditEvent


def create_audit_pusher(
    audit_url: str,
    http_client: Optional[httpx.Client] = None,
) -> Callable[[GrantAuditEvent], None]:
    """Create an onAuditEvent callback that POSTs audit events to a Grantex server."""

    owned_client = http_client is None
    client = http_client or httpx.Client()

    def push(event: GrantAuditEvent) -> None:
        try:
            client.post(
                audit_url,
                json=asdict(event),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
        except Exception:
            # Audit push failure is non-fatal
            pass

    # NOTE: caller is responsible for closing `http_client` if they supplied one;
    # if we created ours, it will be reused for the lifetime of the pusher.
    _ = owned_client
    return push
