from __future__ import annotations

from datetime import datetime, timedelta, timezone

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import DecisionAction, DecisionEpisode, Outcome, Strategy
from decisionvault.memory.inmemory import InMemoryEpisodeStore


class RecordingStore(InMemoryEpisodeStore):
    def __init__(self):
        super().__init__()
        self.last_limit = None
        self.last_minimum_similarity = None

    def recall(self, *, scope_id: str, situation: str, limit: int = 5):
        self.last_limit = limit
        return super().recall(scope_id=scope_id, situation=situation, limit=limit)

    def recall_governed(self, *, scope_id: str, situation: str, minimum_similarity: float):
        self.last_minimum_similarity = minimum_similarity
        return super().recall_governed(
            scope_id=scope_id,
            situation=situation,
            minimum_similarity=minimum_similarity,
        )


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


def test_agent_requests_complete_governance_coverage_when_store_supports_it():
    store = RecordingStore()
    consumer = DecisionAgent(memory=store, agent_id="planner")

    consumer.decide(scope_id="shared-team", situation="payment token stale")

    assert store.last_limit is None
    assert store.last_minimum_similarity == 0.30


def test_governance_conflict_is_not_hidden_beyond_legacy_32_candidates():
    store = InMemoryEpisodeStore()
    base = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    common = "payment token stale after replacement card"

    # This contradictory FAILED observation is oldest. A legacy top-32 ordered
    # by similarity/recency would drop it after 32 newer heads arrive.
    store.save(
        DecisionEpisode(
            episode_id="00000000-0000-0000-0000-000000000001",
            scope_id="shared-team",
            situation=common,
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            confidence=1.0,
            evidence={"producer_agent_id": "failure-observer"},
            created_at=base,
        )
    )
    for index in range(31):
        store.save(
            DecisionEpisode(
                episode_id=f"00000000-0000-0000-0001-{index:012d}",
                scope_id="shared-team",
                situation=common,
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.UNKNOWN,
                effectiveness=0.5,
                confidence=1.0,
                evidence={"producer_agent_id": f"neutral-{index}"},
                created_at=base + timedelta(seconds=index + 1),
            )
        )
    store.save(
        DecisionEpisode(
            episode_id="00000000-0000-0000-0000-000000000099",
            scope_id="shared-team",
            situation=common,
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            outcome=Outcome.SUCCESS,
            effectiveness=0.9,
            confidence=1.0,
            evidence={"producer_agent_id": "success-observer"},
            created_at=base + timedelta(seconds=40),
        )
    )

    decision = DecisionAgent(memory=store, agent_id="planner").decide(
        scope_id="shared-team",
        situation=common,
    )

    assert decision.strategy is None
    assert decision.action == DecisionAction.ABSTAIN
    assert decision.memory_conflict is True
    assert decision.memory_resolution == "CONFLICT_ABSTAIN"
