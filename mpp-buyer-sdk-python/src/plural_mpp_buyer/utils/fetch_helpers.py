"""HTTP helpers with timeout + retry/backoff support.

Mirrors the Node SDK's `fetchWithTimeout` — retries on 429/5xx, network
errors, and timeouts using exponential backoff with jitter. Honours
`Retry-After` headers.
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from ..types.config import MppLogger

DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_RETRY_DELAY_MS = 500


def _is_retriable_status(status: int) -> bool:
    return status == 429 or status >= 500


def _retry_delay_ms(attempt: int, initial: int, response: Optional[httpx.Response]) -> int:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                seconds = float(retry_after)
                if seconds > 0:
                    return int(seconds * 1000)
            except ValueError:
                pass
    base = initial * (2 ** attempt)
    jitter = base * 0.25 * (random.random() * 2 - 1)
    return max(0, int(round(base + jitter)))


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    content: Any = None,
    json: Any = None,
    timeout_ms: Optional[int] = None,
    logger: Optional[MppLogger] = None,
    max_retries: Optional[int] = None,
    initial_retry_delay_ms: Optional[int] = None,
) -> httpx.Response:
    effective_timeout = (timeout_ms or DEFAULT_TIMEOUT_MS) / 1000.0
    effective_max = DEFAULT_MAX_RETRIES if max_retries is None else max_retries
    effective_initial = initial_retry_delay_ms or DEFAULT_INITIAL_RETRY_DELAY_MS
    request_id = str(uuid.uuid4())

    req_headers: Dict[str, str] = dict(headers or {})
    req_headers.setdefault("X-Request-Id", request_id)

    last_error: Optional[BaseException] = None

    for attempt in range(effective_max + 1):
        is_retry = attempt > 0
        start = time.monotonic()

        if logger is not None:
            try:
                if is_retry:
                    logger.info(
                        f"↻ {method} {url} retry {attempt}/{effective_max}",
                        {"attempt": attempt, "requestId": request_id},
                    )
                else:
                    logger.debug(
                        f"→ {method} {url}",
                        {"timeoutMs": (timeout_ms or DEFAULT_TIMEOUT_MS), "requestId": request_id},
                    )
            except Exception:
                pass

        try:
            response = client.request(
                method,
                url,
                headers=req_headers,
                content=content,
                json=json,
                timeout=effective_timeout,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            if _is_retriable_status(response.status_code) and attempt < effective_max:
                delay = _retry_delay_ms(attempt, effective_initial, response)
                if logger is not None:
                    try:
                        logger.info(
                            f"← {method} {url} {response.status_code} (retriable, waiting {delay}ms)",
                            {"durationMs": duration_ms, "status": response.status_code, "retryInMs": delay},
                        )
                    except Exception:
                        pass
                time.sleep(delay / 1000.0)
                continue

            if logger is not None:
                try:
                    logger.info(
                        f"← {method} {url} {response.status_code}",
                        {"durationMs": duration_ms, "status": response.status_code, "requestId": request_id},
                    )
                except Exception:
                    pass
            return response

        except httpx.TimeoutException as exc:
            last_error = exc
            duration_ms = int((time.monotonic() - start) * 1000)
            if attempt < effective_max:
                delay = _retry_delay_ms(attempt, effective_initial, None)
                if logger is not None:
                    try:
                        logger.info(
                            f"✕ {method} {url} TIMEOUT (retriable, waiting {delay}ms)",
                            {"durationMs": duration_ms, "retryInMs": delay},
                        )
                    except Exception:
                        pass
                time.sleep(delay / 1000.0)
                continue
            if logger is not None:
                try:
                    logger.error(
                        f"✕ {method} {url} TIMEOUT",
                        {"durationMs": duration_ms, "timeoutMs": (timeout_ms or DEFAULT_TIMEOUT_MS)},
                    )
                except Exception:
                    pass
            raise TimeoutError(
                f"MPP request timed out after {timeout_ms or DEFAULT_TIMEOUT_MS}ms: {method} {url}"
            ) from exc

        except httpx.HTTPError as exc:
            last_error = exc
            duration_ms = int((time.monotonic() - start) * 1000)
            if attempt < effective_max:
                delay = _retry_delay_ms(attempt, effective_initial, None)
                if logger is not None:
                    try:
                        logger.info(
                            f"✕ {method} {url} NETWORK_ERROR (retriable, waiting {delay}ms)",
                            {"durationMs": duration_ms, "error": str(exc), "retryInMs": delay},
                        )
                    except Exception:
                        pass
                time.sleep(delay / 1000.0)
                continue
            if logger is not None:
                try:
                    logger.error(
                        f"✕ {method} {url} NETWORK_ERROR",
                        {"durationMs": duration_ms, "error": str(exc)},
                    )
                except Exception:
                    pass
            raise

    raise RuntimeError(
        f"MPP request failed after {effective_max} retries: {method} {url} — last error: {last_error}"
    )
