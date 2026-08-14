from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
import json
from uuid import uuid4

from decisionvault.adaptive_memory import (
    ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
    Applicability,
    GovernedMemory,
    MemoryClass,
    MemoryPolarity,
    MemoryScopeLevel,
    MemoryStatus,
    MemoryType,
)
from decisionvault.domain import (
    DecisionEpisode,
    Outcome,
    RecalledEpisode,
    Strategy,
)
from decisionvault.memory.retry import retry_cockroach_serialization
from decisionvault.memory.outbox import enqueue_consolidation
from decisionvault.memory.governed_query import (
    adaptive_semantic_ann_sql,
    adaptive_semantic_coverage_sql,
    semantic_ann_sql,
    semantic_coverage_sql,
)


Vector = Sequence[float]


class SupersessionWriteConflict(RuntimeError):
    """A correction no longer targets the producer's current governed head."""


class MemoryRevocationConflict(RuntimeError):
    """A revocation target is missing or no longer the producer's current head."""


@dataclass(frozen=True, slots=True)
class MemoryRevocationResult:
    revocation_id: str
    episode_id: str
    producer_agent_id: str
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class ProducerRetirementResult:
    retired_heads: int
    producer_agent_ids: tuple[str, ...]
    scope_ids: tuple[str, ...] = ()


def _vector_literal(vector: Vector) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    if isinstance(parsed, (tuple, list, set, frozenset)):
        return tuple(str(item) for item in parsed)
    return (str(parsed),)


def _adaptive_memory_from_row(row: tuple[object, ...]) -> GovernedMemory:
    distance = max(0.0, min(1.0, float(row[28])))
    return GovernedMemory(
        memory_id=str(row[0]),
        candidate_id=str(row[1]),
        scope_id=str(row[2]),
        scope_level=MemoryScopeLevel(str(row[3])),
        memory_type=MemoryType(str(row[4])),
        polarity=MemoryPolarity(str(row[5])),
        situation_class=str(row[6]),
        applicability=Applicability(
            preconditions=frozenset(_string_tuple(row[7])),
            exclusions=frozenset(_string_tuple(row[8])),
        ),
        intervention=Strategy(str(row[9])),
        expected_outcome=Outcome(str(row[10])),
        supporting_episode_ids=_string_tuple(row[11]),
        producer_set=_string_tuple(row[12]),
        positive_episode_ids=_string_tuple(row[13]),
        negative_episode_ids=_string_tuple(row[14]),
        confidence=float(row[15]),
        observed_from=row[16],
        observed_to=row[17],
        created_at=row[18],
        recorded_at=row[19],
        governance_revision=str(row[20]),
        semantic_embedding_space=str(row[21]),
        memory_class=MemoryClass(str(row[22])),
        expires_at=row[23],
        status=MemoryStatus(str(row[24])),
        supersedes_memory_id=str(row[25]) if row[25] is not None else None,
        revoked_at=row[26],
        revocation_reason=str(row[27]) if row[27] is not None else None,
        similarity=1.0 - distance,
    )


@dataclass(slots=True)
class CockroachVectorMemoryStore:
    """CockroachDB implementation seam.

    `connection_factory` returns a DB-API compatible connection.
    `embedder` returns the fixed-width vector expected by the schema.

    The driver is deliberately injected so the deterministic local suite does
    not require cloud dependencies.
    """

    connection_factory: Callable[[], object]
    embedder: Callable[[str], Vector]
    query_embedder: Callable[[str], Vector] | None = None
    semantic_embedder: Callable[[str], Vector] | None = None
    semantic_query_embedder: Callable[[str], Vector] | None = None
    semantic_embedding_space: str | None = None
    scope_level_resolver: Callable[[str], MemoryScopeLevel] | None = None

    def __post_init__(self) -> None:
        semantic_enabled = (
            self.semantic_embedder is not None
            or self.semantic_query_embedder is not None
        )
        if semantic_enabled and not (self.semantic_embedding_space or "").strip():
            raise ValueError(
                "semantic_embedding_space is required for semantic persistence/retrieval"
            )

    def _scope_level(self, scope_id: str) -> MemoryScopeLevel:
        if self.scope_level_resolver is None:
            return MemoryScopeLevel.TEAM
        return self.scope_level_resolver(scope_id)

    def save(self, episode: DecisionEpisode) -> None:
        vector = _vector_literal(self.embedder(episode.situation))
        execution_receipt_id = str(
            episode.evidence.get("execution_receipt_id", "")
        ).strip() or None
        supersedes_episode_id = str(
            episode.evidence.get("supersedes_episode_id", "")
        ).strip() or None
        semantic_vector = (
            _vector_literal(self.semantic_embedder(episode.situation))
            if self.semantic_embedder is not None
            else None
        )
        semantic_space = (self.semantic_embedding_space or "").strip() or None
        if semantic_vector is None:
            sql = """
                INSERT INTO decision_episodes (
                    episode_id, scope_id, situation, strategy, outcome,
                    effectiveness, confidence, evidence, execution_receipt_id,
                    supersedes_episode_id, embedding, observed_at, recorded_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::UUID, %s::VECTOR, %s, %s
                )
            """
            params = (
                episode.episode_id,
                episode.scope_id,
                episode.situation,
                episode.strategy.value,
                episode.outcome.value,
                episode.effectiveness,
                episode.confidence,
                json.dumps(dict(episode.evidence)),
                execution_receipt_id,
                supersedes_episode_id,
                vector,
                episode.observed_at,
                episode.recorded_at,
            )
        else:
            sql = """
                INSERT INTO decision_episodes (
                    episode_id, scope_id, situation, strategy, outcome,
                    effectiveness, confidence, evidence, execution_receipt_id,
                    supersedes_episode_id, embedding,
                    semantic_embedding, semantic_embedding_space,
                    observed_at, recorded_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::UUID, %s::VECTOR,
                    %s::VECTOR, %s, %s, %s
                )
            """
            params = (
                episode.episode_id,
                episode.scope_id,
                episode.situation,
                episode.strategy.value,
                episode.outcome.value,
                episode.effectiveness,
                episode.confidence,
                json.dumps(dict(episode.evidence)),
                execution_receipt_id,
                supersedes_episode_id,
                vector,
                semantic_vector,
                semantic_space,
                episode.observed_at,
                episode.recorded_at,
            )
        def write_transaction() -> None:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    producer_agent_id = str(
                        episode.evidence.get("producer_agent_id", "")
                    ).strip()
                    incoming_is_newest = True
                    if semantic_vector is not None and producer_agent_id:
                        # Immutable history is the durable event-time watermark.
                        # This prevents an older execution receipt that arrives
                        # late from becoming current after a newer write,
                        # supersession, or revocation removed/replaced the head.
                        cur.execute(
                            """
                            SELECT max(observed_at)
                            FROM decision_episodes
                            WHERE scope_id = %s
                              AND strategy = %s
                              AND evidence->>'producer_agent_id' = %s
                            """,
                            (
                                episode.scope_id,
                                episode.strategy.value,
                                producer_agent_id,
                            ),
                        )
                        watermark_row = cur.fetchone()
                        latest_observed_at = (
                            watermark_row[0]
                            if watermark_row is not None and watermark_row[0] is not None
                            else None
                        )
                        incoming_is_newest = (
                            latest_observed_at is None
                            or episode.observed_at > latest_observed_at
                        )
                    if semantic_vector is not None and supersedes_episode_id:
                        if not producer_agent_id:
                            raise SupersessionWriteConflict(
                                "supersession requires producer provenance"
                            )
                        if not incoming_is_newest:
                            raise SupersessionWriteConflict(
                                "supersession observation is older than existing producer history"
                            )
                        cur.execute(
                            """
                            DELETE FROM decision_memory_heads
                            WHERE scope_id = %s
                              AND producer_agent_id = %s
                              AND episode_id = %s::UUID
                              AND observed_at < %s
                            RETURNING episode_id::STRING
                            """,
                            (
                                episode.scope_id,
                                producer_agent_id,
                                supersedes_episode_id,
                                episode.observed_at,
                            ),
                        )
                        deleted = cur.fetchone()
                        if deleted is None:
                            raise SupersessionWriteConflict(
                                "supersession target is not the producer's current governed head"
                            )
                    cur.execute(sql, params)
                    if (
                        semantic_vector is not None
                        and producer_agent_id
                        and incoming_is_newest
                    ):
                        cur.execute(
                            """
                            INSERT INTO decision_memory_heads (
                                scope_id, producer_agent_id, strategy, episode_id,
                                situation, outcome, effectiveness, confidence,
                                evidence, execution_receipt_id, supersedes_episode_id,
                                semantic_embedding, semantic_embedding_space,
                                observed_at, recorded_at
                            ) VALUES (
                                %s, %s, %s, %s::UUID,
                                %s, %s, %s, %s,
                                %s::JSONB, %s, %s::UUID, %s::VECTOR, %s, %s, %s
                            )
                            ON CONFLICT (scope_id, producer_agent_id, strategy)
                            DO UPDATE SET
                                episode_id = excluded.episode_id,
                                situation = excluded.situation,
                                outcome = excluded.outcome,
                                effectiveness = excluded.effectiveness,
                                confidence = excluded.confidence,
                                evidence = excluded.evidence,
                                execution_receipt_id = excluded.execution_receipt_id,
                                supersedes_episode_id = excluded.supersedes_episode_id,
                                semantic_embedding = excluded.semantic_embedding,
                                semantic_embedding_space = excluded.semantic_embedding_space,
                                observed_at = excluded.observed_at,
                                recorded_at = excluded.recorded_at
                            WHERE excluded.observed_at > decision_memory_heads.observed_at
                            """,
                            (
                                episode.scope_id,
                                producer_agent_id,
                                episode.strategy.value,
                                episode.episode_id,
                                episode.situation,
                                episode.outcome.value,
                                episode.effectiveness,
                                episode.confidence,
                                json.dumps(dict(episode.evidence)),
                                execution_receipt_id,
                                supersedes_episode_id,
                                semantic_vector,
                                semantic_space,
                                episode.observed_at,
                                episode.recorded_at,
                            ),
                        )
                    if semantic_vector is not None and producer_agent_id:
                        cur.execute(
                            """
                            UPDATE decision_governed_memories
                            SET status = 'REVOKED',
                                revoked_at = now(),
                                revocation_reason = 'support episode is no longer a current head'
                            WHERE scope_id = %s
                              AND status = 'ACTIVE'
                              AND EXISTS (
                                SELECT 1
                                FROM decision_governed_memory_support s
                                WHERE s.memory_id = decision_governed_memories.memory_id
                                  AND NOT EXISTS (
                                    SELECT 1
                                    FROM decision_memory_heads h
                                    WHERE h.scope_id = decision_governed_memories.scope_id
                                      AND h.episode_id = s.episode_id
                                      AND h.semantic_embedding_space = %s
                                  )
                              )
                            """,
                            (episode.scope_id, semantic_space),
                        )
                    if (
                        semantic_vector is not None
                        and producer_agent_id
                        and incoming_is_newest
                    ):
                        enqueue_consolidation(
                            cur,
                            scope_id=episode.scope_id,
                            scope_level=self._scope_level(episode.scope_id),
                        )
                conn.commit()
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        retry_cockroach_serialization(write_transaction)

    def revoke_current_head(
        self,
        *,
        scope_id: str,
        producer_agent_id: str,
        episode_id: str,
        reason: str,
    ) -> MemoryRevocationResult:
        def revoke_transaction() -> MemoryRevocationResult:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT revocation_id::STRING, producer_agent_id
                        FROM decision_memory_revocations
                        WHERE scope_id = %s AND episode_id = %s::UUID
                        """,
                        (scope_id, episode_id),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        if str(existing[1]) != producer_agent_id:
                            raise MemoryRevocationConflict(
                                "revocation belongs to a different producer"
                            )
                        return MemoryRevocationResult(
                            revocation_id=str(existing[0]),
                            episode_id=episode_id,
                            producer_agent_id=producer_agent_id,
                            idempotent_replay=True,
                        )

                    cur.execute(
                        """
                        DELETE FROM decision_memory_heads
                        WHERE scope_id = %s
                          AND producer_agent_id = %s
                          AND episode_id = %s::UUID
                        RETURNING episode_id::STRING
                        """,
                        (scope_id, producer_agent_id, episode_id),
                    )
                    if cur.fetchone() is None:
                        raise MemoryRevocationConflict(
                            "revocation target is not the producer's current governed head"
                        )

                    revocation_id = str(uuid4())
                    cur.execute(
                        """
                        INSERT INTO decision_memory_revocations (
                            revocation_id, scope_id, episode_id,
                            producer_agent_id, reason
                        ) VALUES (%s::UUID, %s, %s::UUID, %s, %s)
                        """,
                        (
                            revocation_id,
                            scope_id,
                            episode_id,
                            producer_agent_id,
                            reason,
                        ),
                    )
                    cur.execute(
                        """
                        UPDATE decision_governed_memories
                        SET status = 'REVOKED',
                            revoked_at = now(),
                            revocation_reason = %s
                        WHERE scope_id = %s
                          AND status = 'ACTIVE'
                          AND memory_id IN (
                            SELECT memory_id
                            FROM decision_governed_memory_support
                            WHERE episode_id = %s::UUID
                          )
                        """,
                        (
                            "support episode revoked: " + reason,
                            scope_id,
                            episode_id,
                        ),
                    )
                    enqueue_consolidation(
                        cur,
                        scope_id=scope_id,
                        scope_level=self._scope_level(scope_id),
                    )
                conn.commit()
                return MemoryRevocationResult(
                    revocation_id=revocation_id,
                    episode_id=episode_id,
                    producer_agent_id=producer_agent_id,
                    idempotent_replay=False,
                )
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        return retry_cockroach_serialization(revoke_transaction)

    def retire_untrusted_heads(
        self,
        *,
        active_producer_agent_ids: set[str] | frozenset[str],
        reason: str,
    ) -> ProducerRetirementResult:
        """Retire current heads owned by producers absent from the active grants."""

        active = {item.strip() for item in active_producer_agent_ids if item.strip()}

        def retire_transaction() -> ProducerRetirementResult:
            conn = self.connection_factory()
            retired = 0
            retired_producers: list[str] = []
            retired_scopes: list[str] = []
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT scope_id, episode_id::STRING, producer_agent_id
                        FROM decision_memory_heads
                        """
                    )
                    rows = cur.fetchall()
                    for scope_id, episode_id, producer_agent_id in rows:
                        producer = str(producer_agent_id)
                        if producer in active:
                            continue
                        cur.execute(
                            """
                            DELETE FROM decision_memory_heads
                            WHERE scope_id = %s
                              AND producer_agent_id = %s
                              AND episode_id = %s::UUID
                            RETURNING episode_id::STRING
                            """,
                            (scope_id, producer, episode_id),
                        )
                        if cur.fetchone() is None:
                            continue
                        cur.execute(
                            """
                            INSERT INTO decision_memory_revocations (
                                revocation_id, scope_id, episode_id,
                                producer_agent_id, reason
                            ) VALUES (%s::UUID, %s, %s::UUID, %s, %s)
                            ON CONFLICT (scope_id, episode_id) DO NOTHING
                            """,
                            (str(uuid4()), scope_id, episode_id, producer, reason),
                        )
                        cur.execute(
                            """
                            UPDATE decision_governed_memories
                            SET status = 'REVOKED',
                                revoked_at = now(),
                                revocation_reason = %s
                            WHERE scope_id = %s
                              AND status = 'ACTIVE'
                              AND memory_id IN (
                                SELECT memory_id
                                FROM decision_governed_memory_support
                                WHERE episode_id = %s::UUID
                              )
                            """,
                            (
                                "support producer retired: " + reason,
                                scope_id,
                                episode_id,
                            ),
                        )
                        enqueue_consolidation(
                            cur,
                            scope_id=str(scope_id),
                            scope_level=self._scope_level(str(scope_id)),
                        )
                        retired += 1
                        retired_producers.append(producer)
                        retired_scopes.append(str(scope_id))
                conn.commit()
                return ProducerRetirementResult(
                    retired_heads=retired,
                    producer_agent_ids=tuple(dict.fromkeys(retired_producers)),
                    scope_ids=tuple(dict.fromkeys(retired_scopes)),
                )
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        return retry_cockroach_serialization(retire_transaction)

    def recall(
        self,
        *,
        scope_id: str,
        situation: str,
        limit: int = 5,
    ) -> list[RecalledEpisode]:
        if self.semantic_query_embedder is not None:
            vector = _vector_literal(self.semantic_query_embedder(situation))
            semantic_space = (self.semantic_embedding_space or "").strip()
            sql = """
                SELECT
                    episode_id::STRING,
                    scope_id,
                    situation,
                    strategy,
                    outcome,
                    effectiveness,
                    confidence,
                    evidence,
                    observed_at,
                    recorded_at,
                    semantic_embedding <=> %s::VECTOR AS cosine_distance
                FROM decision_memory_heads
                WHERE scope_id = %s
                  AND semantic_embedding_space = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM decision_memory_revocations r
                    WHERE r.scope_id = decision_memory_heads.scope_id
                      AND r.episode_id = decision_memory_heads.episode_id
                  )
                  AND COALESCE(upper(evidence->>'memory_status'), 'ACTIVE') <> 'REVOKED'
                  AND (
                    COALESCE(lower(evidence->>'pinned'), 'false') = 'true'
                    OR observed_at >= now() - INTERVAL '90 days'
                  )
                  AND (
                    (outcome = 'SUCCESS' AND effectiveness >= 0.7)
                    OR (outcome = 'FAILED' AND confidence >= 0.6)
                  )
                ORDER BY semantic_embedding <=> %s::VECTOR
                LIMIT %s
            """
        else:
            embed_query = self.query_embedder or self.embedder
            vector = _vector_literal(embed_query(situation))
            sql = """
                SELECT
                    episode_id::STRING,
                    scope_id,
                    situation,
                    strategy,
                    outcome,
                    effectiveness,
                    confidence,
                    evidence,
                    observed_at,
                    recorded_at,
                    embedding <=> %s::VECTOR AS cosine_distance
                FROM decision_episodes
                WHERE scope_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM decision_memory_revocations r
                    WHERE r.scope_id = decision_episodes.scope_id
                      AND r.episode_id = decision_episodes.episode_id
                  )
                ORDER BY embedding <=> %s::VECTOR
                LIMIT %s
            """
        def read_transaction():
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    params = (
                        (vector, scope_id, semantic_space, vector, limit)
                        if self.semantic_query_embedder is not None
                        else (vector, scope_id, vector, limit)
                    )
                    cur.execute(sql, params)
                    return cur.fetchall()
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        rows = retry_cockroach_serialization(read_transaction)

        recalled: list[RecalledEpisode] = []
        for row in rows:
            distance = max(0.0, min(1.0, float(row[10])))
            recalled.append(
                RecalledEpisode(
                    episode=DecisionEpisode(
                        episode_id=row[0],
                        scope_id=row[1],
                        situation=row[2],
                        strategy=Strategy(row[3]),
                        outcome=Outcome(row[4]),
                        effectiveness=float(row[5]),
                        confidence=float(row[6]),
                        evidence=row[7] or {},
                        observed_at=row[8],
                        recorded_at=row[9],
                    ),
                    similarity=1.0 - distance,
                )
            )
        return recalled

    def recall_adaptive(
        self,
        *,
        scope_id: str,
        situation: str,
        minimum_similarity: float,
    ) -> list[GovernedMemory]:
        """Recall promoted L2/L3 knowledge with DVI fast path + exact coverage."""

        if self.semantic_query_embedder is None:
            return []
        if not 0.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity must be between 0 and 1")
        semantic_space = (self.semantic_embedding_space or "").strip()
        if not semantic_space:
            raise ValueError("semantic_embedding_space is required")

        vector = _vector_literal(self.semantic_query_embedder(situation))
        max_distance = 1.0 - minimum_similarity
        ann_sql = adaptive_semantic_ann_sql(
            vector_expr="%s::VECTOR",
            scope_expr="%s",
            space_expr="%s",
        )
        coverage_sql = adaptive_semantic_coverage_sql(
            vector_expr="%s::VECTOR",
            scope_expr="%s",
            space_expr="%s",
            governance_revision_expr="%s",
            max_distance_expr="%s",
        )

        def read_transaction():
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(ann_sql, (vector, scope_id, semantic_space, vector))
                    ann_rows = cur.fetchall()
                    cur.execute(
                        coverage_sql,
                        (
                            vector,
                            scope_id,
                            semantic_space,
                            ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
                            vector,
                            max_distance,
                        ),
                    )
                    coverage_rows = cur.fetchall()
                # Exact coverage is authoritative. Executing the ANN query
                # proves/warms the DVI fast path, while support-lineage checks
                # in coverage prevent a stale ANN hit from bypassing governance.
                _ = ann_rows
                return sorted(
                    (tuple(row) for row in coverage_rows),
                    key=lambda row: float(row[28]),
                )
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        rows = retry_cockroach_serialization(read_transaction)
        return [_adaptive_memory_from_row(tuple(row)) for row in rows]

    def recall_governed(
        self,
        *,
        scope_id: str,
        situation: str,
        minimum_similarity: float,
    ) -> list[RecalledEpisode]:
        """Return complete governed evidence above the relevance threshold.

        The semantic path intentionally performs two reads with one query
        embedding: an ANN top-32 read exercises the production DVI for the common
        fast path, while an exact threshold coverage read adds every other
        admissible head whose similarity can affect governance. Correctness is
        therefore not bounded by the ANN K value.
        """

        if not 0.0 <= minimum_similarity <= 1.0:
            raise ValueError("minimum_similarity must be between 0 and 1")
        max_distance = 1.0 - minimum_similarity

        if self.semantic_query_embedder is not None:
            vector = _vector_literal(self.semantic_query_embedder(situation))
            semantic_space = (self.semantic_embedding_space or "").strip()
            ann_sql = semantic_ann_sql(
                vector_expr="%s::VECTOR",
                scope_expr="%s",
                space_expr="%s",
            )
            coverage_sql = semantic_coverage_sql(
                vector_expr="%s::VECTOR",
                scope_expr="%s",
                space_expr="%s",
                max_distance_expr="%s",
            )

            def semantic_read_transaction():
                conn = self.connection_factory()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            ann_sql,
                            (vector, scope_id, semantic_space, vector),
                        )
                        ann_rows = cur.fetchall()
                        cur.execute(
                            coverage_sql,
                            (
                                vector,
                                scope_id,
                                semantic_space,
                                vector,
                                max_distance,
                            ),
                        )
                        coverage_rows = cur.fetchall()
                    merged = {row[0]: row for row in ann_rows}
                    for row in coverage_rows:
                        merged[row[0]] = row
                    return sorted(merged.values(), key=lambda row: float(row[10]))
                finally:
                    conn.close()

            rows = retry_cockroach_serialization(semantic_read_transaction)
        else:
            embed_query = self.query_embedder or self.embedder
            vector = _vector_literal(embed_query(situation))
            sql = """
                SELECT e.episode_id::STRING, e.scope_id, e.situation, e.strategy,
                       e.outcome, e.effectiveness, e.confidence, e.evidence,
                       e.observed_at, e.recorded_at,
                       e.embedding <=> %s::VECTOR AS cosine_distance
                FROM decision_episodes e
                WHERE e.scope_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM decision_memory_revocations r
                    WHERE r.scope_id = e.scope_id AND r.episode_id = e.episode_id
                  )
                  AND e.embedding <=> %s::VECTOR <= %s
                ORDER BY cosine_distance
            """

            def deterministic_read_transaction():
                conn = self.connection_factory()
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql, (vector, scope_id, vector, max_distance))
                        return cur.fetchall()
                finally:
                    conn.close()

            rows = retry_cockroach_serialization(deterministic_read_transaction)

        recalled: list[RecalledEpisode] = []
        for row in rows:
            distance = max(0.0, min(1.0, float(row[10])))
            recalled.append(
                RecalledEpisode(
                    episode=DecisionEpisode(
                        episode_id=row[0],
                        scope_id=row[1],
                        situation=row[2],
                        strategy=Strategy(row[3]),
                        outcome=Outcome(row[4]),
                        effectiveness=float(row[5]),
                        confidence=float(row[6]),
                        evidence=row[7] or {},
                        observed_at=row[8],
                        recorded_at=row[9],
                    ),
                    similarity=1.0 - distance,
                )
            )
        return recalled
