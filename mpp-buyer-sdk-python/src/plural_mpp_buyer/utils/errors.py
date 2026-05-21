from __future__ import annotations

from typing import Any, Dict, Optional


class MppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.details = details

    @classmethod
    def from_response(cls, status: int, body: Dict[str, Any]) -> "MppError":
        err = body.get("error") or {}
        return cls(
            err.get("code", "MPP_INTERNAL_ERROR"),
            err.get("message", f"HTTP {status}"),
            status,
            err.get("additional_error_details"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "additional_error_details": self.details,
            }
        }


class MppNetworkError(Exception):
    def __init__(self, message: str, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause


class MppChallengeError(Exception):
    def __init__(self, message: str, challenge_id: str) -> None:
        super().__init__(message)
        self.challenge_id = challenge_id
