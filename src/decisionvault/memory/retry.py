from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def retry_cockroach_serialization(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.02,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Retry an entire CockroachDB transaction on SQLSTATE 40001 only."""

    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return operation()
        except Exception as exc:
            retryable = getattr(exc, "sqlstate", None) == "40001"
            if not retryable or attempt + 1 >= max_attempts:
                raise
            sleep(base_delay_seconds * (2**attempt))
    raise AssertionError("unreachable")
