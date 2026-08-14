from __future__ import annotations

from datetime import datetime, timedelta, timezone

from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import DecisionEpisode, Outcome, RecalledEpisode, Strategy


NOW = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)


def _memory(
    episode_id: str,
    *,
    producer: str,
    strategy: Strategy,
    outcome: Outcome,
    effectiveness: float,
    confidence: float = 1.0,
    similarity: float = 0.8,
    age_days: float = 0.0,
    extra: dict[str, str] | None = None,
) -> RecalledEpisode:
    evidence = {"producer_agent_id": producer, **(extra or {})}
    return RecalledEpisode(
        episode=DecisionEpisode(
            episode_id=episode_id,
            scope_id="team-scope",
            situation="payment recovery context",
            strategy=strategy,
            outcome=outcome,
            effectiveness=effectiveness,
            confidence=confidence,
            evidence=evidence,
            created_at=NOW - timedelta(days=age_days),
        ),
        similarity=similarity,
    )


def test_balanced_cross_agent_contradiction_abstains():
    result = ConflictAwareMemoryResolver().resolve(
        [
            _memory(
                "success-a",
                producer="agent-a",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
            _memory(
                "failure-b",
                producer="agent-b",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.FAILED,
                effectiveness=0.1,
            ),
        ],
        now=NOW,
    )
    assert result.memory_influenced is False
    assert result.selected_strategy is None
    assert result.conflict is True
    assert result.resolution == "CONFLICT_ABSTAIN"


def test_explicit_producer_trust_can_resolve_conflict_without_hiding_it():
    resolver = ConflictAwareMemoryResolver(
        producer_trust={"agent-a": 1.0, "agent-b": 0.05}
    )
    result = resolver.resolve(
        [
            _memory(
                "success-a",
                producer="agent-a",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
            _memory(
                "failure-b",
                producer="agent-b",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.FAILED,
                effectiveness=0.1,
            ),
        ],
        now=NOW,
    )
    assert result.selected_strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert result.memory_influenced is True
    assert result.conflict is True
    assert result.resolution == "RESOLVED_CONFLICT"


def test_stale_memory_does_not_propagate():
    result = ConflictAwareMemoryResolver(max_age_days=90).resolve(
        [
            _memory(
                "stale",
                producer="agent-a",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.95,
                age_days=120,
            )
        ],
        now=NOW,
    )
    assert result.memory_influenced is False
    assert result.resolution == "NO_SIGNAL"


def test_supersession_removes_obsolete_memory_from_resolution():
    result = ConflictAwareMemoryResolver().resolve(
        [
            _memory(
                "old-billing",
                producer="agent-a",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.95,
                age_days=2,
            ),
            _memory(
                "new-refresh",
                producer="agent-a",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.SUCCESS,
                effectiveness=0.95,
                age_days=1,
                extra={"supersedes_episode_id": "old-billing"},
            ),
        ],
        now=NOW,
    )
    assert result.selected_strategy == Strategy.REFRESH_PAYMENT_TOKEN
    assert result.episode_ids == ("new-refresh",)


def test_duplicate_writes_from_one_producer_do_not_outvote_another_agent():
    duplicates = [
        _memory(
            f"dup-{index}",
            producer="agent-a",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.SUCCESS,
            effectiveness=0.9,
            age_days=float(5 - index) / 10.0,
        )
        for index in range(5)
    ]
    conflict = _memory(
        "failure-b",
        producer="agent-b",
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )
    result = ConflictAwareMemoryResolver().resolve(
        [*duplicates, conflict],
        now=NOW,
    )
    assert result.memory_influenced is False
    assert result.conflict is True


def test_competing_successful_strategies_abstain_when_evidence_is_tied():
    result = ConflictAwareMemoryResolver().resolve(
        [
            _memory(
                "refresh-success",
                producer="agent-a",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
            _memory(
                "billing-success",
                producer="agent-b",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
        ],
        now=NOW,
    )
    assert result.selected_strategy is None
    assert result.memory_influenced is False
    assert result.conflict is True


def test_policy_surfaces_conflict_abstention_as_safe_default():
    policy = OutcomeAwarePolicy(resolver=ConflictAwareMemoryResolver())
    decision = policy.decide(
        recalled=[
            _memory(
                "refresh-success",
                producer="agent-a",
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
            _memory(
                "billing-success",
                producer="agent-b",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
            ),
        ]
    )
    assert decision.strategy == Strategy.GENERIC_RETRY
    assert decision.memory_influenced is False
    assert decision.memory_conflict is True
    assert decision.memory_resolution == "CONFLICT_ABSTAIN"
