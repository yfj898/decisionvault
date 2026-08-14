from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
import json
from math import exp
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from decisionvault.domain import DecisionEpisode, Outcome, Strategy


ADAPTIVE_MEMORY_GOVERNANCE_REVISION = "governed-adaptive-memory-v1"
PRODUCTION_ADAPTIVE_MIN_EFFECTIVE_CONFIDENCE = 0.30


class MemoryType(StrEnum):
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"


class MemoryPolarity(StrEnum):
    POSITIVE = "POSITIVE"
    AVOID = "AVOID"


class MemoryStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class MemoryScopeLevel(StrEnum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    GLOBAL = "GLOBAL"

    @property
    def minimum_distinct_producers(self) -> int:
        return {
            MemoryScopeLevel.PRIVATE: 1,
            MemoryScopeLevel.TEAM: 2,
            MemoryScopeLevel.GLOBAL: 3,
        }[self]


class MemoryClass(StrEnum):
    EPHEMERAL = "EPHEMERAL"
    SHORT_TERM = "SHORT_TERM"
    OPERATIONAL = "OPERATIONAL"
    LONG_TERM = "LONG_TERM"
    STRUCTURAL = "STRUCTURAL"

    @property
    def max_age(self) -> timedelta | None:
        return {
            MemoryClass.EPHEMERAL: timedelta(hours=1),
            MemoryClass.SHORT_TERM: timedelta(days=7),
            MemoryClass.OPERATIONAL: timedelta(days=90),
            MemoryClass.LONG_TERM: timedelta(days=365),
            MemoryClass.STRUCTURAL: None,
        }[self]


def _csv_set(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (tuple, list, set, frozenset)):
        raw = value
    else:
        raw = (str(value),)
    return frozenset(
        normalized
        for item in raw
        if (normalized := str(item).strip().lower().replace(" ", "_"))
    )


def _producer_id(episode: DecisionEpisode) -> str:
    return str(episode.evidence.get("producer_agent_id", "")).strip()


def _situation_class(episode: DecisionEpisode) -> str:
    explicit = str(episode.evidence.get("situation_class", "")).strip().lower()
    if explicit:
        return explicit
    scenario = str(episode.evidence.get("execution_scenario", "")).strip().lower()
    if scenario:
        return scenario
    return "unclassified"


def _episode_semantic_space(episode: DecisionEpisode) -> str:
    return str(episode.evidence.get("semantic_embedding_space", "")).strip()


def adaptive_rule_key(
    *,
    situation_class: str,
    intervention: Strategy,
    applicability: "Applicability",
) -> str:
    """Stable identity for one applicability-bounded intervention rule.

    Polarity is deliberately excluded: POSITIVE and AVOID are competing governed
    states of the same rule, not two rules that may remain ACTIVE in parallel.
    """

    payload = {
        "situation_class": situation_class.strip().lower(),
        "intervention": intervention.value,
        "preconditions": sorted(applicability.preconditions),
        "exclusions": sorted(applicability.exclusions),
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _qualified_success(episode: DecisionEpisode) -> bool:
    return (
        episode.outcome == Outcome.SUCCESS
        and episode.effectiveness >= 0.7
        and episode.confidence >= 0.6
    )


def _qualified_failure(episode: DecisionEpisode) -> bool:
    return (
        episode.outcome == Outcome.FAILED
        and episode.effectiveness <= 0.3
        and episode.confidence >= 0.6
    )


def _is_evidence_active(episode: DecisionEpisode) -> bool:
    return str(episode.evidence.get("memory_status", "ACTIVE")).upper() == "ACTIVE"


@dataclass(frozen=True, slots=True)
class Applicability:
    preconditions: frozenset[str] = frozenset()
    exclusions: frozenset[str] = frozenset()

    def matches(self, context_tags: set[str] | frozenset[str]) -> bool:
        normalized = {str(tag).strip().lower().replace(" ", "_") for tag in context_tags}
        return self.preconditions.issubset(normalized) and not (
            self.exclusions & normalized
        )

    @classmethod
    def from_episode(cls, episode: DecisionEpisode) -> "Applicability":
        return cls(
            preconditions=_csv_set(
                episode.evidence.get(
                    "preconditions", episode.evidence.get("context_tags", "")
                )
            ),
            exclusions=_csv_set(episode.evidence.get("exclusions", "")),
        )


@dataclass(frozen=True, slots=True)
class WorkingMemory:
    """L0 request-local context. It is never persisted or promoted."""

    scope_id: str
    situation: str
    context_tags: frozenset[str]
    created_at: datetime

    @classmethod
    def from_request(
        cls,
        *,
        scope_id: str,
        situation: str,
        now: datetime | None = None,
    ) -> "WorkingMemory":
        if not scope_id.strip():
            raise ValueError("working memory scope_id is required")
        if not situation.strip():
            raise ValueError("working memory situation is required")
        return cls(
            scope_id=scope_id,
            situation=situation,
            context_tags=derive_context_tags(situation),
            created_at=now or datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class LLMPatternProposal:
    """Non-authoritative model output that must match evidence-derived fields."""

    situation_class: str
    intervention: Strategy
    preconditions: frozenset[str]
    exclusions: frozenset[str]
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class ConsolidationCandidate:
    candidate_id: str
    scope_id: str
    scope_level: MemoryScopeLevel
    memory_type: MemoryType
    polarity: MemoryPolarity
    situation_class: str
    applicability: Applicability
    intervention: Strategy
    expected_outcome: Outcome
    supporting_episode_ids: tuple[str, ...]
    producer_set: tuple[str, ...]
    positive_episode_ids: tuple[str, ...]
    negative_episode_ids: tuple[str, ...]
    confidence: float
    observed_from: datetime
    observed_to: datetime
    created_at: datetime
    recorded_at: datetime
    governance_revision: str
    semantic_embedding_space: str
    memory_class: MemoryClass
    status: MemoryStatus = MemoryStatus.CANDIDATE
    supersedes_memory_id: str | None = None


@dataclass(frozen=True, slots=True)
class GovernedMemory:
    memory_id: str
    candidate_id: str
    scope_id: str
    scope_level: MemoryScopeLevel
    memory_type: MemoryType
    polarity: MemoryPolarity
    situation_class: str
    applicability: Applicability
    intervention: Strategy
    expected_outcome: Outcome
    supporting_episode_ids: tuple[str, ...]
    producer_set: tuple[str, ...]
    positive_episode_ids: tuple[str, ...]
    negative_episode_ids: tuple[str, ...]
    confidence: float
    observed_from: datetime
    observed_to: datetime
    created_at: datetime
    recorded_at: datetime
    governance_revision: str
    semantic_embedding_space: str
    memory_class: MemoryClass
    status: MemoryStatus = MemoryStatus.ACTIVE
    expires_at: datetime | None = None
    supersedes_memory_id: str | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    similarity: float = 1.0

    def effective_confidence(self, *, now: datetime | None = None) -> float:
        """Return memory-class-aware confidence without mutating audit history."""

        horizon = self.memory_class.max_age
        if horizon is None:
            return self.confidence
        current = now or datetime.now(timezone.utc)
        age_seconds = max(0.0, (current - self.observed_to).total_seconds())
        horizon_seconds = max(1.0, horizon.total_seconds())
        # Exponential decay keeps recent evidence useful while making older
        # operational knowledge progressively less influential before expiry.
        factor = exp(-0.6931471805599453 * age_seconds / (horizon_seconds / 2.0))
        return max(0.0, min(1.0, self.confidence * factor))

    @classmethod
    def for_test(
        cls,
        *,
        memory_id: str,
        polarity: MemoryPolarity = MemoryPolarity.POSITIVE,
        intervention: Strategy = Strategy.REFRESH_PAYMENT_TOKEN,
        applicability: Applicability = Applicability(),
        confidence: float = 0.9,
        similarity: float = 0.9,
        supersedes_memory_id: str | None = None,
    ) -> "GovernedMemory":
        now = datetime.now(timezone.utc)
        return cls(
            memory_id=memory_id,
            candidate_id=f"candidate-{memory_id}",
            scope_id="team-payments",
            scope_level=MemoryScopeLevel.TEAM,
            memory_type=MemoryType.PROCEDURAL,
            polarity=polarity,
            situation_class="stale_payment_token",
            applicability=applicability,
            intervention=intervention,
            expected_outcome=(
                Outcome.SUCCESS if polarity == MemoryPolarity.POSITIVE else Outcome.FAILED
            ),
            supporting_episode_ids=(f"episode-{memory_id}",),
            producer_set=(f"producer-{memory_id}",),
            positive_episode_ids=(f"episode-{memory_id}",)
            if polarity == MemoryPolarity.POSITIVE
            else (),
            negative_episode_ids=(f"episode-{memory_id}",)
            if polarity == MemoryPolarity.AVOID
            else (),
            confidence=confidence,
            observed_from=now,
            observed_to=now,
            created_at=now,
            recorded_at=now,
            governance_revision=ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
            semantic_embedding_space="test-space",
            memory_class=MemoryClass.STRUCTURAL,
            supersedes_memory_id=supersedes_memory_id,
            similarity=similarity,
        )


@dataclass(frozen=True, slots=True)
class ConsolidationGovernanceTrace:
    input_evidence: int
    current_evidence: int
    distinct_producers: int
    positive_evidence: int
    negative_evidence: int
    rejected_evidence: int
    conflict: bool


@dataclass(frozen=True, slots=True)
class ConsolidationGovernanceResult:
    promoted: bool
    resolution: str
    reason: str
    conflict: bool = False
    memory: GovernedMemory | None = None
    trace: ConsolidationGovernanceTrace | None = None


@dataclass(frozen=True, slots=True)
class AdaptiveMemoryResolution:
    selected_strategy: Strategy | None
    resolution: str
    conflict: bool
    memory_ids: tuple[str, ...] = ()
    producer_agent_ids: tuple[str, ...] = ()
    vetoed_strategies: tuple[Strategy, ...] = ()
    candidate_count: int = 0
    applicable_count: int = 0
    rejected_count: int = 0


@dataclass(frozen=True, slots=True)
class StrategyEffectivenessStats:
    strategy: Strategy
    situation_class: str
    sample_count: int
    success_count: int
    failure_count: int
    independent_producer_count: int
    effectiveness: float
    confidence: float

    @classmethod
    def from_episodes(
        cls,
        episodes: Iterable[DecisionEpisode],
        *,
        strategy: Strategy,
        situation_class: str,
        now: datetime | None = None,
        recency_half_life_days: float = 30.0,
    ) -> "StrategyEffectivenessStats":
        current = now or datetime.now(timezone.utc)
        latest_by_producer: dict[str, DecisionEpisode] = {}
        for episode in episodes:
            if episode.strategy != strategy or _situation_class(episode) != situation_class:
                continue
            if not _is_evidence_active(episode):
                continue
            producer = _producer_id(episode) or episode.episode_id
            existing = latest_by_producer.get(producer)
            if existing is None or episode.observed_at > existing.observed_at:
                latest_by_producer[producer] = episode

        selected = list(latest_by_producer.values())
        success_count = sum(_qualified_success(item) for item in selected)
        failure_count = sum(_qualified_failure(item) for item in selected)
        weighted_total = 0.0
        weighted_effectiveness = 0.0
        for episode in selected:
            age_days = max(
                0.0, (current - episode.observed_at).total_seconds() / 86400.0
            )
            if recency_half_life_days <= 0:
                recency = 1.0
            else:
                recency = exp(-0.6931471805599453 * age_days / recency_half_life_days)
            weight = recency * episode.confidence
            weighted_total += weight
            weighted_effectiveness += weight * episode.effectiveness
        effectiveness = (
            weighted_effectiveness / weighted_total if weighted_total else 0.0
        )
        # Confidence is derived from independent evidence volume, never from a
        # caller-supplied aggregate. It approaches one conservatively.
        independent = len(selected)
        confidence = 0.0 if independent == 0 else independent / (independent + 2.0)
        return cls(
            strategy=strategy,
            situation_class=situation_class,
            sample_count=independent,
            success_count=success_count,
            failure_count=failure_count,
            independent_producer_count=independent,
            effectiveness=max(0.0, min(1.0, effectiveness)),
            confidence=max(0.0, min(1.0, confidence)),
        )


@dataclass(slots=True)
class MemoryConsolidator:
    """Deterministically proposes reusable knowledge from governed L1 heads.

    This class cannot promote memory. Its output is always a candidate that an
    independent `MemoryConsolidationGovernor` must validate against the current
    evidence set immediately before persistence.
    """

    default_memory_class: MemoryClass = MemoryClass.LONG_TERM

    def consolidate(
        self,
        episodes: Iterable[DecisionEpisode],
        *,
        semantic_embedding_space: str,
        scope_level: MemoryScopeLevel = MemoryScopeLevel.TEAM,
        now: datetime | None = None,
    ) -> list[ConsolidationCandidate]:
        if not semantic_embedding_space.strip():
            raise ValueError("semantic_embedding_space is required")
        current = now or datetime.now(timezone.utc)
        groups: dict[
            tuple[str, str, Strategy, Applicability], list[DecisionEpisode]
        ] = {}
        for episode in episodes:
            if not _is_evidence_active(episode):
                continue
            if not (_qualified_success(episode) or _qualified_failure(episode)):
                continue
            situation_class = _situation_class(episode)
            applicability = Applicability.from_episode(episode)
            # Pre-adaptive legacy rows remain valid L1 audit history, but are
            # never generalized into L2/L3 knowledge without explicit,
            # deterministic applicability metadata.
            if situation_class == "unclassified" or not applicability.preconditions:
                continue
            key = (
                episode.scope_id,
                situation_class,
                episode.strategy,
                applicability,
            )
            groups.setdefault(key, []).append(episode)

        candidates: list[ConsolidationCandidate] = []
        for (scope_id, situation_class, strategy, applicability), grouped in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2].value)
        ):
            grouped = sorted(grouped, key=lambda item: (item.observed_at, item.episode_id))
            positive = [item for item in grouped if _qualified_success(item)]
            negative = [item for item in grouped if _qualified_failure(item)]
            positive_producers = {_producer_id(item) or item.episode_id for item in positive}
            negative_producers = {_producer_id(item) or item.episode_id for item in negative}
            polarity = (
                MemoryPolarity.AVOID
                if len(negative_producers) > len(positive_producers)
                else MemoryPolarity.POSITIVE
            )
            producer_set = tuple(
                sorted(
                    {
                        producer
                        for item in grouped
                        if (producer := _producer_id(item))
                    }
                )
            )
            # Aggregate confidence is deliberately based on distinct producers
            # rather than raw episode count, preventing producer-crowding and
            # repeated-write confidence inflation.
            aligned_producers = (
                negative_producers if polarity == MemoryPolarity.AVOID else positive_producers
            )
            independent_confidence = (
                0.0
                if not aligned_producers
                else len(aligned_producers) / (len(aligned_producers) + 1.0)
            )
            stats = StrategyEffectivenessStats.from_episodes(
                grouped,
                strategy=strategy,
                situation_class=situation_class,
                now=current,
            )
            evidence_strength = (
                1.0 - stats.effectiveness
                if polarity == MemoryPolarity.AVOID
                else stats.effectiveness
            )
            confidence = independent_confidence * evidence_strength
            observed_from = min(item.observed_at for item in grouped)
            observed_to = max(item.observed_at for item in grouped)
            supporting_ids = tuple(item.episode_id for item in grouped)
            identity = {
                "scope_id": scope_id,
                "scope_level": scope_level.value,
                "situation_class": situation_class,
                "intervention": strategy.value,
                "polarity": polarity.value,
                "preconditions": sorted(applicability.preconditions),
                "exclusions": sorted(applicability.exclusions),
                "supporting_episode_ids": sorted(supporting_ids),
                "semantic_embedding_space": semantic_embedding_space,
                "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
            }
            digest = sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            candidate_id = str(uuid5(NAMESPACE_URL, f"decisionvault:candidate:{digest}"))
            candidates.append(
                ConsolidationCandidate(
                    candidate_id=candidate_id,
                    scope_id=scope_id,
                    scope_level=scope_level,
                    memory_type=MemoryType.PROCEDURAL,
                    polarity=polarity,
                    situation_class=situation_class,
                    applicability=applicability,
                    intervention=strategy,
                    expected_outcome=(
                        Outcome.FAILED
                        if polarity == MemoryPolarity.AVOID
                        else Outcome.SUCCESS
                    ),
                    supporting_episode_ids=supporting_ids,
                    producer_set=producer_set,
                    positive_episode_ids=tuple(item.episode_id for item in positive),
                    negative_episode_ids=tuple(item.episode_id for item in negative),
                    confidence=confidence,
                    observed_from=observed_from,
                    observed_to=observed_to,
                    created_at=current,
                    recorded_at=current,
                    governance_revision=ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
                    semantic_embedding_space=semantic_embedding_space,
                    memory_class=self.default_memory_class,
                )
            )
        return candidates


@dataclass(slots=True)
class MemoryConsolidationGovernor:
    """Independent deterministic promotion gate for consolidation candidates."""

    require_zero_independent_contradictions: bool = True

    def evaluate(
        self,
        candidate: ConsolidationCandidate,
        *,
        current_episodes: Iterable[DecisionEpisode],
        current_semantic_embedding_space: str,
        active_producer_agent_ids: set[str] | frozenset[str] | None = None,
        llm_proposal: LLMPatternProposal | None = None,
        now: datetime | None = None,
    ) -> ConsolidationGovernanceResult:
        current = now or datetime.now(timezone.utc)
        episodes = list(current_episodes)
        by_id = {item.episode_id: item for item in episodes}
        supported: list[DecisionEpisode] = []
        for episode_id in candidate.supporting_episode_ids:
            episode = by_id.get(episode_id)
            if episode is None or episode.scope_id != candidate.scope_id:
                return self._reject(
                    candidate,
                    "EVIDENCE_NOT_CURRENT",
                    "candidate support is absent from the current governed evidence set",
                    episodes,
                )
            supported.append(episode)

        if candidate.governance_revision != ADAPTIVE_MEMORY_GOVERNANCE_REVISION:
            return self._reject(
                candidate,
                "GOVERNANCE_REVISION_MISMATCH",
                "candidate governance revision is not current",
                episodes,
            )
        if candidate.semantic_embedding_space != current_semantic_embedding_space:
            return self._reject(
                candidate,
                "EMBEDDING_REVISION_MISMATCH",
                "candidate embedding generation is not current",
                episodes,
            )
        evidence_spaces = {_episode_semantic_space(item) for item in supported}
        evidence_spaces.discard("")
        if evidence_spaces and evidence_spaces != {current_semantic_embedding_space}:
            return self._reject(
                candidate,
                "EMBEDDING_REVISION_MISMATCH",
                "supporting evidence spans incompatible embedding revisions",
                episodes,
            )
        if any(not _is_evidence_active(item) for item in supported):
            return self._reject(
                candidate,
                "EVIDENCE_NOT_CURRENT",
                "revoked or inactive evidence cannot support consolidation",
                episodes,
            )

        # Current-head proof: if a current episode explicitly supersedes any
        # support item then that support cannot be used, even when the stale row
        # is still present in immutable L1 history.
        superseded_ids = {
            str(item.evidence.get("supersedes_episode_id", "")).strip()
            for item in episodes
            if str(item.evidence.get("supersedes_episode_id", "")).strip()
        }
        if superseded_ids.intersection(candidate.supporting_episode_ids):
            return self._reject(
                candidate,
                "EVIDENCE_NOT_CURRENT",
                "superseded evidence cannot continue supporting promoted memory",
                episodes,
            )

        producers = {_producer_id(item) for item in supported if _producer_id(item)}
        if active_producer_agent_ids is not None:
            active = {item.strip() for item in active_producer_agent_ids if item.strip()}
            if not producers.issubset(active):
                return self._reject(
                    candidate,
                    "UNTRUSTED_PRODUCER_EVIDENCE",
                    "revoked or retired producers cannot participate in consolidation",
                    episodes,
                )
        if len(producers) < candidate.scope_level.minimum_distinct_producers:
            return self._reject(
                candidate,
                "INSUFFICIENT_DISTINCT_PRODUCERS",
                "promotion requires independent producers rather than repeated writes",
                episodes,
            )

        max_age = candidate.memory_class.max_age
        if max_age is not None:
            cutoff = current - max_age
            if any(item.observed_at < cutoff for item in supported):
                return self._reject(
                    candidate,
                    "EVIDENCE_EXPIRED",
                    "supporting evidence crosses the memory-class freshness horizon",
                    episodes,
                )

        positive_producers = {
            _producer_id(item) or item.episode_id
            for item in supported
            if _qualified_success(item)
        }
        negative_producers = {
            _producer_id(item) or item.episode_id
            for item in supported
            if _qualified_failure(item)
        }
        contradiction = bool(positive_producers and negative_producers)
        if self.require_zero_independent_contradictions and contradiction:
            return self._reject(
                candidate,
                "CONTRADICTION_ABSTAIN",
                "independent qualified evidence contradicts the proposed reusable rule",
                episodes,
                conflict=True,
            )

        aligned = (
            negative_producers
            if candidate.polarity == MemoryPolarity.AVOID
            else positive_producers
        )
        if len(aligned) < candidate.scope_level.minimum_distinct_producers:
            return self._reject(
                candidate,
                "INSUFFICIENT_DISTINCT_PRODUCERS",
                "the proposed polarity lacks enough independent supporting producers",
                episodes,
            )

        # The model may suggest wording/patterns, but every authority-bearing
        # field must exactly match the deterministic evidence-derived candidate.
        if llm_proposal is not None and not self._proposal_matches(candidate, llm_proposal):
            return self._reject(
                candidate,
                "LLM_PROPOSAL_EVIDENCE_MISMATCH",
                "model proposal disagrees with deterministic evidence-derived fields",
                episodes,
            )

        memory_id = str(
            uuid5(
                NAMESPACE_URL,
                f"decisionvault:memory:{candidate.candidate_id}:{candidate.governance_revision}",
            )
        )
        expires_at = (
            None
            if candidate.memory_class.max_age is None
            else candidate.observed_to + candidate.memory_class.max_age
        )
        memory = GovernedMemory(
            memory_id=memory_id,
            candidate_id=candidate.candidate_id,
            scope_id=candidate.scope_id,
            scope_level=candidate.scope_level,
            memory_type=candidate.memory_type,
            polarity=candidate.polarity,
            situation_class=candidate.situation_class,
            applicability=candidate.applicability,
            intervention=candidate.intervention,
            expected_outcome=candidate.expected_outcome,
            supporting_episode_ids=candidate.supporting_episode_ids,
            producer_set=tuple(sorted(producers)),
            positive_episode_ids=candidate.positive_episode_ids,
            negative_episode_ids=candidate.negative_episode_ids,
            confidence=candidate.confidence,
            observed_from=candidate.observed_from,
            observed_to=candidate.observed_to,
            created_at=candidate.created_at,
            recorded_at=current,
            governance_revision=candidate.governance_revision,
            semantic_embedding_space=candidate.semantic_embedding_space,
            memory_class=candidate.memory_class,
            status=MemoryStatus.ACTIVE,
            expires_at=expires_at,
            supersedes_memory_id=candidate.supersedes_memory_id,
        )
        return ConsolidationGovernanceResult(
            promoted=True,
            resolution="PROMOTED",
            reason="candidate passed deterministic evidence and governance validation",
            conflict=False,
            memory=memory,
            trace=self._trace(candidate, episodes, conflict=False),
        )

    @staticmethod
    def can_supersede(
        existing: GovernedMemory, candidate: ConsolidationCandidate
    ) -> bool:
        if existing.status != MemoryStatus.ACTIVE:
            return False
        if existing.scope_id != candidate.scope_id:
            return False
        if existing.situation_class != candidate.situation_class:
            return False
        if existing.intervention != candidate.intervention:
            return False
        if existing.applicability != candidate.applicability:
            return False
        if existing.semantic_embedding_space != candidate.semantic_embedding_space:
            return False
        return candidate.observed_to > existing.observed_to

    @staticmethod
    def validate_lineage(
        memory: GovernedMemory, *, existing: Mapping[str, GovernedMemory]
    ) -> bool:
        target = memory.supersedes_memory_id
        if target is None:
            return True
        if target == memory.memory_id or target not in existing:
            return False
        # A supersession target may have only one child, preventing forks.
        if any(
            item.memory_id != memory.memory_id
            and item.supersedes_memory_id == target
            for item in existing.values()
        ):
            return False
        seen = {memory.memory_id}
        cursor: str | None = target
        while cursor is not None:
            if cursor in seen:
                return False
            seen.add(cursor)
            parent = existing.get(cursor)
            if parent is None:
                return False
            cursor = parent.supersedes_memory_id
        return True

    @staticmethod
    def _proposal_matches(
        candidate: ConsolidationCandidate, proposal: LLMPatternProposal
    ) -> bool:
        return (
            proposal.situation_class.strip().lower() == candidate.situation_class
            and proposal.intervention == candidate.intervention
            and proposal.preconditions == candidate.applicability.preconditions
            and proposal.exclusions == candidate.applicability.exclusions
        )

    def _reject(
        self,
        candidate: ConsolidationCandidate,
        resolution: str,
        reason: str,
        episodes: list[DecisionEpisode],
        *,
        conflict: bool = False,
    ) -> ConsolidationGovernanceResult:
        return ConsolidationGovernanceResult(
            promoted=False,
            resolution=resolution,
            reason=reason,
            conflict=conflict,
            memory=None,
            trace=self._trace(candidate, episodes, conflict=conflict),
        )

    @staticmethod
    def _trace(
        candidate: ConsolidationCandidate,
        episodes: list[DecisionEpisode],
        *,
        conflict: bool,
    ) -> ConsolidationGovernanceTrace:
        current_ids = {item.episode_id for item in episodes}
        supported = [
            item for item in episodes if item.episode_id in candidate.supporting_episode_ids
        ]
        return ConsolidationGovernanceTrace(
            input_evidence=len(candidate.supporting_episode_ids),
            current_evidence=len(supported),
            distinct_producers=len(
                {_producer_id(item) for item in supported if _producer_id(item)}
            ),
            positive_evidence=sum(_qualified_success(item) for item in supported),
            negative_evidence=sum(_qualified_failure(item) for item in supported),
            rejected_evidence=len(
                set(candidate.supporting_episode_ids).difference(current_ids)
            ),
            conflict=conflict,
        )


@dataclass(slots=True)
class GovernedAdaptiveMemoryResolver:
    minimum_similarity: float = 0.40
    conflict_margin: float = 0.08
    minimum_effective_confidence: float = PRODUCTION_ADAPTIVE_MIN_EFFECTIVE_CONFIDENCE

    def resolve(
        self,
        memories: Iterable[GovernedMemory],
        *,
        context_tags: set[str] | frozenset[str],
        now: datetime | None = None,
    ) -> AdaptiveMemoryResolution:
        current = now or datetime.now(timezone.utc)
        candidates = list(memories)
        applicable = [
            memory
            for memory in candidates
            if memory.status == MemoryStatus.ACTIVE
            and memory.memory_type == MemoryType.PROCEDURAL
            and memory.similarity >= self.minimum_similarity
            and (memory.expires_at is None or memory.expires_at >= current)
            and memory.effective_confidence(now=current)
            >= self.minimum_effective_confidence
            and memory.applicability.matches(context_tags)
        ]
        if not applicable:
            return AdaptiveMemoryResolution(
                selected_strategy=None,
                resolution="NO_APPLICABLE_MEMORY",
                conflict=False,
                candidate_count=len(candidates),
                applicable_count=0,
                rejected_count=len(candidates),
            )

        negative = [
            memory for memory in applicable if memory.polarity == MemoryPolarity.AVOID
        ]
        vetoed = tuple(sorted({item.intervention for item in negative}, key=lambda x: x.value))
        positive = [
            memory
            for memory in applicable
            if memory.polarity == MemoryPolarity.POSITIVE
            and memory.intervention not in vetoed
        ]
        if not positive:
            return AdaptiveMemoryResolution(
                selected_strategy=None,
                resolution="NEGATIVE_MEMORY_VETO" if vetoed else "NO_APPLICABLE_MEMORY",
                conflict=False,
                memory_ids=tuple(item.memory_id for item in negative),
                producer_agent_ids=tuple(
                    sorted({producer for item in negative for producer in item.producer_set})
                ),
                vetoed_strategies=vetoed,
                candidate_count=len(candidates),
                applicable_count=len(applicable),
                rejected_count=len(candidates) - len(applicable),
            )

        scores: dict[Strategy, float] = {}
        by_strategy: dict[Strategy, list[GovernedMemory]] = {}
        for memory in positive:
            score = memory.effective_confidence(now=current) * memory.similarity
            scores[memory.intervention] = scores.get(memory.intervention, 0.0) + score
            by_strategy.setdefault(memory.intervention, []).append(memory)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
        winner, winner_score = ranked[0]
        if len(ranked) > 1 and winner_score - ranked[1][1] < self.conflict_margin:
            return AdaptiveMemoryResolution(
                selected_strategy=None,
                resolution="ADAPTIVE_MEMORY_CONFLICT_ABSTAIN",
                conflict=True,
                memory_ids=tuple(item.memory_id for item in positive),
                producer_agent_ids=tuple(
                    sorted({producer for item in positive for producer in item.producer_set})
                ),
                vetoed_strategies=vetoed,
                candidate_count=len(candidates),
                applicable_count=len(applicable),
                rejected_count=len(candidates) - len(applicable),
            )
        selected = by_strategy[winner]
        return AdaptiveMemoryResolution(
            selected_strategy=winner,
            resolution="GOVERNED_ADAPTIVE_MEMORY",
            conflict=False,
            memory_ids=tuple(item.memory_id for item in selected),
            producer_agent_ids=tuple(
                sorted({producer for item in selected for producer in item.producer_set})
            ),
            vetoed_strategies=vetoed,
            candidate_count=len(candidates),
            applicable_count=len(applicable),
            rejected_count=len(candidates) - len(applicable),
        )


def derive_context_tags(situation: str) -> frozenset[str]:
    """Deterministic, non-LLM context tags for applicability checks.

    These tags are conservative and intentionally small. Unknown text simply
    yields fewer tags, which causes applicability to fail closed rather than
    broadening a memory rule.
    """

    text = " ".join(situation.lower().replace("_", " ").split())
    tags: set[str] = set()
    rules = {
        "card_replaced": ("replacement card", "card replaced", "reissued card"),
        "stale_token": (
            "stale token",
            "expired token",
            "old stored payment credential",
            "old credential",
            "wallet credential no longer",
        ),
        "insufficient_funds": ("insufficient funds", "not enough funds"),
        "account_blocked": ("account blocked", "account locked", "account suspended"),
        "billing_profile_mismatch": (
            "billing profile mismatch",
            "billing address mismatch",
        ),
        "transient_issuer_outage": (
            "issuer outage",
            "issuer unavailable",
            "temporary issuer failure",
        ),
    }
    for tag, phrases in rules.items():
        if any(phrase in text for phrase in phrases):
            tags.add(tag)
    return frozenset(tags)


__all__ = [
    "ADAPTIVE_MEMORY_GOVERNANCE_REVISION",
    "AdaptiveMemoryResolution",
    "Applicability",
    "ConsolidationCandidate",
    "ConsolidationGovernanceResult",
    "ConsolidationGovernanceTrace",
    "GovernedAdaptiveMemoryResolver",
    "GovernedMemory",
    "LLMPatternProposal",
    "MemoryClass",
    "MemoryConsolidationGovernor",
    "MemoryConsolidator",
    "MemoryPolarity",
    "MemoryScopeLevel",
    "MemoryStatus",
    "MemoryType",
    "StrategyEffectivenessStats",
    "WorkingMemory",
    "adaptive_rule_key",
    "derive_context_tags",
]
