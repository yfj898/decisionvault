from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
import json
from uuid import uuid4

from decisionvault.domain import (
    DecisionEpisode,
    Outcome,
    RecalledEpisode,
    Strategy,
)
from decisionvault.memory.retry import retry_cockroach_serialization


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


def _vector_literal(vector: Vector) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


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

    def __post_init__(self) -> None:
        semantic_enabled = (
            self.semantic_embedder is not None
            or self.semantic_query_embedder is not None
        )
        if semantic_enabled and not (self.semantic_embedding_space or "").strip():
            raise ValueError(
                "semantic_embedding_space is required for semantic persistence/retrieval"
            )

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
                    supersedes_episode_id, embedding, created_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::UUID, %s::VECTOR, %s
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
                episode.created_at,
            )
        else:
            sql = """
                INSERT INTO decision_episodes (
                    episode_id, scope_id, situation, strategy, outcome,
                    effectiveness, confidence, evidence, execution_receipt_id,
                    supersedes_episode_id, embedding,
                    semantic_embedding, semantic_embedding_space, created_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::UUID, %s::VECTOR,
                    %s::VECTOR, %s, %s
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
                episode.created_at,
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
                            SELECT max(created_at)
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
                            or episode.created_at > latest_observed_at
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
                              AND created_at < %s
                            RETURNING episode_id::STRING
                            """,
                            (
                                episode.scope_id,
                                producer_agent_id,
                                supersedes_episode_id,
                                episode.created_at,
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
                                semantic_embedding, semantic_embedding_space, created_at
                            ) VALUES (
                                %s, %s, %s, %s::UUID,
                                %s, %s, %s, %s,
                                %s::JSONB, %s, %s::UUID, %s::VECTOR, %s, %s
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
                                created_at = excluded.created_at
                            WHERE excluded.created_at > decision_memory_heads.created_at
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
                                episode.created_at,
                            ),
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
                    created_at,
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
                    OR created_at >= now() - INTERVAL '90 days'
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
                    created_at,
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
            distance = max(0.0, min(1.0, float(row[9])))
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
                        created_at=row[8],
                    ),
                    similarity=1.0 - distance,
                )
            )
        return recalled

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
            admissible = """
                  AND NOT EXISTS (
                    SELECT 1 FROM decision_memory_revocations r
                    WHERE r.scope_id = h.scope_id AND r.episode_id = h.episode_id
                  )
                  AND COALESCE(upper(h.evidence->>'memory_status'), 'ACTIVE') <> 'REVOKED'
                  AND (
                    COALESCE(lower(h.evidence->>'pinned'), 'false') = 'true'
                    OR h.created_at >= now() - INTERVAL '90 days'
                  )
                  AND (
                    (h.outcome = 'SUCCESS' AND h.effectiveness >= 0.7)
                    OR (h.outcome = 'FAILED' AND h.confidence >= 0.6)
                  )
            """
            ann_sql = f"""
                SELECT h.episode_id::STRING, h.scope_id, h.situation, h.strategy,
                       h.outcome, h.effectiveness, h.confidence, h.evidence,
                       h.created_at,
                       h.semantic_embedding <=> %s::VECTOR AS cosine_distance
                FROM decision_memory_heads h
                WHERE h.scope_id = %s
                  AND h.semantic_embedding_space = %s
                  {admissible}
                ORDER BY h.semantic_embedding <=> %s::VECTOR
                LIMIT 32
            """
            coverage_sql = f"""
                SELECT h.episode_id::STRING, h.scope_id, h.situation, h.strategy,
                       h.outcome, h.effectiveness, h.confidence, h.evidence,
                       h.created_at,
                       h.semantic_embedding <=> %s::VECTOR AS cosine_distance
                FROM decision_memory_heads h
                WHERE h.scope_id = %s
                  AND h.semantic_embedding_space = %s
                  {admissible}
                  AND h.semantic_embedding <=> %s::VECTOR <= %s
                ORDER BY cosine_distance
            """

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
                    return sorted(merged.values(), key=lambda row: float(row[9]))
                finally:
                    conn.close()

            rows = retry_cockroach_serialization(semantic_read_transaction)
        else:
            embed_query = self.query_embedder or self.embedder
            vector = _vector_literal(embed_query(situation))
            sql = """
                SELECT e.episode_id::STRING, e.scope_id, e.situation, e.strategy,
                       e.outcome, e.effectiveness, e.confidence, e.evidence,
                       e.created_at,
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
            distance = max(0.0, min(1.0, float(row[9])))
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
                        created_at=row[8],
                    ),
                    similarity=1.0 - distance,
                )
            )
        return recalled
