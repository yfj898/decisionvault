from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Outcome, Strategy
from decisionvault.memory.inmemory import InMemoryEpisodeStore


FIRST_CASE = (
    "customer payment failed twice after replacing their card "
    "and the stored payment token may be stale"
)

SIMILAR_CASE = (
    "payment failed again after the customer replaced the card; "
    "the saved token looks stale"
)


def test_no_memory_uses_default_strategy():
    agent = DecisionAgent(memory=InMemoryEpisodeStore())

    decision = agent.decide(scope_id="customer-1", situation=FIRST_CASE)

    assert decision.strategy == Strategy.GENERIC_RETRY
    assert decision.memory_influenced is False
    assert decision.recalled_episode_ids == ()


def test_failed_strategy_is_persisted_as_episode():
    memory = InMemoryEpisodeStore()
    agent = DecisionAgent(memory=memory)
    decision = agent.decide(scope_id="customer-1", situation=FIRST_CASE)

    episode = agent.record_outcome(
        scope_id="customer-1",
        situation=FIRST_CASE,
        decision=decision,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )

    assert memory.episodes == (episode,)
    assert episode.strategy == Strategy.GENERIC_RETRY
    assert episode.outcome == Outcome.FAILED


def test_similar_failure_memory_changes_next_decision():
    memory = InMemoryEpisodeStore()
    agent = DecisionAgent(memory=memory)
    first = agent.decide(scope_id="customer-1", situation=FIRST_CASE)
    failed = agent.record_outcome(
        scope_id="customer-1",
        situation=FIRST_CASE,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )

    second = agent.decide(scope_id="customer-1", situation=SIMILAR_CASE)

    assert second.strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert second.memory_influenced is True
    assert second.recalled_episode_ids == (failed.episode_id,)


def test_memory_disabled_baseline_repeats_default_strategy():
    memory = InMemoryEpisodeStore()
    learning_agent = DecisionAgent(memory=memory)
    first = learning_agent.decide(scope_id="customer-1", situation=FIRST_CASE)
    learning_agent.record_outcome(
        scope_id="customer-1",
        situation=FIRST_CASE,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )

    baseline = DecisionAgent(memory=memory, memory_enabled=False)
    decision = baseline.decide(scope_id="customer-1", situation=SIMILAR_CASE)

    assert decision.strategy == Strategy.GENERIC_RETRY
    assert decision.memory_influenced is False


def test_memory_is_scoped_and_does_not_leak_between_customers():
    memory = InMemoryEpisodeStore()
    agent = DecisionAgent(memory=memory)
    first = agent.decide(scope_id="customer-1", situation=FIRST_CASE)
    agent.record_outcome(
        scope_id="customer-1",
        situation=FIRST_CASE,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )

    other = agent.decide(scope_id="customer-2", situation=SIMILAR_CASE)

    assert other.strategy == Strategy.GENERIC_RETRY
    assert other.memory_influenced is False


def test_successful_memory_is_reused():
    memory = InMemoryEpisodeStore()
    agent = DecisionAgent(memory=memory)

    first = agent.decide(scope_id="customer-1", situation=FIRST_CASE)
    agent.record_outcome(
        scope_id="customer-1",
        situation=FIRST_CASE,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )
    second = agent.decide(scope_id="customer-1", situation=SIMILAR_CASE)
    successful = agent.record_outcome(
        scope_id="customer-1",
        situation=SIMILAR_CASE,
        decision=second,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
    )

    third = agent.decide(
        scope_id="customer-1",
        situation="stale payment token after a replacement card caused another payment failure",
    )

    assert third.strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert third.memory_influenced is True
    assert successful.episode_id in third.recalled_episode_ids
