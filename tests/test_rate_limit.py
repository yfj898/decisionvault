from __future__ import annotations

from datetime import datetime, timezone

from decisionvault.rate_limit import CockroachRateLimiter, minute_bucket


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        if "INSERT INTO decision_rate_limits" in sql:
            self.connection.count += 1
            self.result = (self.connection.count,)

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self):
        self.count = 0
        self.commits = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closes += 1


def test_minute_bucket_returns_retry_until_next_minute():
    bucket, retry_after = minute_bucket(
        datetime(2026, 8, 14, 3, 45, 42, tzinfo=timezone.utc)
    )
    assert bucket > 0
    assert retry_after == 18


def test_cockroach_rate_limiter_allows_then_rejects():
    connection = FakeConnection()
    limiter = CockroachRateLimiter(lambda: connection)
    now = datetime(2026, 8, 14, 3, 45, 42, tzinfo=timezone.utc)

    first = limiter.check(
        principal_id="agent-a",
        route_group="agent-api",
        limit=2,
        now=now,
    )
    second = limiter.check(
        principal_id="agent-a",
        route_group="agent-api",
        limit=2,
        now=now,
    )
    third = limiter.check(
        principal_id="agent-a",
        route_group="agent-api",
        limit=2,
        now=now,
    )

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.count == 3
    assert third.retry_after_seconds == 18
    assert connection.commits == 3
