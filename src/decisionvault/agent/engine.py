from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from decisionvault.domain import Decision, DecisionEpisode, Outcome
from decisionvault.memory.base import MemoryStore
from decisionvault.agent.policy import OutcomeAwarePolicy


@dataclass(slots=True)
class DecisionAgent:
    memory: MemoryStore
    policy: OutcomeAwarePolicy = OutcomeAwarePolicy()
    memory_enabled: bool = True

    def decide(self, *, scope_id: str, situation: str) -> Decision:
        recalled = (
            self.memory.recall(scope_id=scope_id, situation=situation, limit=5)
            if self.memory_enabled
            else []
        )
        return self.policy.decide(recalled=recalled)

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
            evidence={"decision_reason": decision.reason},
            created_at=datetime.now(timezone.utc),
        )
        self.memory.save(episode)
        return episode
