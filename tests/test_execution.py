from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from decisionvault.domain import Decision, DecisionGovernanceTrace, Outcome, Strategy
from decisionvault.execution import (
    decision_provenance_payload,
    issue_decision_snapshot,
    issue_sandbox_receipt,
    verify_decision_snapshot,
    verify_execution_receipt,
)


SECRET = "test-execution-receipt-secret-123"
NOW = datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc)


def test_sandbox_receipt_binds_verified_outcome_to_agent_scope_and_strategy():
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="replacement card uses stale merchant credential",
        strategy=Strategy.GENERIC_RETRY,
        scenario="stale_payment_token",
        signing_secret=SECRET,
        now=NOW,
    )
    receipt = verify_execution_receipt(
        payload,
        signing_secret=SECRET,
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        now=NOW,
    )
    assert receipt.outcome == Outcome.FAILED
    assert receipt.effectiveness == 0.10
    assert receipt.strategy == Strategy.GENERIC_RETRY


def test_sandbox_receipt_rejects_tampering():
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="billing mismatch",
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        scenario="billing_profile_mismatch",
        signing_secret=SECRET,
        now=NOW,
    )
    payload["outcome"] = Outcome.FAILED.value
    with pytest.raises(ValueError, match="signature"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-a",
            expected_agent_id="executor-a",
            now=NOW,
        )


def test_sandbox_receipt_rejects_cross_agent_and_cross_scope_use():
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret=SECRET,
        now=NOW,
    )
    with pytest.raises(ValueError, match="scope"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-b",
            expected_agent_id="executor-a",
            now=NOW,
        )
    with pytest.raises(ValueError, match="agent"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-a",
            expected_agent_id="executor-b",
            now=NOW,
        )


def test_sandbox_receipt_expires():
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret=SECRET,
        now=NOW,
    )
    with pytest.raises(ValueError, match="expired"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-a",
            expected_agent_id="executor-a",
            now=NOW + timedelta(minutes=20),
        )


def test_signed_snapshot_and_receipt_preserve_governed_memory_provenance():
    decision = Decision(
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        reason="governed adaptive memory",
        recalled_episode_ids=("episode-a", "episode-b"),
        recalled_memory_ids=("memory-a",),
        recalled_producer_agent_ids=("agent-a", "agent-b"),
        memory_influenced=True,
        memory_resolution="GOVERNED_ADAPTIVE_MEMORY",
        governance_trace=DecisionGovernanceTrace(
            episodic_candidates=2,
            adaptive_candidates=1,
            adaptive_applicable=1,
            selected_memory_ids=("memory-a",),
        ),
    )
    provenance = decision_provenance_payload(decision)
    snapshot_payload = issue_decision_snapshot(
        scope_id="team-a",
        agent_id="planner-a",
        situation="replacement card uses stale token",
        strategy=decision.strategy,
        decision_digest="d" * 64,
        decision_provenance=provenance,
        signing_secret=SECRET,
        now=NOW,
    )
    snapshot = verify_decision_snapshot(
        snapshot_payload,
        signing_secret=SECRET,
        expected_scope_id="team-a",
        expected_situation="replacement card uses stale token",
        expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        now=NOW,
    )
    assert snapshot.decision_provenance["recalled_memory_ids"] == ["memory-a"]

    receipt_payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="replacement card uses stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret=SECRET,
        decision_snapshot_id=snapshot.snapshot_id,
        decision_digest=snapshot.decision_digest,
        decision_revision=snapshot.decision_revision,
        decision_agent_id=snapshot.agent_id,
        decision_provenance=snapshot.decision_provenance,
        now=NOW,
    )
    receipt = verify_execution_receipt(
        receipt_payload,
        signing_secret=SECRET,
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        now=NOW,
    )
    assert receipt.decision_provenance is not None
    assert receipt.decision_provenance["recalled_memory_ids"] == ["memory-a"]
    assert receipt.decision_provenance["governance_trace"]["adaptive_applicable"] == 1
