from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from decisionvault.domain import Outcome, RecalledEpisode, Strategy


@dataclass(frozen=True, slots=True)
class MemoryGovernanceResult:
    selected_strategy: Strategy | None
    memory_influenced: bool
    resolution: str
    conflict: bool
    reason: str
    episode_ids: tuple[str, ...] = ()
    producer_agent_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class ConflictAwareMemoryResolver:
    """Resolve shared outcome memory without hiding disagreement.

    The resolver applies five governance rules before memory can influence a
    decision:

    1. relevance gate;
    2. revocation / explicit supersession;
    3. staleness gate;
    4. one active vote per producer and strategy;
    5. conflict-aware aggregation with optional producer trust weights.

    A close conflict never silently picks a winner: it returns an abstention and
    lets the policy fall back to its safe default.
    """

    minimum_similarity: float = 0.30
    max_age_days: float = 90.0
    minimum_signal: float = 0.12
    conflict_margin: float = 0.08
    producer_trust: Mapping[str, float] = field(default_factory=dict)

    def resolve(
        self,
        recalled: list[RecalledEpisode],
        *,
        now: datetime | None = None,
    ) -> MemoryGovernanceResult:
        now = now or datetime.now(timezone.utc)
        active = self._active_memories(recalled, now=now)
        if not active:
            return MemoryGovernanceResult(
                selected_strategy=None,
                memory_influenced=False,
                resolution="NO_SIGNAL",
                conflict=False,
                reason="no admissible outcome memory; use safe default",
            )

        support: dict[Strategy, float] = {strategy: 0.0 for strategy in Strategy}
        opposition: dict[Strategy, float] = {strategy: 0.0 for strategy in Strategy}
        support_items: dict[Strategy, list[RecalledEpisode]] = {
            strategy: [] for strategy in Strategy
        }
        opposition_items: dict[Strategy, list[RecalledEpisode]] = {
            strategy: [] for strategy in Strategy
        }

        for item in active:
            episode = item.episode
            weight = self._base_weight(item, now=now)
            if episode.outcome == Outcome.SUCCESS and episode.effectiveness >= 0.7:
                signal = weight * episode.effectiveness
                support[episode.strategy] += signal
                support_items[episode.strategy].append(item)
            elif episode.outcome == Outcome.FAILED and episode.confidence >= 0.6:
                signal = weight * max(0.1, 1.0 - episode.effectiveness)
                opposition[episode.strategy] += signal
                opposition_items[episode.strategy].append(item)

        recommendations: dict[Strategy, float] = {}
        sources: dict[Strategy, list[RecalledEpisode]] = {}

        for strategy in Strategy:
            net = support[strategy] - opposition[strategy]
            if support[strategy] >= self.minimum_signal and net >= self.conflict_margin:
                recommendations[strategy] = recommendations.get(strategy, 0.0) + net
                sources.setdefault(strategy, []).extend(support_items[strategy])

        generic_negative = opposition[Strategy.GENERIC_RETRY] - support[
            Strategy.GENERIC_RETRY
        ]
        if (
            opposition[Strategy.GENERIC_RETRY] >= self.minimum_signal
            and generic_negative >= self.conflict_margin
        ):
            target = Strategy.REFRESH_PAYMENT_TOKEN
            recommendations[target] = recommendations.get(target, 0.0) + generic_negative
            sources.setdefault(target, []).extend(
                opposition_items[Strategy.GENERIC_RETRY]
            )

        # Conflict visibility is deliberately independent from trust weighting.
        # A low-trust producer may lose the resolution vote, but its qualified
        # contradiction must remain visible for auditability.
        contradiction_present = any(
            any(
                item.episode.strategy == strategy
                and item.episode.outcome == Outcome.SUCCESS
                and item.episode.effectiveness >= 0.7
                for item in active
            )
            and any(
                item.episode.strategy == strategy
                and item.episode.outcome == Outcome.FAILED
                and item.episode.confidence >= 0.6
                for item in active
            )
            for strategy in Strategy
        )

        if not recommendations:
            return self._abstain(
                active,
                conflict=contradiction_present,
                reason=(
                    "shared memories conflict or are too weak to justify a strategy change"
                    if contradiction_present
                    else "no governed memory signal is strong enough; use safe default"
                ),
            )

        ranked = sorted(recommendations.items(), key=lambda item: item[1], reverse=True)
        winner, winner_score = ranked[0]
        competing = len(ranked) > 1 and (winner_score - ranked[1][1]) < self.conflict_margin
        if competing:
            return self._abstain(
                active,
                conflict=True,
                reason=(
                    "multiple strategies have similarly strong shared-memory evidence; "
                    "abstain to safe default"
                ),
            )

        winning_items = self._unique_items(sources.get(winner, []))
        episode_ids = tuple(item.episode.episode_id for item in winning_items)
        producer_ids = self._producer_ids(winning_items)
        conflict = contradiction_present or len(ranked) > 1
        resolution = "RESOLVED_CONFLICT" if conflict else "GOVERNED_MEMORY"
        return MemoryGovernanceResult(
            selected_strategy=winner,
            memory_influenced=True,
            resolution=resolution,
            conflict=conflict,
            reason=(
                f"governed shared memory selected {winner.value} from "
                f"{len(winning_items)} provenance-aware evidence item(s)"
            ),
            episode_ids=episode_ids,
            producer_agent_ids=producer_ids,
        )

    def _active_memories(
        self,
        recalled: list[RecalledEpisode],
        *,
        now: datetime,
    ) -> list[RecalledEpisode]:
        relevant = [
            item
            for item in recalled
            if item.similarity >= self.minimum_similarity
            and str(item.episode.evidence.get("memory_status", "ACTIVE")).upper()
            != "REVOKED"
        ]
        superseded_ids = {
            str(item.episode.evidence.get("supersedes_episode_id", "")).strip()
            for item in relevant
            if str(item.episode.evidence.get("supersedes_episode_id", "")).strip()
        }
        relevant = [
            item for item in relevant if item.episode.episode_id not in superseded_ids
        ]

        fresh: list[RecalledEpisode] = []
        for item in relevant:
            pinned = str(item.episode.evidence.get("pinned", "false")).lower() == "true"
            age_days = max(0.0, (now - item.episode.created_at).total_seconds() / 86400.0)
            if pinned or age_days <= self.max_age_days:
                fresh.append(item)

        # Prevent one producer from dominating shared memory by repeated writes.
        # The newest active observation is the producer's current vote for a
        # strategy. Memories without provenance remain independent evidence.
        latest: dict[tuple[str, Strategy], RecalledEpisode] = {}
        for item in fresh:
            producer = self._producer_id(item)
            key = (producer or item.episode.episode_id, item.episode.strategy)
            current = latest.get(key)
            if current is None or item.episode.created_at > current.episode.created_at:
                latest[key] = item
        return list(latest.values())

    def _base_weight(self, item: RecalledEpisode, *, now: datetime) -> float:
        episode = item.episode
        age_days = max(0.0, (now - episode.created_at).total_seconds() / 86400.0)
        recency = 1.0 if self.max_age_days <= 0 else max(
            0.25, 1.0 - (age_days / self.max_age_days)
        )
        producer = self._producer_id(item)
        trust = float(self.producer_trust.get(producer, 1.0)) if producer else 1.0
        trust = max(0.0, min(1.0, trust))
        return item.similarity * episode.confidence * recency * trust

    def _abstain(
        self,
        items: list[RecalledEpisode],
        *,
        conflict: bool,
        reason: str,
    ) -> MemoryGovernanceResult:
        unique = self._unique_items(items)
        return MemoryGovernanceResult(
            selected_strategy=None,
            memory_influenced=False,
            resolution="CONFLICT_ABSTAIN" if conflict else "NO_SIGNAL",
            conflict=conflict,
            reason=reason,
            episode_ids=tuple(item.episode.episode_id for item in unique),
            producer_agent_ids=self._producer_ids(unique),
        )

    @staticmethod
    def _unique_items(items: list[RecalledEpisode]) -> list[RecalledEpisode]:
        unique: dict[str, RecalledEpisode] = {}
        for item in items:
            unique[item.episode.episode_id] = item
        return list(unique.values())

    @staticmethod
    def _producer_id(item: RecalledEpisode) -> str:
        return str(item.episode.evidence.get("producer_agent_id", "")).strip()

    def _producer_ids(self, items: list[RecalledEpisode]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                producer
                for producer in (self._producer_id(item) for item in items)
                if producer
            )
        )
