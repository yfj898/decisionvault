from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from decisionvault.domain import Outcome, Strategy
from decisionvault.execution import issue_sandbox_receipt, verify_execution_receipt


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
