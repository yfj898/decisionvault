from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from decisionvault.domain import Decision, DecisionEpisode, Outcome
from decisionvault.memory.base import MemoryStore
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.providers.base import DecisionAdvisor


@dataclass(slots=True)
class DecisionAgent:
    memory: MemoryStore
    policy: OutcomeAwarePolicy = OutcomeAwarePolicy()
    memory_enabled: bool = True
    advisor: DecisionAdvisor | None = None
    agent_id: str = "decision-agent"

    def decide(self, *, scope_id: str, situation: str) -> Decision:
        recalled = (
            self.memory.recall(scope_id=scope_id, situation=situation, limit=5)
            if self.memory_enabled
            else []
        )
        decision = self.policy.decide(recalled=recalled)
        if self.advisor is None:
            return decision

        try:
            explanation = self.advisor.explain(
                situation=situation,
                decision=decision,
                recalled=recalled,
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
    ) -> DecisionEpisode:
        episode = DecisionEpisode(
            episode_id=str(uuid4()),
            scope_id=scope_id,
            situation=situation,
            strategy=decision.strategy,
            outcome=outcome,
            effectiveness=effectiveness,
            confidence=confidence,
            evidence={
                "decision_reason": decision.reason,
                "producer_agent_id": self.agent_id,
            },
            created_at=datetime.now(timezone.utc),
        )
        self.memory.save(episode)
        return episode
