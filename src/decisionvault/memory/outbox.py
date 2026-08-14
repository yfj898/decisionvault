from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from decisionvault.adaptive_memory import MemoryScopeLevel
from decisionvault.memory.retry import retry_cockroach_serialization


@dataclass(frozen=True, slots=True)
class ConsolidationWorkItem:
    scope_id: str
    scope_level: MemoryScopeLevel
    attempt_count: int
    generation: int


def enqueue_consolidation(
    cursor: object,
    *,
    scope_id: str,
    scope_level: MemoryScopeLevel,
) -> None:
    """Durably record an L1→L2/L3 consolidation obligation in the L1 transaction."""

    cursor.execute(
        """
        INSERT INTO decision_memory_consolidation_outbox (
            scope_id, scope_level, status, attempt_count, generation,
            next_attempt_at, lease_until, last_error_code,
            requested_at, updated_at
        ) VALUES (%s, %s, 'PENDING', 0, 1, now(), NULL, NULL, now(), now())
        ON CONFLICT (scope_id) DO UPDATE SET
            scope_level = excluded.scope_level,
            status = 'PENDING',
            generation = decision_memory_consolidation_outbox.generation + 1,
            next_attempt_at = LEAST(
                decision_memory_consolidation_outbox.next_attempt_at,
                excluded.next_attempt_at
            ),
            lease_until = NULL,
            last_error_code = NULL,
            updated_at = now()
        """,
        (scope_id, scope_level.value),
    )


@dataclass(slots=True)
class ConsolidationOutbox:
    connection_factory: Callable[[], object]
    lease_seconds: int = 120

    def _claim_rows(
        self,
        *,
        scope_id: str | None,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[ConsolidationWorkItem, ...]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        lease_until = current + timedelta(seconds=max(1, self.lease_seconds))

        def operation() -> tuple[ConsolidationWorkItem, ...]:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    if scope_id is None:
                        cur.execute(
                            """
                            SELECT scope_id, scope_level, attempt_count, generation
                            FROM decision_memory_consolidation_outbox
                            WHERE next_attempt_at <= %s
                              AND (
                                status = 'PENDING'
                                OR (status = 'RUNNING' AND lease_until <= %s)
                              )
                            ORDER BY next_attempt_at, requested_at
                            LIMIT %s
                            FOR UPDATE
                            """,
                            (current, current, max(1, limit)),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT scope_id, scope_level, attempt_count, generation
                            FROM decision_memory_consolidation_outbox
                            WHERE scope_id = %s
                              AND next_attempt_at <= %s
                              AND (
                                status = 'PENDING'
                                OR (status = 'RUNNING' AND lease_until <= %s)
                              )
                            FOR UPDATE
                            """,
                            (scope_id, current, current),
                        )
                    rows = cur.fetchall()
                    claimed: list[ConsolidationWorkItem] = []
                    for row in rows:
                        cur.execute(
                            """
                            UPDATE decision_memory_consolidation_outbox
                            SET status = 'RUNNING', lease_until = %s, updated_at = %s
                            WHERE scope_id = %s
                            """,
                            (lease_until, current, str(row[0])),
                        )
                        claimed.append(
                            ConsolidationWorkItem(
                                scope_id=str(row[0]),
                                scope_level=MemoryScopeLevel(str(row[1])),
                                attempt_count=int(row[2]),
                                generation=int(row[3]),
                            )
                        )
                conn.commit()
                return tuple(claimed)
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        return retry_cockroach_serialization(operation)

    def claim_scope(self, scope_id: str) -> ConsolidationWorkItem | None:
        rows = self._claim_rows(scope_id=scope_id, limit=1)
        return rows[0] if rows else None

    def claim_due(self, *, limit: int) -> tuple[ConsolidationWorkItem, ...]:
        return self._claim_rows(scope_id=None, limit=limit)

    def mark_complete(self, scope_id: str, *, generation: int) -> None:
        def operation() -> None:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM decision_memory_consolidation_outbox
                        WHERE scope_id = %s
                          AND generation = %s
                          AND status = 'RUNNING'
                        """,
                        (scope_id, generation),
                    )
                conn.commit()
            finally:
                conn.close()

        retry_cockroach_serialization(operation)

    def mark_deferred(
        self,
        *,
        scope_id: str,
        error_code: str,
        attempt_count: int,
        generation: int,
        now: datetime | None = None,
    ) -> int:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        new_attempt_count = max(0, attempt_count) + 1
        backoff_seconds = min(3600, 2 ** min(new_attempt_count, 10))
        next_attempt_at = current + timedelta(seconds=backoff_seconds)

        def operation() -> None:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE decision_memory_consolidation_outbox
                        SET status = 'PENDING',
                            attempt_count = %s,
                            next_attempt_at = %s,
                            lease_until = NULL,
                            last_error_code = %s,
                            updated_at = %s
                        WHERE scope_id = %s
                          AND generation = %s
                          AND status = 'RUNNING'
                        """,
                        (
                            new_attempt_count,
                            next_attempt_at,
                            error_code[:128],
                            current,
                            scope_id,
                            generation,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

        retry_cockroach_serialization(operation)
        return backoff_seconds

    def backlog_count(self) -> int:
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM decision_memory_consolidation_outbox")
                return int(cur.fetchone()[0])
        finally:
            conn.close()
