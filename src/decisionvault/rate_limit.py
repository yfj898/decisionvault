from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from decisionvault.memory.retry import retry_cockroach_serialization


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    count: int
    limit: int
    retry_after_seconds: int


def minute_bucket(now: datetime | None = None) -> tuple[int, int]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = int(current.timestamp())
    bucket = timestamp // 60
    retry_after = max(1, 60 - (timestamp % 60))
    return bucket, retry_after


class CockroachRateLimiter:
    def __init__(self, connection_factory: Callable[[], object]) -> None:
        self.connection_factory = connection_factory

    def check(
        self,
        *,
        principal_id: str,
        route_group: str,
        limit: int,
        now: datetime | None = None,
    ) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(True, 0, limit, 0)
        bucket, retry_after = minute_bucket(now)

        def operation() -> int:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM decision_rate_limits
                        WHERE principal_id = %s
                          AND route_group = %s
                          AND bucket_epoch < %s
                        """,
                        (principal_id, route_group, bucket - 2),
                    )
                    cur.execute(
                        """
                        INSERT INTO decision_rate_limits (
                            principal_id, route_group, bucket_epoch, request_count
                        ) VALUES (%s, %s, %s, 1)
                        ON CONFLICT (principal_id, route_group, bucket_epoch)
                        DO UPDATE SET
                            request_count = decision_rate_limits.request_count + 1
                        RETURNING request_count
                        """,
                        (principal_id, route_group, bucket),
                    )
                    count = int(cur.fetchone()[0])
                conn.commit()
                return count
            finally:
                conn.close()

        count = retry_cockroach_serialization(operation, max_attempts=5)
        return RateLimitDecision(
            allowed=count <= limit,
            count=count,
            limit=limit,
            retry_after_seconds=retry_after,
        )
