from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from decisionvault.domain import Decision, DecisionGovernanceTrace, Outcome, Strategy
from decisionvault.execution import (
    _sign,
    decision_provenance_payload,
    issue_decision_snapshot,
    issue_external_receipt,
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


def test_keyed_receipt_survives_active_signing_key_rotation():
    old_secret = "old-execution-signing-secret-123"
    new_secret = "new-execution-signing-secret-456"
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret=old_secret,
        signing_key_id="key-1",
        now=NOW,
    )

    receipt = verify_execution_receipt(
        payload,
        signing_secret=new_secret,
        verification_secrets={"key-1": old_secret, "key-2": new_secret},
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        ttl_seconds=None,
        now=NOW + timedelta(days=30),
    )

    assert receipt.signing_key_id == "key-1"
    assert receipt.outcome == Outcome.SUCCESS


def test_legacy_keyless_receipt_survives_rotation_when_old_key_is_retained():
    old_secret = "legacy-execution-signing-secret-123"
    new_secret = "new-execution-signing-secret-456"
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret=old_secret,
        now=NOW,
    )

    receipt = verify_execution_receipt(
        payload,
        signing_secret=new_secret,
        verification_secrets={"legacy-key": old_secret, "key-2": new_secret},
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        ttl_seconds=None,
        now=NOW + timedelta(days=30),
    )

    assert receipt.signing_key_id is None


def test_keyed_receipt_never_falls_back_to_a_different_key():
    payload = issue_sandbox_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        scenario="stale_payment_token",
        signing_secret="old-execution-signing-secret-123",
        signing_key_id="retired-key",
        now=NOW,
    )

    with pytest.raises(ValueError, match="key id"):
        verify_execution_receipt(
            payload,
            signing_secret="new-execution-signing-secret-456",
            verification_secrets={"active-key": "new-execution-signing-secret-456"},
            expected_scope_id="team-a",
            expected_agent_id="executor-a",
            ttl_seconds=None,
            now=NOW,
        )


def test_external_receipt_binds_verified_side_effect_without_claiming_business_success():
    payload = issue_external_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="replacement card uses stale merchant credential",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        execution_provider="github-contents-v1",
        external_operation_id=(
            "github:yfj898/decisionvault-execution-sandbox:"
            "decisionvault-executions/example.json@blob7"
        ),
        execution_evidence={
            "verified": True,
            "object_type": "github_repository_file",
            "repository": "yfj898/decisionvault-execution-sandbox",
            "path": "decisionvault-executions/example.json",
            "blob_sha": "blob7",
        },
        outcome=Outcome.UNKNOWN,
        effectiveness=0.0,
        confidence=1.0,
        signing_secret=SECRET,
        decision_snapshot_id="00000000-0000-0000-0000-000000000123",
        decision_digest="d" * 64,
        decision_revision="governed-adaptive-memory-v2",
        decision_agent_id="planner-a",
        now=NOW,
    )
    receipt = verify_execution_receipt(
        payload,
        signing_secret=SECRET,
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        now=NOW,
    )
    assert receipt.version == 3
    assert receipt.outcome == Outcome.UNKNOWN
    assert receipt.execution_provider == "github-contents-v1"
    assert receipt.external_operation_id.endswith("@blob7")
    assert receipt.execution_evidence is not None
    assert receipt.execution_evidence["verified"] is True


def test_external_receipt_rejects_provider_tampering():
    payload = issue_external_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.GENERIC_RETRY,
        execution_provider="github-contents-v1",
        external_operation_id=(
            "github:yfj898/decisionvault-execution-sandbox:"
            "decisionvault-executions/tamper.json@blob8"
        ),
        execution_evidence={"verified": True, "issue_number": 8},
        outcome=Outcome.UNKNOWN,
        effectiveness=0.0,
        confidence=1.0,
        signing_secret=SECRET,
        decision_snapshot_id="00000000-0000-0000-0000-000000000124",
        decision_digest="e" * 64,
        decision_revision="governed-adaptive-memory-v2",
        decision_agent_id="planner-a",
        now=NOW,
    )
    payload["execution_provider"] = "attacker-controlled"
    with pytest.raises(ValueError, match="signature"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-a",
            expected_agent_id="executor-a",
            now=NOW,
        )


def test_external_receipt_issuer_rejects_claimed_business_outcome():
    with pytest.raises(ValueError, match="must not claim a business outcome"):
        issue_external_receipt(
            scope_id="team-a",
            agent_id="executor-a",
            situation="replacement card uses stale merchant credential",
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            execution_provider="github-contents-v1",
            external_operation_id=(
                "github:yfj898/decisionvault-execution-sandbox:"
                "decisionvault-executions/claimed.json@blob9"
            ),
            execution_evidence={
                "verified": True,
                "object_type": "github_repository_file",
                "repository": "yfj898/decisionvault-execution-sandbox",
                "path": "decisionvault-executions/claimed.json",
                "blob_sha": "blob9",
            },
            outcome=Outcome.SUCCESS,
            effectiveness=0.95,
            confidence=1.0,
            signing_secret=SECRET,
            decision_snapshot_id="00000000-0000-0000-0000-000000000125",
            decision_digest="f" * 64,
            decision_revision="governed-adaptive-memory-v2",
            decision_agent_id="planner-a",
            now=NOW,
        )


def test_external_receipt_verify_rejects_claimed_business_outcome():
    # Simulate a hypothetical future issuer path that forgot the UNKNOWN
    # contract: the payload is re-signed after claiming SUCCESS, so signature
    # verification passes and the v3 outcome contract must still reject it.
    payload = issue_external_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.GENERIC_RETRY,
        execution_provider="github-contents-v1",
        external_operation_id=(
            "github:yfj898/decisionvault-execution-sandbox:"
            "decisionvault-executions/handwritten.json@blob10"
        ),
        execution_evidence={"verified": True, "object_type": "github_repository_file"},
        outcome=Outcome.UNKNOWN,
        effectiveness=0.0,
        confidence=1.0,
        signing_secret=SECRET,
        decision_snapshot_id="00000000-0000-0000-0000-000000000126",
        decision_digest="a" * 64,
        decision_revision="governed-adaptive-memory-v2",
        decision_agent_id="planner-a",
        now=NOW,
    )
    payload["outcome"] = "SUCCESS"
    payload["effectiveness"] = 0.95
    payload["signature"] = _sign(payload, SECRET)
    with pytest.raises(ValueError, match="must not claim a business outcome"):
        verify_execution_receipt(
            payload,
            signing_secret=SECRET,
            expected_scope_id="team-a",
            expected_agent_id="executor-a",
            now=NOW,
        )


def test_external_receipt_verify_accepts_unclaimed_transport_success():
    payload = issue_external_receipt(
        scope_id="team-a",
        agent_id="executor-a",
        situation="issuer outage",
        strategy=Strategy.GENERIC_RETRY,
        execution_provider="github-contents-v1",
        external_operation_id=(
            "github:yfj898/decisionvault-execution-sandbox:"
            "decisionvault-executions/transport.json@blob11"
        ),
        execution_evidence={"verified": True, "object_type": "github_repository_file"},
        outcome=Outcome.UNKNOWN,
        effectiveness=0.0,
        confidence=1.0,
        signing_secret=SECRET,
        decision_snapshot_id="00000000-0000-0000-0000-000000000127",
        decision_digest="b" * 64,
        decision_revision="governed-adaptive-memory-v2",
        decision_agent_id="planner-a",
        now=NOW,
    )
    receipt = verify_execution_receipt(
        payload,
        signing_secret=SECRET,
        expected_scope_id="team-a",
        expected_agent_id="executor-a",
        now=NOW,
    )
    assert receipt.version == 3
    assert receipt.outcome == Outcome.UNKNOWN
    assert receipt.effectiveness == 0.0
