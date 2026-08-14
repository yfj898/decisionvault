from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from decisionvault.adaptive_memory import WorkingMemory
from decisionvault.domain import Decision, DecisionAction, DecisionEpisode, Outcome
from decisionvault.memory.base import MemoryStore
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.providers.base import DecisionAdvisor


GOVERNANCE_ANN_CANDIDATE_HINT = 32


@dataclass(slots=True)
class DecisionAgent:
    memory: MemoryStore
    policy: OutcomeAwarePolicy = field(default_factory=OutcomeAwarePolicy)
    memory_enabled: bool = True
    advisor: DecisionAdvisor | None = None
    agent_id: str = "decision-agent"

    def decide(self, *, scope_id: str, situation: str) -> Decision:
        working = WorkingMemory.from_request(scope_id=scope_id, situation=situation)
        recalled: list = []
        adaptive_memories: list = []
        if self.memory_enabled:
            governed_recall = getattr(self.memory, "recall_governed", None)
            if callable(governed_recall):
                recalled = governed_recall(
                    scope_id=scope_id,
                    situation=situation,
                    minimum_similarity=self.policy.resolver.minimum_similarity,
                )
            else:
                # Compatibility fallback for third-party stores that have not
                # implemented the governed coverage contract yet. Production
                # stores implement recall_governed, so correctness there is not
                # bounded by this ANN hint.
                recalled = self.memory.recall(
                    scope_id=scope_id,
                    situation=situation,
                    limit=GOVERNANCE_ANN_CANDIDATE_HINT,
                )
            recall_adaptive = getattr(self.memory, "recall_adaptive", None)
            if callable(recall_adaptive):
                adaptive_memories = recall_adaptive(
                    scope_id=scope_id,
                    situation=situation,
                    minimum_similarity=self.policy.adaptive_resolver.minimum_similarity,
                )
        decision = self.policy.decide(
            recalled=recalled,
            adaptive_memories=adaptive_memories,
            context_tags=working.context_tags,
        )
        if self.advisor is None or decision.action == DecisionAction.ABSTAIN:
            return decision

        governed_episode_ids = set(decision.recalled_episode_ids)
        governed_recalled = [
            item
            for item in recalled
            if item.episode.episode_id in governed_episode_ids
        ]

        try:
            explanation = self.advisor.explain(
                situation=situation,
                decision=decision,
                recalled=governed_recalled,
            ).strip()
        except Exception:
            # The model is explicitly non-authoritative. Provider failures must
            # never change or block the deterministic memory-based decision.
            return decision

        if not explanation:
            return decision
        return replace(
            decision,
            model_explanation=explanation,
            model_provider=self.advisor.provider_name,
        )

    def record_outcome(
        self,
        *,
        scope_id: str,
        situation: str,
        decision: Decision,
        outcome: Outcome,
        effectiveness: float,
        confidence: float = 1.0,
        evidence: Mapping[str, str] | None = None,
        observed_at: datetime | None = None,
    ) -> DecisionEpisode:
        if not decision.executable or decision.strategy is None:
            raise ValueError("cannot record an outcome for a non-executable decision")
        episode_evidence = dict(evidence or {})
        episode_evidence.update(
            {
                "decision_reason": decision.reason,
                "producer_agent_id": self.agent_id,
            }
        )
        recorded_at = datetime.now(timezone.utc)
        episode = DecisionEpisode(
            episode_id=str(uuid4()),
            scope_id=scope_id,
            situation=situation,
            strategy=decision.strategy,
            outcome=outcome,
            effectiveness=effectiveness,
            confidence=confidence,
            evidence=episode_evidence,
            observed_at=(observed_at or recorded_at),
            recorded_at=recorded_at,
        )
        self.memory.save(episode)
        return episode
