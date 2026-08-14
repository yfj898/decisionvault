from __future__ import annotations

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory.inmemory import InMemoryEpisodeStore


class StaticAdvisor:
    provider_name = "test:static"

    def explain(self, **kwargs) -> str:
        return "The prior generic retry failed, so the committed refresh is grounded."


class FailingAdvisor:
    provider_name = "test:failing"

    def explain(self, **kwargs) -> str:
        raise RuntimeError("provider unavailable")


class CapturingAdvisor:
    provider_name = "test:capturing"

    def __init__(self):
        self.recalled_ids = ()

    def explain(self, **kwargs) -> str:
        self.recalled_ids = tuple(
            item.episode.episode_id for item in kwargs["recalled"]
        )
        return "The explanation only sees evidence admitted by memory governance."


class CountingAdvisor:
    provider_name = "test:counting"

    def __init__(self):
        self.calls = 0

    def explain(self, **kwargs) -> str:
        self.calls += 1
        return "This must not run for a non-executable abstention."


def _seed_failed_generic(store: InMemoryEpisodeStore, scope_id: str) -> None:
    seed_agent = DecisionAgent(memory=store)
    situation = "payment failed after card replacement and token may be stale"
    decision = seed_agent.decide(scope_id=scope_id, situation=situation)
    seed_agent.record_outcome(
        scope_id=scope_id,
        situation=situation,
        decision=decision,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )


def test_advisor_can_explain_but_cannot_change_memory_decision():
    store = InMemoryEpisodeStore()
    _seed_failed_generic(store, "scope-1")
    agent = DecisionAgent(memory=store, advisor=StaticAdvisor())

    decision = agent.decide(
        scope_id="scope-1",
        situation="payment failed again after replacing the card; token is stale",
    )

    assert decision.strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert decision.memory_influenced is True
    assert decision.model_provider == "test:static"
    assert decision.model_explanation


def test_advisor_failure_is_fail_open_for_deterministic_policy():
    store = InMemoryEpisodeStore()
    _seed_failed_generic(store, "scope-1")
    agent = DecisionAgent(memory=store, advisor=FailingAdvisor())

    decision = agent.decide(
        scope_id="scope-1",
        situation="payment failed again after replacing the card; token is stale",
    )

    assert decision.strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert decision.memory_influenced is True
    assert decision.model_provider is None
    assert decision.model_explanation is None


def test_model_metadata_defaults_to_none_for_policy_only_decision():
    decision = Decision(strategy=Strategy.GENERIC_RETRY, reason="safe default")

    assert decision.model_provider is None
    assert decision.model_explanation is None


def test_advisor_only_receives_governed_memory_evidence():
    store = InMemoryEpisodeStore()
    producer = DecisionAgent(memory=store, agent_id="observer")
    producer.record_outcome(
        scope_id="scope-1",
        situation="shipping parcel destination postal code correction",
        decision=Decision(
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            reason="irrelevant low-similarity evidence",
        ),
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
    )
    advisor = CapturingAdvisor()
    agent = DecisionAgent(memory=store, advisor=advisor, agent_id="planner")

    decision = agent.decide(
        scope_id="scope-1",
        situation="replacement card payment token is stale",
    )

    assert decision.memory_influenced is False
    assert decision.recalled_episode_ids == ()
    assert advisor.recalled_ids == ()


def test_advisor_is_not_invoked_for_conflict_abstention():
    store = InMemoryEpisodeStore()
    situation = "replacement card payment token recovery"
    for agent_id, outcome, effectiveness in (
        ("observer-success", Outcome.SUCCESS, 0.9),
        ("observer-failure", Outcome.FAILED, 0.1),
    ):
        producer = DecisionAgent(memory=store, agent_id=agent_id)
        producer.record_outcome(
            scope_id="scope-conflict",
            situation=situation,
            decision=Decision(
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                reason="conflict seed",
            ),
            outcome=outcome,
            effectiveness=effectiveness,
        )

    advisor = CountingAdvisor()
    decision = DecisionAgent(memory=store, advisor=advisor).decide(
        scope_id="scope-conflict",
        situation=situation,
    )

    assert decision.strategy is None
    assert decision.executable is False
    assert decision.memory_resolution == "CONFLICT_ABSTAIN"
    assert advisor.calls == 0
