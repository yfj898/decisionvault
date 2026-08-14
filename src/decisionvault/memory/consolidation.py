from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
from typing import Callable, Iterable, Sequence

from decisionvault.adaptive_memory import (
    ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
    ConsolidationCandidate,
    ConsolidationGovernanceResult,
    GovernedMemory,
    MemoryConsolidationGovernor,
    MemoryConsolidator,
    MemoryPolarity,
    MemoryScopeLevel,
    MemoryStatus,
    StrategyEffectivenessStats,
    adaptive_rule_key,
)
from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.retry import retry_cockroach_serialization


Vector = Sequence[float]


def _vector_literal(vector: Vector) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _json_list(items: Iterable[str]) -> str:
    return json.dumps(list(items), sort_keys=True, separators=(",", ":"))


def _knowledge_text(memory: GovernedMemory) -> str:
    return " ".join(
        (
            f"situation class {memory.situation_class}",
            "preconditions " + " ".join(sorted(memory.applicability.preconditions)),
            "exclusions " + " ".join(sorted(memory.applicability.exclusions)),
            f"intervention {memory.intervention.value}",
            f"polarity {memory.polarity.value}",
            f"expected outcome {memory.expected_outcome.value}",
        )
    ).strip()


@dataclass(frozen=True, slots=True)
class ConsolidationBatchResult:
    scope_id: str
    candidate_count: int
    promoted_count: int
    abstained_count: int
    memory_ids: tuple[str, ...]
    resolutions: tuple[str, ...]


@dataclass(slots=True)
class CockroachMemoryConsolidationService:
    """Atomic candidate→governance→promotion service for CockroachDB.

    The transaction re-reads current heads and writes both the candidate audit
    and any promoted memory. CockroachDB SERIALIZABLE retries therefore make a
    concurrent normal write, supersession, or revocation invalidate/retry the
    consolidation rather than allowing a stale evidence snapshot to promote.
    """

    connection_factory: Callable[[], object]
    semantic_embedder: Callable[[str], Vector]
    semantic_embedding_space: str
    consolidator: MemoryConsolidator = field(default_factory=MemoryConsolidator)
    governor: MemoryConsolidationGovernor = field(
        default_factory=MemoryConsolidationGovernor
    )

    def __post_init__(self) -> None:
        if not self.semantic_embedding_space.strip():
            raise ValueError("semantic_embedding_space is required")

    def consolidate_scope(
        self,
        *,
        scope_id: str,
        scope_level: MemoryScopeLevel = MemoryScopeLevel.TEAM,
        active_producer_agent_ids: set[str] | frozenset[str] | None = None,
        now: datetime | None = None,
    ) -> ConsolidationBatchResult:
        if not scope_id.strip():
            raise ValueError("scope_id is required")
        governed_at = now or datetime.now(timezone.utc)

        def transaction() -> ConsolidationBatchResult:
            conn = self.connection_factory()
            try:
                with conn.cursor() as cur:
                    self._expire_active_memories(
                        cur, scope_id=scope_id, as_of=governed_at
                    )
                    episodes = self._load_current_heads_for_update(cur, scope_id)
                    self._materialize_strategy_effectiveness(
                        cur,
                        scope_id=scope_id,
                        episodes=episodes,
                        recorded_at=governed_at,
                    )
                    candidates = self.consolidator.consolidate(
                        episodes,
                        semantic_embedding_space=self.semantic_embedding_space,
                        scope_level=scope_level,
                        now=governed_at,
                    )
                    promoted_ids: list[str] = []
                    resolutions: list[str] = []
                    promoted_count = 0
                    abstained_count = 0
                    for candidate in candidates:
                        self._insert_candidate(cur, candidate)
                        existing_memory = self._existing_memory_for_candidate(
                            cur, candidate.candidate_id
                        )
                        if existing_memory is not None:
                            existing_memory_id, existing_status = existing_memory
                            if existing_status == MemoryStatus.ACTIVE.value:
                                promoted_ids.append(existing_memory_id)
                                resolutions.append("IDEMPOTENT_PROMOTION_REPLAY")
                                promoted_count += 1
                            else:
                                resolutions.append(
                                    "HISTORICAL_PROMOTION_NOT_REACTIVATED"
                                )
                                abstained_count += 1
                            continue

                        governance = self.governor.evaluate(
                            candidate,
                            current_episodes=episodes,
                            current_semantic_embedding_space=(
                                self.semantic_embedding_space
                            ),
                            active_producer_agent_ids=active_producer_agent_ids,
                            now=governed_at,
                        )
                        if not governance.promoted or governance.memory is None:
                            if governance.resolution == "CONTRADICTION_ABSTAIN":
                                self._revoke_conflicting_active_rules(
                                    cur,
                                    candidate=candidate,
                                    reason=(
                                        "independent contradictory current evidence "
                                        "invalidated the promoted rule"
                                    ),
                                )
                            self._finalize_candidate(
                                cur,
                                candidate,
                                governance,
                                status="ABSTAIN",
                                governed_at=governed_at,
                            )
                            resolutions.append(governance.resolution)
                            abstained_count += 1
                            continue

                        memory = governance.memory
                        active = self._active_rule_for_update(cur, candidate)
                        if active is not None:
                            active_memory_id, active_observed_to = active
                            if candidate.observed_to <= active_observed_to:
                                stale = ConsolidationGovernanceResult(
                                    promoted=False,
                                    resolution="LATE_EVIDENCE_ABSTAIN",
                                    reason=(
                                        "candidate evidence window is not newer than the "
                                        "active governed memory"
                                    ),
                                    conflict=False,
                                    trace=governance.trace,
                                )
                                self._finalize_candidate(
                                    cur,
                                    candidate,
                                    stale,
                                    status="ABSTAIN",
                                    governed_at=governed_at,
                                )
                                resolutions.append(stale.resolution)
                                abstained_count += 1
                                continue
                            memory = replace(
                                memory, supersedes_memory_id=active_memory_id
                            )
                            cur.execute(
                                """
                                UPDATE decision_governed_memories
                                SET status = 'SUPERSEDED'
                                WHERE memory_id = %s::UUID
                                  AND status = 'ACTIVE'
                                  AND observed_to < %s
                                RETURNING memory_id::STRING
                                """,
                                (active_memory_id, candidate.observed_to),
                            )
                            if cur.fetchone() is None:
                                raise RuntimeError(
                                    "active governed memory changed during consolidation"
                                )

                        self._insert_governed_memory(cur, memory)
                        self._insert_support_rows(cur, memory, episodes)
                        self._finalize_candidate(
                            cur,
                            candidate,
                            replace(governance, memory=memory),
                            status="PROMOTED",
                            governed_at=governed_at,
                        )
                        promoted_ids.append(memory.memory_id)
                        resolutions.append("PROMOTED")
                        promoted_count += 1
                conn.commit()
                return ConsolidationBatchResult(
                    scope_id=scope_id,
                    candidate_count=len(candidates),
                    promoted_count=promoted_count,
                    abstained_count=abstained_count,
                    memory_ids=tuple(promoted_ids),
                    resolutions=tuple(resolutions),
                )
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                raise
            finally:
                conn.close()

        return retry_cockroach_serialization(transaction)

    @staticmethod
    def _revoke_conflicting_active_rules(
        cur: object,
        *,
        candidate: ConsolidationCandidate,
        reason: str,
    ) -> None:
        rule_key = adaptive_rule_key(
            situation_class=candidate.situation_class,
            intervention=candidate.intervention,
            applicability=candidate.applicability,
        )
        cur.execute(
            """
            UPDATE decision_governed_memories
            SET status = 'REVOKED',
                revoked_at = now(),
                revocation_reason = %s
            WHERE scope_id = %s
              AND rule_key = %s
              AND semantic_embedding_space = %s
              AND status = 'ACTIVE'
            """,
            (
                reason,
                candidate.scope_id,
                rule_key,
                candidate.semantic_embedding_space,
            ),
        )

    @staticmethod
    def _expire_active_memories(
        cur: object, *, scope_id: str, as_of: datetime
    ) -> None:
        cur.execute(
            """
            UPDATE decision_governed_memories
            SET status = 'EXPIRED'
            WHERE scope_id = %s
              AND status = 'ACTIVE'
              AND expires_at IS NOT NULL
              AND expires_at < %s
            """,
            (scope_id, as_of),
        )

    def _materialize_strategy_effectiveness(
        self,
        cur: object,
        *,
        scope_id: str,
        episodes: list[DecisionEpisode],
        recorded_at: datetime,
    ) -> None:
        """Refresh the L2 semantic statistics projection from current L1 heads.

        The projection is deliberately rebuilt for the scope inside the same
        SERIALIZABLE transaction. Revocation/supersession therefore removes
        obsolete statistics instead of allowing append-only historical rows to
        keep contributing. L2 rows are auditable knowledge only; they are not
        read by the execution policy.
        """

        cur.execute(
            "DELETE FROM decision_strategy_effectiveness WHERE scope_id = %s",
            (scope_id,),
        )
        keys = sorted(
            {
                (
                    str(episode.evidence.get("situation_class", "unclassified"))
                    .strip()
                    .lower()
                    or "unclassified",
                    episode.strategy,
                )
                for episode in episodes
            },
            key=lambda item: (item[0], item[1].value),
        )
        for situation_class, strategy in keys:
            stats = StrategyEffectivenessStats.from_episodes(
                episodes,
                strategy=strategy,
                situation_class=situation_class,
                now=recorded_at,
            )
            relevant = [
                episode
                for episode in episodes
                if episode.strategy == strategy
                and (
                    str(
                        episode.evidence.get("situation_class", "unclassified")
                    ).strip().lower()
                    or "unclassified"
                )
                == situation_class
            ]
            if not relevant or stats.sample_count == 0:
                continue
            observed_to = max(episode.observed_at for episode in relevant)
            cur.execute(
                """
                INSERT INTO decision_strategy_effectiveness (
                    scope_id, situation_class, strategy,
                    semantic_embedding_space, sample_count, success_count,
                    failure_count, effectiveness, independent_producer_count,
                    confidence, observed_to, recorded_at, governance_revision
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    scope_id,
                    situation_class,
                    strategy.value,
                    self.semantic_embedding_space,
                    stats.sample_count,
                    stats.success_count,
                    stats.failure_count,
                    stats.effectiveness,
                    stats.independent_producer_count,
                    stats.confidence,
                    observed_to,
                    recorded_at,
                    ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
                ),
            )

    def _load_current_heads_for_update(
        self, cur: object, scope_id: str
    ) -> list[DecisionEpisode]:
        cur.execute(
            """
            SELECT episode_id::STRING, scope_id, situation, strategy, outcome,
                   effectiveness, confidence, evidence,
                   semantic_embedding_space, observed_at, recorded_at
            FROM decision_memory_heads
            WHERE scope_id = %s
            FOR UPDATE
            """,
            (scope_id,),
        )
        episodes: list[DecisionEpisode] = []
        for row in cur.fetchall():
            evidence = dict(row[7] or {})
            evidence["semantic_embedding_space"] = str(row[8])
            episodes.append(
                DecisionEpisode(
                    episode_id=str(row[0]),
                    scope_id=str(row[1]),
                    situation=str(row[2]),
                    strategy=Strategy(str(row[3])),
                    outcome=Outcome(str(row[4])),
                    effectiveness=float(row[5]),
                    confidence=float(row[6]),
                    evidence=evidence,
                    observed_at=row[9],
                    recorded_at=row[10],
                )
            )
        return episodes

    @staticmethod
    def _insert_candidate(cur: object, candidate: ConsolidationCandidate) -> None:
        rule_key = adaptive_rule_key(
            situation_class=candidate.situation_class,
            intervention=candidate.intervention,
            applicability=candidate.applicability,
        )
        cur.execute(
            """
            INSERT INTO decision_memory_consolidation_candidates (
                candidate_id, scope_id, scope_level, memory_type, polarity,
                situation_class, rule_key, preconditions, exclusions, intervention,
                expected_outcome, supporting_episode_ids, producer_set,
                positive_episode_ids, negative_episode_ids, confidence,
                observed_from, observed_to, created_at, recorded_at,
                governance_revision, semantic_embedding_space, memory_class,
                status, supersedes_memory_id
            ) VALUES (
                %s::UUID, %s, %s, %s, %s,
                %s, %s, %s::JSONB, %s::JSONB, %s,
                %s, %s::JSONB, %s::JSONB,
                %s::JSONB, %s::JSONB, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                'CANDIDATE', %s::UUID
            )
            ON CONFLICT (candidate_id) DO NOTHING
            """,
            (
                candidate.candidate_id,
                candidate.scope_id,
                candidate.scope_level.value,
                candidate.memory_type.value,
                candidate.polarity.value,
                candidate.situation_class,
                rule_key,
                _json_list(sorted(candidate.applicability.preconditions)),
                _json_list(sorted(candidate.applicability.exclusions)),
                candidate.intervention.value,
                candidate.expected_outcome.value,
                _json_list(candidate.supporting_episode_ids),
                _json_list(candidate.producer_set),
                _json_list(candidate.positive_episode_ids),
                _json_list(candidate.negative_episode_ids),
                candidate.confidence,
                candidate.observed_from,
                candidate.observed_to,
                candidate.created_at,
                candidate.recorded_at,
                candidate.governance_revision,
                candidate.semantic_embedding_space,
                candidate.memory_class.value,
                candidate.supersedes_memory_id,
            ),
        )

    @staticmethod
    def _existing_memory_for_candidate(
        cur: object, candidate_id: str
    ) -> tuple[str, str] | None:
        cur.execute(
            """
            SELECT memory_id::STRING, status
            FROM decision_governed_memories
            WHERE candidate_id = %s::UUID
            LIMIT 1
            """,
            (candidate_id,),
        )
        row = cur.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    @staticmethod
    def _active_rule_for_update(
        cur: object, candidate: ConsolidationCandidate
    ) -> tuple[str, datetime] | None:
        rule_key = adaptive_rule_key(
            situation_class=candidate.situation_class,
            intervention=candidate.intervention,
            applicability=candidate.applicability,
        )
        cur.execute(
            """
            SELECT memory_id::STRING, observed_to
            FROM decision_governed_memories
            WHERE scope_id = %s
              AND rule_key = %s
              AND semantic_embedding_space = %s
              AND status = 'ACTIVE'
            FOR UPDATE
            """,
            (
                candidate.scope_id,
                rule_key,
                candidate.semantic_embedding_space,
            ),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return str(row[0]), row[1]

    def _insert_governed_memory(self, cur: object, memory: GovernedMemory) -> None:
        embedding = _vector_literal(self.semantic_embedder(_knowledge_text(memory)))
        rule_key = adaptive_rule_key(
            situation_class=memory.situation_class,
            intervention=memory.intervention,
            applicability=memory.applicability,
        )
        cur.execute(
            """
            INSERT INTO decision_governed_memories (
                memory_id, candidate_id, scope_id, scope_level, memory_type,
                polarity, situation_class, rule_key, preconditions, exclusions,
                intervention, expected_outcome, supporting_episode_ids,
                producer_set, positive_episode_ids, negative_episode_ids,
                confidence, observed_from, observed_to, created_at, recorded_at,
                governance_revision, semantic_embedding, semantic_embedding_space,
                memory_class, expires_at, status, supersedes_memory_id,
                revoked_at, revocation_reason
            ) VALUES (
                %s::UUID, %s::UUID, %s, %s, %s,
                %s, %s, %s, %s::JSONB, %s::JSONB,
                %s, %s, %s::JSONB,
                %s::JSONB, %s::JSONB, %s::JSONB,
                %s, %s, %s, %s, %s,
                %s, %s::VECTOR, %s,
                %s, %s, %s, %s::UUID,
                %s, %s
            )
            """,
            (
                memory.memory_id,
                memory.candidate_id,
                memory.scope_id,
                memory.scope_level.value,
                memory.memory_type.value,
                memory.polarity.value,
                memory.situation_class,
                rule_key,
                _json_list(sorted(memory.applicability.preconditions)),
                _json_list(sorted(memory.applicability.exclusions)),
                memory.intervention.value,
                memory.expected_outcome.value,
                _json_list(memory.supporting_episode_ids),
                _json_list(memory.producer_set),
                _json_list(memory.positive_episode_ids),
                _json_list(memory.negative_episode_ids),
                memory.confidence,
                memory.observed_from,
                memory.observed_to,
                memory.created_at,
                memory.recorded_at,
                memory.governance_revision,
                embedding,
                memory.semantic_embedding_space,
                memory.memory_class.value,
                memory.expires_at,
                memory.status.value,
                memory.supersedes_memory_id,
                memory.revoked_at,
                memory.revocation_reason,
            ),
        )

    @staticmethod
    def _insert_support_rows(
        cur: object,
        memory: GovernedMemory,
        episodes: list[DecisionEpisode],
    ) -> None:
        by_id = {episode.episode_id: episode for episode in episodes}
        positive = set(memory.positive_episode_ids)
        for episode_id in memory.supporting_episode_ids:
            episode = by_id[episode_id]
            producer = str(episode.evidence.get("producer_agent_id", "")).strip()
            polarity = (
                MemoryPolarity.POSITIVE.value
                if episode_id in positive
                else MemoryPolarity.AVOID.value
            )
            cur.execute(
                """
                INSERT INTO decision_governed_memory_support (
                    memory_id, episode_id, producer_agent_id, evidence_polarity
                ) VALUES (%s::UUID, %s::UUID, %s, %s)
                ON CONFLICT (memory_id, episode_id) DO NOTHING
                """,
                (memory.memory_id, episode_id, producer, polarity),
            )

    @staticmethod
    def _finalize_candidate(
        cur: object,
        candidate: ConsolidationCandidate,
        governance: ConsolidationGovernanceResult,
        *,
        status: str,
        governed_at: datetime,
    ) -> None:
        trace = asdict(governance.trace) if governance.trace is not None else {}
        supersedes = (
            governance.memory.supersedes_memory_id
            if governance.memory is not None
            else candidate.supersedes_memory_id
        )
        cur.execute(
            """
            UPDATE decision_memory_consolidation_candidates
            SET status = %s,
                governance_resolution = %s,
                governance_trace = %s::JSONB,
                governed_at = %s,
                supersedes_memory_id = %s::UUID
            WHERE candidate_id = %s::UUID
            """,
            (
                status,
                governance.resolution,
                json.dumps(trace, sort_keys=True, separators=(",", ":")),
                governed_at,
                supersedes,
                candidate.candidate_id,
            ),
        )


__all__ = ["CockroachMemoryConsolidationService", "ConsolidationBatchResult"]
