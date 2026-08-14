from __future__ import annotations

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Outcome, Strategy
from decisionvault.memory.inmemory import InMemoryEpisodeStore


class RecordingStore(InMemoryEpisodeStore):
    def __init__(self):
        super().__init__()
        self.last_limit = None

    def recall(self, *, scope_id: str, situation: str, limit: int = 5):
        self.last_limit = limit
        return super().recall(scope_id=scope_id, situation=situation, limit=limit)


def test_cross_agent_outcome_memory_preserves_provenance_and_scope():
    store = InMemoryEpisodeStore()
    producer = DecisionAgent(memory=store, agent_id="recovery-observer")
    consumer = DecisionAgent(memory=store, agent_id="recovery-planner")

    situation = "payment failed after card replacement; payment token is stale"
    initial = producer.decide(scope_id="shared-team", situation=situation)
    episode = producer.record_outcome(
        scope_id="shared-team",
        situation=situation,
        decision=initial,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        confidence=1.0,
    )

    shared = consumer.decide(
        scope_id="shared-team",
        situation="payment failed again after card replacement; token is stale",
    )
    isolated = consumer.decide(
        scope_id="other-team",
        situation="payment failed again after card replacement; token is stale",
    )

    assert episode.evidence["producer_agent_id"] == "recovery-observer"
    assert shared.strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert shared.memory_influenced is True
    assert shared.recalled_producer_agent_ids == ("recovery-observer",)
    assert isolated.strategy == Strategy.GENERIC_RETRY
    assert isolated.memory_influenced is False
    assert isolated.recalled_producer_agent_ids == ()


def test_agent_overfetches_governance_candidates_beyond_legacy_top5():
    store = RecordingStore()
    consumer = DecisionAgent(memory=store, agent_id="planner")

    consumer.decide(scope_id="shared-team", situation="payment token stale")

    assert store.last_limit is not None
    assert store.last_limit >= 32
