from __future__ import annotations

from dataclasses import dataclass, field, replace

from decisionvault.adaptive_memory import (
    GovernedAdaptiveMemoryResolver,
    GovernedMemory,
)
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.domain import (
    Decision,
    DecisionAction,
    DecisionGovernanceTrace,
    RecalledEpisode,
    Strategy,
)


@dataclass(slots=True)
class OutcomeAwarePolicy:
    """Small deterministic policy that makes the memory effect auditable."""

    resolver: ConflictAwareMemoryResolver = field(
        default_factory=ConflictAwareMemoryResolver
    )
    adaptive_resolver: GovernedAdaptiveMemoryResolver = field(
        default_factory=GovernedAdaptiveMemoryResolver
    )

    def decide(
        self,
        *,
        recalled: list[RecalledEpisode],
        adaptive_memories: list[GovernedMemory] | None = None,
        context_tags: set[str] | frozenset[str] = frozenset(),
    ) -> Decision:
        resolution = self.resolver.resolve(recalled)
        adaptive = self.adaptive_resolver.resolve(
            adaptive_memories or [], context_tags=context_tags
        )
        trace = DecisionGovernanceTrace(
            episodic_candidates=len(recalled),
            adaptive_candidates=adaptive.candidate_count,
            adaptive_applicable=adaptive.applicable_count,
            adaptive_rejected=adaptive.rejected_count,
            vetoed_strategies=tuple(item.value for item in adaptive.vetoed_strategies),
            selected_episode_ids=resolution.episode_ids,
            selected_memory_ids=adaptive.memory_ids,
            conflict=resolution.conflict or adaptive.conflict,
        )

        # A hard conflict in either governed layer remains a fail-closed
        # abstention. Statistical/adaptive ranking cannot override it.
        if resolution.resolution == "CONFLICT_ABSTAIN" or adaptive.conflict:
            return Decision(
                strategy=None,
                action=DecisionAction.ABSTAIN,
                reason=(
                    resolution.reason
                    if resolution.resolution == "CONFLICT_ABSTAIN"
                    else "governed adaptive memories conflict; execution is blocked"
                ),
                recalled_episode_ids=resolution.episode_ids,
                recalled_memory_ids=adaptive.memory_ids,
                recalled_producer_agent_ids=tuple(
                    dict.fromkeys(
                        (*resolution.producer_agent_ids, *adaptive.producer_agent_ids)
                    )
                ),
                memory_influenced=False,
                memory_resolution=(
                    resolution.resolution
                    if resolution.resolution == "CONFLICT_ABSTAIN"
                    else adaptive.resolution
                ),
                memory_conflict=True,
                governance_trace=trace,
            )

        episodic_strategy = (
            resolution.selected_strategy if resolution.memory_influenced else None
        )
        if episodic_strategy in adaptive.vetoed_strategies:
            episodic_strategy = None

        if adaptive.selected_strategy is not None and episodic_strategy is not None:
            if adaptive.selected_strategy != episodic_strategy:
                return Decision(
                    strategy=None,
                    action=DecisionAction.ABSTAIN,
                    reason=(
                        "governed episodic and consolidated memory recommend different "
                        "strategies; execution is blocked"
                    ),
                    recalled_episode_ids=resolution.episode_ids,
                    recalled_memory_ids=adaptive.memory_ids,
                    recalled_producer_agent_ids=tuple(
                        dict.fromkeys(
                            (*resolution.producer_agent_ids, *adaptive.producer_agent_ids)
                        )
                    ),
                    memory_influenced=False,
                    memory_resolution="CROSS_LAYER_CONFLICT_ABSTAIN",
                    memory_conflict=True,
                    governance_trace=replace(trace, conflict=True),
                )

        selected_strategy = adaptive.selected_strategy or episodic_strategy
        if selected_strategy is not None:
            memory_ids = adaptive.memory_ids if adaptive.selected_strategy is not None else ()
            episode_ids = resolution.episode_ids if episodic_strategy is not None else ()
            producer_ids = tuple(
                dict.fromkeys(
                    (
                        *(
                            resolution.producer_agent_ids
                            if episodic_strategy is not None
                            else ()
                        ),
                        *(
                            adaptive.producer_agent_ids
                            if adaptive.selected_strategy is not None
                            else ()
                        ),
                    )
                )
            )
            return Decision(
                strategy=selected_strategy,
                reason=(
                    "governed consolidated memory selected " + selected_strategy.value
                    if adaptive.selected_strategy is not None
                    else resolution.reason
                ),
                recalled_episode_ids=episode_ids,
                recalled_memory_ids=memory_ids,
                recalled_producer_agent_ids=producer_ids,
                memory_influenced=True,
                memory_resolution=(
                    adaptive.resolution
                    if adaptive.selected_strategy is not None
                    else resolution.resolution
                ),
                memory_conflict=False,
                governance_trace=trace,
            )

        # A negative memory is a veto, not an instruction. Fall back to the
        # deterministic default only if that default itself is not vetoed.
        if Strategy.GENERIC_RETRY in adaptive.vetoed_strategies:
            return Decision(
                strategy=None,
                action=DecisionAction.ABSTAIN,
                reason="governed avoidance memory vetoes the deterministic default",
                recalled_episode_ids=resolution.episode_ids,
                recalled_memory_ids=adaptive.memory_ids,
                recalled_producer_agent_ids=tuple(
                    dict.fromkeys(
                        (*resolution.producer_agent_ids, *adaptive.producer_agent_ids)
                    )
                ),
                memory_influenced=False,
                memory_resolution="NEGATIVE_MEMORY_VETO_ABSTAIN",
                memory_conflict=False,
                governance_trace=trace,
            )

        return Decision(
            strategy=Strategy.GENERIC_RETRY,
            reason=(
                "governed avoidance memory vetoed recalled strategy; use safe default"
                if adaptive.vetoed_strategies
                else resolution.reason
            ),
            recalled_episode_ids=resolution.episode_ids,
            recalled_memory_ids=adaptive.memory_ids,
            recalled_producer_agent_ids=tuple(
                dict.fromkeys(
                    (*resolution.producer_agent_ids, *adaptive.producer_agent_ids)
                )
            ),
            memory_influenced=False,
            memory_resolution=(
                "NEGATIVE_MEMORY_VETO_FALLBACK"
                if adaptive.vetoed_strategies
                else resolution.resolution
            ),
            memory_conflict=resolution.conflict,
            governance_trace=trace,
        )
