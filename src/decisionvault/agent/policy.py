from __future__ import annotations

from dataclasses import dataclass, field

from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.domain import Decision, RecalledEpisode, Strategy


@dataclass(slots=True)
class OutcomeAwarePolicy:
    """Small deterministic policy that makes the memory effect auditable."""

    resolver: ConflictAwareMemoryResolver = field(
        default_factory=ConflictAwareMemoryResolver
    )

    def decide(
        self,
        *,
        recalled: list[RecalledEpisode],
    ) -> Decision:
        resolution = self.resolver.resolve(recalled)
        if resolution.memory_influenced and resolution.selected_strategy is not None:
            return Decision(
                strategy=resolution.selected_strategy,
                reason=resolution.reason,
                recalled_episode_ids=resolution.episode_ids,
                recalled_producer_agent_ids=resolution.producer_agent_ids,
                memory_influenced=True,
                memory_resolution=resolution.resolution,
                memory_conflict=resolution.conflict,
            )
        return Decision(
            strategy=Strategy.GENERIC_RETRY,
            reason=resolution.reason,
            recalled_episode_ids=resolution.episode_ids,
            recalled_producer_agent_ids=resolution.producer_agent_ids,
            memory_influenced=False,
            memory_resolution=resolution.resolution,
            memory_conflict=resolution.conflict,
        )
