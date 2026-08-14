from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from decisionvault.adaptive_memory import (
    Applicability,
    GovernedAdaptiveMemoryResolver,
    GovernedMemory,
    LLMPatternProposal,
    MemoryClass,
    MemoryConsolidationGovernor,
    MemoryConsolidator,
    MemoryPolarity,
    MemoryScopeLevel,
    MemoryStatus,
    MemoryType,
    StrategyEffectivenessStats,
    WorkingMemory,
    adaptive_rule_key,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, DecisionEpisode, Outcome, RecalledEpisode, Strategy
from decisionvault.execution import decision_state_digest
from decisionvault.memory.consolidation import CockroachMemoryConsolidationService


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc)
SPACE_V2 = "embed|revision=v2|dim=1024|contract=query-passage-v1"
SPACE_V1 = "embed|revision=v1|dim=1024|contract=query-passage-v1"


def _episode(
    episode_id: str,
    *,
    producer: str,
    outcome: Outcome,
    strategy: Strategy = Strategy.REFRESH_PAYMENT_TOKEN,
    scope_id: str = "team-payments",
    situation_class: str = "stale_payment_token",
    observed_at: datetime = NOW,
    confidence: float = 1.0,
    effectiveness: float | None = None,
    semantic_space: str = SPACE_V2,
    status: str = "ACTIVE",
    supersedes: str | None = None,
) -> DecisionEpisode:
    if effectiveness is None:
        effectiveness = 0.95 if outcome == Outcome.SUCCESS else 0.05
    evidence = {
        "producer_agent_id": producer,
        "situation_class": situation_class,
        "preconditions": "card_replaced,stale_token",
        "exclusions": "insufficient_funds,account_blocked",
        "memory_status": status,
        "semantic_embedding_space": semantic_space,
    }
    if supersedes:
        evidence["supersedes_episode_id"] = supersedes
    return DecisionEpisode(
        episode_id=episode_id,
        scope_id=scope_id,
        situation="replacement card has an old stored payment credential",
        strategy=strategy,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=confidence,
        evidence=evidence,
        observed_at=observed_at,
        recorded_at=NOW,
    )


def _candidate(episodes: list[DecisionEpisode], **kwargs):
    candidates = MemoryConsolidator().consolidate(
        episodes,
        semantic_embedding_space=kwargs.pop("semantic_embedding_space", SPACE_V2),
        scope_level=kwargs.pop("scope_level", MemoryScopeLevel.TEAM),
        now=NOW,
    )
    assert len(candidates) == 1
    return candidates[0]


def test_single_agent_repetition_cannot_promote_team_knowledge():
    episodes = [
        _episode(f"a-{index}", producer="agent-a", outcome=Outcome.SUCCESS)
        for index in range(5)
    ]
    candidate = _candidate(episodes)
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "INSUFFICIENT_DISTINCT_PRODUCERS"


def test_three_success_and_independent_contradictory_failure_abstains():
    episodes = [
        _episode(f"s-{index}", producer=f"success-{index}", outcome=Outcome.SUCCESS)
        for index in range(3)
    ] + [_episode("failure", producer="failure-agent", outcome=Outcome.FAILED)]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.conflict is True
    assert result.resolution == "CONTRADICTION_ABSTAIN"


def test_revoked_producer_cannot_participate_in_consolidation():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        active_producer_agent_ids={"agent-a"},
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "UNTRUSTED_PRODUCER_EVIDENCE"


def test_superseded_evidence_cannot_support_long_term_memory():
    old = _episode("old", producer="agent-a", outcome=Outcome.SUCCESS)
    newer = _episode(
        "new",
        producer="agent-a",
        outcome=Outcome.SUCCESS,
        observed_at=NOW + timedelta(seconds=1),
        supersedes="old",
    )
    other = _episode("other", producer="agent-b", outcome=Outcome.SUCCESS)
    candidate = _candidate([old, other])
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=[newer, other],
        current_semantic_embedding_space=SPACE_V2,
        now=NOW + timedelta(seconds=2),
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_NOT_CURRENT"


def test_consolidation_vs_normal_write_revalidates_current_evidence():
    old = _episode("old-normal", producer="agent-a", outcome=Outcome.SUCCESS)
    other = _episode("other-normal", producer="agent-b", outcome=Outcome.SUCCESS)
    candidate = _candidate([old, other])
    replacement = _episode(
        "replacement-normal",
        producer="agent-a",
        outcome=Outcome.SUCCESS,
        observed_at=NOW + timedelta(seconds=1),
    )
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=[replacement, other],
        current_semantic_embedding_space=SPACE_V2,
        now=NOW + timedelta(seconds=2),
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_NOT_CURRENT"


def test_consolidation_vs_revocation_revalidates_current_evidence():
    first = _episode("first-revoke", producer="agent-a", outcome=Outcome.SUCCESS)
    second = _episode("second-revoke", producer="agent-b", outcome=Outcome.SUCCESS)
    candidate = _candidate([first, second])
    revoked = replace(
        first,
        evidence={**first.evidence, "memory_status": "REVOKED"},
    )
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=[revoked, second],
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_NOT_CURRENT"


def test_cross_embedding_revision_consolidation_fails_closed():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode(
            "b",
            producer="agent-b",
            outcome=Outcome.SUCCESS,
            semantic_space=SPACE_V1,
        ),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "EMBEDDING_REVISION_MISMATCH"


def test_late_event_cannot_replace_newer_knowledge_window():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS, observed_at=NOW),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS, observed_at=NOW),
    ]
    promoted = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    ).memory
    assert promoted is not None
    late = [
        _episode(
            "late-a",
            producer="agent-a",
            outcome=Outcome.SUCCESS,
            observed_at=NOW - timedelta(days=2),
        ),
        _episode(
            "late-b",
            producer="agent-b",
            outcome=Outcome.SUCCESS,
            observed_at=NOW - timedelta(days=2),
        ),
    ]
    candidate = _candidate(late)
    assert candidate.observed_to < promoted.observed_to
    assert MemoryConsolidationGovernor.can_supersede(promoted, candidate) is False


def test_different_applicability_rule_cannot_supersede_existing_memory():
    episodes = [
        _episode("app-a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("app-b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    promoted = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    ).memory
    assert promoted is not None
    candidate = replace(
        _candidate(episodes),
        applicability=Applicability(
            preconditions=frozenset({"wallet_reissued", "stale_token"}),
            exclusions=frozenset({"account_blocked"}),
        ),
        observed_to=NOW + timedelta(seconds=1),
    )
    assert MemoryConsolidationGovernor.can_supersede(promoted, candidate) is False


def test_stale_long_term_memory_cannot_be_reactivated_by_old_evidence():
    episodes = [
        _episode(
            "a",
            producer="agent-a",
            outcome=Outcome.SUCCESS,
            observed_at=NOW - timedelta(days=400),
        ),
        _episode(
            "b",
            producer="agent-b",
            outcome=Outcome.SUCCESS,
            observed_at=NOW - timedelta(days=400),
        ),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_EXPIRED"


def test_fresh_evidence_cannot_carry_expired_support_back_into_long_term_memory():
    episodes = [
        _episode(
            "stale",
            producer="agent-a",
            outcome=Outcome.SUCCESS,
            observed_at=NOW - timedelta(days=400),
        ),
        _episode(
            "fresh",
            producer="agent-b",
            outcome=Outcome.SUCCESS,
            observed_at=NOW,
        ),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_EXPIRED"


def test_negative_memory_veto_precedes_positive_ranking():
    resolver = GovernedAdaptiveMemoryResolver()
    positive = GovernedMemory.for_test(
        memory_id="positive",
        polarity=MemoryPolarity.POSITIVE,
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"stale_token"}), exclusions=frozenset()
        ),
        confidence=0.99,
    )
    negative = GovernedMemory.for_test(
        memory_id="negative",
        polarity=MemoryPolarity.AVOID,
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"stale_token"}), exclusions=frozenset()
        ),
        confidence=0.70,
    )
    result = resolver.resolve([positive, negative], context_tags={"stale_token"})
    assert result.selected_strategy is None
    assert result.vetoed_strategies == (Strategy.REFRESH_PAYMENT_TOKEN,)
    assert result.resolution == "NEGATIVE_MEMORY_VETO"


def test_high_similarity_memory_is_ignored_when_applicability_fails():
    memory = GovernedMemory.for_test(
        memory_id="m1",
        polarity=MemoryPolarity.POSITIVE,
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"card_replaced", "stale_token"}),
            exclusions=frozenset({"account_blocked"}),
        ),
        confidence=0.99,
        similarity=0.999,
    )
    result = GovernedAdaptiveMemoryResolver().resolve(
        [memory], context_tags={"stale_token", "account_blocked"}
    )
    assert result.selected_strategy is None
    assert result.resolution == "NO_APPLICABLE_MEMORY"


def test_rule_identity_is_applicability_bounded_but_not_polarity_split():
    card_rule = adaptive_rule_key(
        situation_class="stale_payment_token",
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"card_replaced", "stale_token"}),
            exclusions=frozenset({"account_blocked"}),
        ),
    )
    wallet_rule = adaptive_rule_key(
        situation_class="stale_payment_token",
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"wallet_reissued", "stale_token"}),
            exclusions=frozenset({"account_blocked"}),
        ),
    )
    same_card_rule = adaptive_rule_key(
        situation_class="stale_payment_token",
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(
            preconditions=frozenset({"stale_token", "card_replaced"}),
            exclusions=frozenset({"account_blocked"}),
        ),
    )
    assert card_rule == same_card_rule
    assert card_rule != wallet_rule


def test_consolidation_sql_bindings_include_rule_key_without_placeholder_drift():
    episodes = [
        _episode("sql-a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("sql-b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    candidate = _candidate(episodes)
    governance = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert governance.memory is not None

    class CaptureCursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            assert sql.count("%s") == len(params)
            self.calls.append((sql, params))

    cursor = CaptureCursor()
    CockroachMemoryConsolidationService._insert_candidate(cursor, candidate)
    service = CockroachMemoryConsolidationService(
        connection_factory=lambda: None,
        semantic_embedder=lambda _text: [0.0] * 1024,
        semantic_embedding_space=SPACE_V2,
    )
    service._insert_governed_memory(cursor, governance.memory)

    assert len(cursor.calls) == 2
    assert all("rule_key" in sql for sql, _params in cursor.calls)


def test_llm_pattern_proposal_must_match_evidence_derived_contract():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    candidate = _candidate(episodes)
    proposal = LLMPatternProposal(
        situation_class=candidate.situation_class,
        intervention=Strategy.VERIFY_BILLING_PROFILE,
        preconditions=candidate.applicability.preconditions,
        exclusions=candidate.applicability.exclusions,
        explanation="model proposed a different strategy",
    )
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        llm_proposal=proposal,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "LLM_PROPOSAL_EVIDENCE_MISMATCH"


def test_lineage_cycle_and_fork_are_rejected():
    base = GovernedMemory.for_test(memory_id="base")
    child = GovernedMemory.for_test(memory_id="child", supersedes_memory_id="base")
    assert MemoryConsolidationGovernor.validate_lineage(
        child, existing={"base": base}
    ) is True
    fork = GovernedMemory.for_test(memory_id="fork", supersedes_memory_id="base")
    assert MemoryConsolidationGovernor.validate_lineage(
        fork, existing={"base": base, "child": child}
    ) is False
    cycle = GovernedMemory.for_test(memory_id="base", supersedes_memory_id="child")
    assert MemoryConsolidationGovernor.validate_lineage(
        cycle, existing={"base": base, "child": child}
    ) is False


def test_confidence_is_derived_and_duplicate_producer_cannot_inflate_it():
    two_producers = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS, confidence=1.0),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS, confidence=1.0),
    ]
    crowded = two_producers + [
        _episode(f"dup-{i}", producer="agent-a", outcome=Outcome.SUCCESS, confidence=1.0)
        for i in range(20)
    ]
    assert _candidate(crowded).confidence == _candidate(two_producers).confidence


def test_cross_scope_contamination_is_rejected():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    candidate = _candidate(episodes)
    contaminated = [episodes[0], _episode("foreign", producer="agent-b", outcome=Outcome.SUCCESS, scope_id="other")]
    result = MemoryConsolidationGovernor().evaluate(
        candidate,
        current_episodes=contaminated,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "EVIDENCE_NOT_CURRENT"


def test_strategy_effectiveness_counts_independent_producers_and_recency():
    episodes = [
        _episode("a1", producer="agent-a", outcome=Outcome.SUCCESS, observed_at=NOW),
        _episode("a2", producer="agent-a", outcome=Outcome.SUCCESS, observed_at=NOW - timedelta(days=1)),
        _episode("b", producer="agent-b", outcome=Outcome.FAILED, observed_at=NOW - timedelta(days=10)),
    ]
    stats = StrategyEffectivenessStats.from_episodes(
        episodes,
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        situation_class="stale_payment_token",
        now=NOW,
    )
    assert stats.sample_count == 2
    assert stats.independent_producer_count == 2
    assert stats.success_count == 1
    assert stats.failure_count == 1
    assert 0.0 <= stats.effectiveness <= 1.0
    assert 0.0 <= stats.confidence <= 1.0


def test_memory_class_has_non_uniform_decay_policy():
    assert MemoryClass.EPHEMERAL.max_age < MemoryClass.SHORT_TERM.max_age
    assert MemoryClass.SHORT_TERM.max_age < MemoryClass.OPERATIONAL.max_age
    assert MemoryClass.OPERATIONAL.max_age < MemoryClass.LONG_TERM.max_age
    assert MemoryClass.STRUCTURAL.max_age is None


def test_operational_memory_confidence_decays_before_expiry():
    fresh = GovernedMemory.for_test(memory_id="fresh", confidence=0.9)
    operational = replace(
        fresh,
        memory_class=MemoryClass.OPERATIONAL,
        observed_to=NOW - timedelta(days=60),
        expires_at=NOW + timedelta(days=30),
    )
    assert operational.effective_confidence(now=NOW) < operational.confidence
    assert operational.effective_confidence(now=NOW) > 0.0


def test_global_promotion_requires_three_distinct_producers():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes, scope_level=MemoryScopeLevel.GLOBAL),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "INSUFFICIENT_DISTINCT_PRODUCERS"


def test_negative_memory_requires_multiple_independent_failures():
    single = [_episode(f"f{i}", producer="agent-a", outcome=Outcome.FAILED) for i in range(4)]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(single),
        current_episodes=single,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is False
    assert result.resolution == "INSUFFICIENT_DISTINCT_PRODUCERS"


def test_promoted_memory_retains_full_episode_and_producer_provenance():
    episodes = [
        _episode("a", producer="agent-a", outcome=Outcome.SUCCESS),
        _episode("b", producer="agent-b", outcome=Outcome.SUCCESS),
    ]
    result = MemoryConsolidationGovernor().evaluate(
        _candidate(episodes),
        current_episodes=episodes,
        current_semantic_embedding_space=SPACE_V2,
        now=NOW,
    )
    assert result.promoted is True
    assert result.memory is not None
    assert result.memory.status == MemoryStatus.ACTIVE
    assert result.memory.supporting_episode_ids == ("a", "b")
    assert result.memory.producer_set == ("agent-a", "agent-b")
    assert result.memory.memory_type in {MemoryType.SEMANTIC, MemoryType.PROCEDURAL}


def test_legacy_episode_without_explicit_applicability_cannot_be_generalized():
    legacy = _episode(
        "legacy",
        producer="agent-a",
        outcome=Outcome.SUCCESS,
    )
    legacy = replace(
        legacy,
        evidence={
            "producer_agent_id": "agent-a",
            "memory_status": "ACTIVE",
            "semantic_embedding_space": SPACE_V2,
        },
    )
    assert MemoryConsolidator().consolidate(
        [legacy],
        semantic_embedding_space=SPACE_V2,
        now=NOW,
    ) == []


def test_working_memory_is_request_local_and_derives_conservative_context():
    working = WorkingMemory.from_request(
        scope_id="team-payments",
        situation="replacement card still uses a stale token",
        now=NOW,
    )
    assert working.scope_id == "team-payments"
    assert working.context_tags == frozenset({"card_replaced", "stale_token"})
    assert working.created_at == NOW


def test_semantic_l2_memory_cannot_directly_select_execution_strategy():
    procedural = GovernedMemory.for_test(memory_id="knowledge")
    semantic = replace(procedural, memory_type=MemoryType.SEMANTIC)
    resolution = GovernedAdaptiveMemoryResolver().resolve(
        [semantic], context_tags=set(semantic.applicability.preconditions)
    )
    assert resolution.selected_strategy is None
    assert resolution.resolution == "NO_APPLICABLE_MEMORY"


def test_cross_layer_disagreement_is_a_hard_abstention():
    recalled = RecalledEpisode(
        episode=_episode(
            "episodic-success",
            producer="agent-a",
            outcome=Outcome.SUCCESS,
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        ),
        similarity=0.95,
    )
    adaptive = GovernedMemory.for_test(
        memory_id="billing-rule",
        intervention=Strategy.VERIFY_BILLING_PROFILE,
        applicability=Applicability(),
    )
    decision = OutcomeAwarePolicy().decide(
        recalled=[recalled], adaptive_memories=[adaptive], context_tags=set()
    )
    assert decision.executable is False
    assert decision.memory_conflict is True
    assert decision.memory_resolution == "CROSS_LAYER_CONFLICT_ABSTAIN"


def test_negative_memory_can_veto_episodic_recommendation():
    recalled = RecalledEpisode(
        episode=_episode(
            "episodic-success",
            producer="agent-a",
            outcome=Outcome.SUCCESS,
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        ),
        similarity=0.95,
    )
    avoid = GovernedMemory.for_test(
        memory_id="avoid-refresh",
        polarity=MemoryPolarity.AVOID,
        intervention=Strategy.REFRESH_PAYMENT_TOKEN,
        applicability=Applicability(),
    )
    decision = OutcomeAwarePolicy().decide(
        recalled=[recalled], adaptive_memories=[avoid], context_tags=set()
    )
    assert decision.strategy == Strategy.GENERIC_RETRY
    assert decision.recalled_memory_ids == ("avoid-refresh",)
    assert Strategy.REFRESH_PAYMENT_TOKEN.value in decision.governance_trace.vetoed_strategies


def test_snapshot_digest_commits_selected_adaptive_memory_and_trace():
    base = Decision(strategy=Strategy.GENERIC_RETRY, reason="safe default")
    influenced = replace(
        base,
        recalled_memory_ids=("memory-a",),
        governance_trace=replace(
            base.governance_trace,
            adaptive_candidates=1,
            adaptive_applicable=1,
            selected_memory_ids=("memory-a",),
        ),
    )
    assert decision_state_digest(
        base, semantic_embedding_space=SPACE_V2
    ) != decision_state_digest(influenced, semantic_embedding_space=SPACE_V2)
