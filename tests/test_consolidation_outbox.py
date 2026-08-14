from __future__ import annotations

from datetime import datetime, timezone

from decisionvault.adaptive_memory import MemoryScopeLevel
from decisionvault.memory.outbox import ConsolidationOutbox, enqueue_consolidation


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executions = []
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.executions.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else (0,)


class Connection:
    def __init__(self, rows=()):
        self.cursor_value = Cursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.committed = False

    def close(self):
        self.closed = True


def test_enqueue_is_an_idempotent_scope_obligation_with_server_scope_level():
    cursor = Cursor()
    enqueue_consolidation(
        cursor,
        scope_id="global/payments",
        scope_level=MemoryScopeLevel.GLOBAL,
    )
    sql, params = cursor.executions[0]
    assert "INSERT INTO decision_memory_consolidation_outbox" in sql
    assert "ON CONFLICT (scope_id) DO UPDATE" in sql
    assert params == ("global/payments", "GLOBAL")


def test_outbox_claim_leases_due_work_and_preserves_attempt_count():
    conn = Connection(rows=[("team/payments", "TEAM", 2, 7)])
    outbox = ConsolidationOutbox(lambda: conn, lease_seconds=120)

    work = outbox.claim_scope("team/payments")

    assert work is not None
    assert work.scope_id == "team/payments"
    assert work.scope_level == MemoryScopeLevel.TEAM
    assert work.attempt_count == 2
    assert work.generation == 7
    assert any("status = 'RUNNING'" in sql for sql, _ in conn.cursor_value.executions)
    assert conn.committed is True


def test_outbox_failure_returns_to_pending_with_exponential_backoff():
    conn = Connection()
    outbox = ConsolidationOutbox(lambda: conn)
    now = datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc)

    backoff = outbox.mark_deferred(
        scope_id="team/payments",
        error_code="ProviderUnavailable",
        attempt_count=2,
        generation=4,
        now=now,
    )

    assert backoff == 8
    sql, params = conn.cursor_value.executions[0]
    assert "status = 'PENDING'" in sql
    assert params[0] == 3
    assert params[2] == "ProviderUnavailable"
    assert params[-2:] == ("team/payments", 4)


def test_complete_is_generation_bound_so_newer_enqueue_cannot_be_lost():
    conn = Connection()
    outbox = ConsolidationOutbox(lambda: conn)

    outbox.mark_complete("team/payments", generation=5)

    sql, params = conn.cursor_value.executions[0]
    assert "generation = %s" in sql
    assert "status = 'RUNNING'" in sql
    assert params == ("team/payments", 5)
