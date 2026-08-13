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

    def save(self, episode: DecisionEpisode) -> None:
        vector = _vector_literal(self.embedder(episode.situation))
        sql = """
            INSERT INTO decision_episodes (
                episode_id, scope_id, situation, strategy, outcome,
                effectiveness, confidence, evidence, embedding, created_at
            )
            VALUES (
                %s::UUID, %s, %s, %s, %s,
                %s, %s, %s::JSONB, %s::VECTOR, %s
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
            vector,
            episode.created_at,
        )
        conn = self.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
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
