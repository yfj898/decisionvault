from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
import json

from decisionvault.domain import (
    DecisionEpisode,
    Outcome,
    RecalledEpisode,
    Strategy,
)


Vector = Sequence[float]


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

    def save(self, episode: DecisionEpisode) -> None:
        vector = _vector_literal(self.embedder(episode.situation))
        execution_receipt_id = str(
            episode.evidence.get("execution_receipt_id", "")
        ).strip() or None
        semantic_vector = (
            _vector_literal(self.semantic_embedder(episode.situation))
            if self.semantic_embedder is not None
            else None
        )
        if semantic_vector is None:
            sql = """
                INSERT INTO decision_episodes (
                    episode_id, scope_id, situation, strategy, outcome,
                    effectiveness, confidence, evidence, execution_receipt_id,
                    embedding, created_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::VECTOR, %s
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
                vector,
                episode.created_at,
            )
        else:
            sql = """
                INSERT INTO decision_episodes (
                    episode_id, scope_id, situation, strategy, outcome,
                    effectiveness, confidence, evidence, execution_receipt_id, embedding,
                    semantic_embedding, created_at
                )
                VALUES (
                    %s::UUID, %s, %s, %s, %s,
                    %s, %s, %s::JSONB, %s, %s::VECTOR,
                    %s::VECTOR, %s
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
                vector,
                semantic_vector,
                episode.created_at,
            )
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                producer_agent_id = str(
                    episode.evidence.get("producer_agent_id", "")
                ).strip()
                if semantic_vector is not None and producer_agent_id:
                    supersedes_episode_id = str(
                        episode.evidence.get("supersedes_episode_id", "")
                    ).strip()
                    if supersedes_episode_id:
                        cur.execute(
                            """
                            DELETE FROM decision_memory_heads
                            WHERE scope_id = %s AND episode_id = %s::UUID
                            """,
                            (episode.scope_id, supersedes_episode_id),
                        )
                    cur.execute(
                        """
                        UPSERT INTO decision_memory_heads (
                            scope_id, producer_agent_id, strategy, episode_id,
                            situation, outcome, effectiveness, confidence,
                            evidence, execution_receipt_id, semantic_embedding, created_at
                        ) VALUES (
                            %s, %s, %s, %s::UUID,
                            %s, %s, %s, %s,
                            %s::JSONB, %s, %s::VECTOR, %s
                        )
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
                            semantic_vector,
                            episode.created_at,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

    def recall(
        self,
        *,
        scope_id: str,
        situation: str,
        limit: int = 5,
    ) -> list[RecalledEpisode]:
        if self.semantic_query_embedder is not None:
            vector = _vector_literal(self.semantic_query_embedder(situation))
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
                ORDER BY embedding <=> %s::VECTOR
                LIMIT %s
            """
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (vector, scope_id, vector, limit))
                rows = cur.fetchall()
        finally:
            conn.close()

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
