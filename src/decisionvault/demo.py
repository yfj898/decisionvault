from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Outcome
from decisionvault.memory.inmemory import InMemoryEpisodeStore


def run() -> None:
    scope = "demo_customer"
    first_case = (
        "customer payment failed twice after replacing their card "
        "and the stored payment token may be stale"
    )
    second_case = (
        "payment failed again after the customer replaced the card; "
        "the saved token looks stale"
    )

    memory = InMemoryEpisodeStore()
    agent = DecisionAgent(memory=memory)

    first = agent.decide(scope_id=scope, situation=first_case)
    print("SESSION 1")
    print("strategy:", first.strategy.value)
    print("memory_influenced:", first.memory_influenced)
    print("reason:", first.reason)

    episode = agent.record_outcome(
        scope_id=scope,
        situation=first_case,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )
    print("stored_episode:", episode.episode_id)
    print()

    second = agent.decide(scope_id=scope, situation=second_case)
    print("SESSION 2 — MEMORY ON")
    print("strategy:", second.strategy.value)
    print("memory_influenced:", second.memory_influenced)
    print("recalled:", second.recalled_episode_ids)
    print("reason:", second.reason)
    print()

    baseline = DecisionAgent(memory=memory, memory_enabled=False)
    baseline_decision = baseline.decide(scope_id=scope, situation=second_case)
    print("SESSION 2 — MEMORY OFF BASELINE")
    print("strategy:", baseline_decision.strategy.value)
    print("memory_influenced:", baseline_decision.memory_influenced)


if __name__ == "__main__":
    run()
