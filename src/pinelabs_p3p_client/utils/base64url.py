"""Base64url helpers matching the Node SDK behaviour (no padding on output)."""
from __future__ import annotations

import base64
import json
import re
from typing import Any, TypeVar, Union

T = TypeVar("T")

_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def encode(data: Union[str, bytes]) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode(encoded: str) -> str:
    return decode_bytes(encoded).decode("utf-8")


def decode_bytes(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def encode_json(obj: Any) -> str:
    return encode(json.dumps(obj, separators=(",", ":")))


def decode_json(encoded: str) -> Any:
    return json.loads(decode(encoded))


def is_base64_url(value: str) -> bool:
    return bool(_BASE64URL_RE.match(value))
