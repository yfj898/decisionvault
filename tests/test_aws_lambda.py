from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

import decisionvault.aws_lambda as aws_lambda
from decisionvault.agent.auth import token_digest
from decisionvault.domain import Decision, DecisionAction, Strategy
from decisionvault.execution import (
    decision_state_digest,
    issue_decision_snapshot,
    issue_sandbox_receipt,
)
from decisionvault.memory.cockroach import SupersessionWriteConflict


def _configure_agent(monkeypatch, *, token="agent-token", permission="decide"):
    monkeypatch.setenv("NVIDIA_EMBED_REVISION", "test-revision-v1")
    monkeypatch.setenv(
        "EXECUTION_RECEIPT_SECRET", "test-execution-receipt-secret-123"
    )
    monkeypatch.setenv(
        "AGENT_AUTH_JSON",
        json.dumps(
            {
                token_digest(token): {
                    "agent_id": "recovery-planner",
                    "scope_prefixes": ["demo"],
                    "permissions": [permission],
                    "trust": 0.8,
                }
            }
        ),
    )
    monkeypatch.setattr(aws_lambda, "_enforce_rate_limit", lambda **_kwargs: None)
    return token


def _configure_executor(monkeypatch, *, token="executor-token"):
    monkeypatch.setenv("NVIDIA_EMBED_REVISION", "test-revision-v1")
    monkeypatch.setenv(
        "AGENT_AUTH_JSON",
        json.dumps(
            {
                token_digest(token): {
                    "agent_id": "recovery-observer-api",
                    "scope_prefixes": ["demo"],
                    "permissions": ["execute", "record"],
                    "trust": 0.8,
                }
            }
        ),
    )
    monkeypatch.setenv(
        "EXECUTION_RECEIPT_SECRET", "test-execution-receipt-secret-123"
    )
    monkeypatch.setattr(aws_lambda, "_enforce_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": _ExecutePolicyAgent(),
    )
    return token


class _ExecutePolicyAgent:
    def decide(self, *, scope_id: str, situation: str) -> Decision:
        return Decision(
            strategy=Strategy.GENERIC_RETRY,
            reason="test execution policy permits generic retry",
        )


def _decision_snapshot(
    *,
    scope_id: str = "demo",
    agent_id: str = "recovery-observer-api",
    situation: str,
    strategy: Strategy = Strategy.GENERIC_RETRY,
    decision: Decision | None = None,
) -> dict:
    committed = decision or _ExecutePolicyAgent().decide(
        scope_id=scope_id, situation=situation
    )
    digest = decision_state_digest(
        committed,
        semantic_embedding_space=(
            "nvidia/nv-embedqa-e5-v5|revision=test-revision-v1|"
            "dim=1024|contract=query-passage-v1"
        ),
    )
    return issue_decision_snapshot(
        scope_id=scope_id,
        agent_id=agent_id,
        situation=situation,
        strategy=strategy,
        decision_digest=digest,
        signing_secret="test-execution-receipt-secret-123",
    )


def test_rate_limit_response_is_429_with_retry_after(monkeypatch):
    token = _configure_agent(monkeypatch)

    def limited(**_kwargs):
        raise aws_lambda.RateLimitExceeded(17)

    monkeypatch.setattr(aws_lambda, "_enforce_rate_limit", limited)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {"scope_id": "demo", "situation": "payment failed again"}
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 429
    assert response["headers"]["retry-after"] == "17"
    assert body == {"error": "rate_limited", "retry_after_seconds": 17}


def test_atomic_supersession_write_conflict_maps_to_http_409(monkeypatch):
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(aws_lambda, "_enforce_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        aws_lambda,
        "_agent_grants",
        lambda: {
            token_digest("agent-token"): aws_lambda.AgentGrant(
                agent_id="recovery-observer",
                scope_prefixes=("demo",),
                permissions=frozenset({"record"}),
                trust=0.8,
            )
        },
    )
    monkeypatch.setattr(
        aws_lambda,
        "_record",
        lambda body, *, agent_id: (_ for _ in ()).throw(
            SupersessionWriteConflict("target changed concurrently")
        ),
    )

    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/record",
            "headers": {"X-DecisionVault-Agent-Token": "agent-token"},
            "body": json.dumps({"scope_id": "demo"}),
        },
        None,
    )

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "conflict"


class StubAgent:
    def decide(self, *, scope_id: str, situation: str) -> Decision:
        assert scope_id == "demo"
        assert situation == "payment failed again"
        return Decision(
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            reason="recalled failed retry",
            recalled_episode_ids=("episode-1",),
            recalled_producer_agent_ids=("recovery-observer",),
            memory_influenced=True,
            model_provider="nvidia:test",
            model_explanation="The prior retry failed, so refresh the token.",
        )


def test_health_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "GET"}},
            "rawPath": "/health",
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["database_configured"] is True
    assert body["nvidia_advisor_configured"] is True
    assert "postgresql://secret" not in response["body"]
    assert "secret-key" not in response["body"]


def test_root_serves_judge_ui_without_embedding_demo_token(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "do-not-embed-this")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "GET"}},
            "rawPath": "/",
        },
        None,
    )
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"].startswith("text/html")
    assert response["headers"]["x-frame-options"] == "DENY"
    assert "Memory OFF" in response["body"]
    assert "Memory ON" in response["body"]
    assert "Reproducible submission evidence" in response["body"]
    assert "semantic_embedding VECTOR(1024)" in response["body"]
    assert "semantic_embedding_space" in response["body"]
    assert "decision_memory_heads_scope_space_semantic_vec_idx" in response["body"]
    assert "action=ABSTAIN" in response["body"]
    assert "executable=false" in response["body"]
    assert "14/14" in response["body"]
    assert "do-not-embed-this" not in response["body"]


def test_decide_function_url_shape(monkeypatch):
    token = _configure_agent(monkeypatch)
    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": StubAgent(),
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {"scope_id": "demo", "situation": "payment failed again"}
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["strategy"] == "REFRESH_PAYMENT_TOKEN"
    assert body["action"] == "EXECUTE"
    assert body["executable"] is True
    assert body["memory_influenced"] is True
    assert body["model_provider"] == "nvidia:test"
    assert body["recalled_producer_agent_ids"] == ["recovery-observer"]


def test_general_decide_rejects_caller_memory_disable(monkeypatch):
    token = _configure_agent(monkeypatch)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": "payment failed again",
                    "memory_enabled": False,
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 400
    assert "server-controlled" in body["detail"]


def test_bad_request_is_bounded():
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "body": "{}",
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 400
    assert body["error"] == "bad_request"


def test_agent_routes_require_agent_token(monkeypatch):
    _configure_agent(monkeypatch)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {},
            "body": json.dumps({"scope_id": "demo", "situation": "x"}),
        },
        None,
    )
    assert response["statusCode"] == 403


def test_demo_requires_demo_token_when_configured(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "local-demo-token")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/demo",
            "headers": {},
            "body": "{}",
        },
        None,
    )
    assert response["statusCode"] == 401


def test_governance_demo_requires_demo_token_when_configured(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "local-demo-token")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/governance-demo",
            "headers": {},
            "body": "{}",
        },
        None,
    )
    assert response["statusCode"] == 401


def test_agent_routes_accept_matching_agent_token(monkeypatch):
    token = _configure_agent(monkeypatch)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": "{}",
        },
        None,
    )
    assert response["statusCode"] == 400


def test_caller_cannot_self_assert_agent_id(monkeypatch):
    token = _configure_agent(monkeypatch)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": "payment failed",
                    "agent_id": "trusted-admin",
                }
            ),
        },
        None,
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "agent_id_is_server_bound"


def test_execute_route_issues_server_signed_receipt(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "replacement card still uses stale merchant token"
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(situation=situation),
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    receipt = body["execution_receipt"]
    assert response["statusCode"] == 200
    assert receipt["agent_id"] == "recovery-observer-api"
    assert receipt["outcome"] == "FAILED"
    assert receipt["effectiveness"] == 0.1
    assert receipt["signature"]
    assert receipt["version"] == 2
    assert receipt["decision_snapshot_id"]
    assert receipt["decision_digest"]
    assert body["policy_decision"]["action"] == "EXECUTE"


def test_decider_snapshot_can_be_executed_by_separately_authorized_executor(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "planner committed payment retry for executor"
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(
                        situation=situation,
                        agent_id="recovery-planner-api",
                    ),
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    receipt = body["execution_receipt"]
    assert receipt["agent_id"] == "recovery-observer-api"
    assert receipt["decision_agent_id"] == "recovery-planner-api"
    assert body["policy_decision"]["executable"] is True


def test_execute_route_rejects_caller_controlled_scenario(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "replacement card still uses stale merchant token"
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(situation=situation),
                    "scenario": "transient_issuer_outage",
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 400
    assert "server-controlled" in body["detail"]


def test_execute_route_uses_server_configured_scenario(monkeypatch):
    token = _configure_executor(monkeypatch)
    monkeypatch.setenv("EXECUTION_SANDBOX_SCENARIO", "transient_issuer_outage")
    situation = "same caller situation"
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(situation=situation),
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["execution_receipt"]["scenario"] == "transient_issuer_outage"
    assert body["execution_receipt"]["outcome"] == "SUCCESS"


def test_execute_route_blocks_abstained_decision(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "conflicting payment recovery evidence"

    class AbstainingAgent:
        def decide(self, *, scope_id: str, situation: str) -> Decision:
            return Decision(
                strategy=None,
                action=DecisionAction.ABSTAIN,
                reason="shared memory conflict",
                memory_resolution="CONFLICT_ABSTAIN",
                memory_conflict=True,
            )

    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": AbstainingAgent(),
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(situation=situation),
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 409
    assert body["error"] == "conflict"
    assert "abstains" in body["detail"]


def test_execute_route_rejects_strategy_not_committed_by_policy(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "payment retry"
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "REFRESH_PAYMENT_TOKEN",
                    "decision_snapshot": _decision_snapshot(
                        situation=situation,
                        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    ),
                }
            ),
        },
        None,
    )
    assert response["statusCode"] == 409
    assert "does not match" in json.loads(response["body"])["detail"]


def test_record_rejects_direct_outcome_fields(monkeypatch):
    token = _configure_executor(monkeypatch)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/record",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "outcome": "SUCCESS",
                    "effectiveness": 1.0,
                }
            ),
        },
        None,
    )
    assert response["statusCode"] == 400
    assert "execution_receipt" in json.loads(response["body"])["detail"]


def test_record_returns_existing_episode_for_receipt_replay(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "stale token"
    execute = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": _decision_snapshot(situation=situation),
                }
            ),
        },
        None,
    )
    receipt = json.loads(execute["body"])["execution_receipt"]
    monkeypatch.setattr(
        aws_lambda,
        "_episode_by_receipt",
        lambda receipt_id: {
            "episode_id": "episode-existing",
            "strategy": "GENERIC_RETRY",
            "outcome": "FAILED",
            "effectiveness": 0.1,
            "producer_agent_id": "recovery-observer-api",
            "execution_receipt_id": receipt_id,
            "idempotent_replay": True,
        },
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/record",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {"scope_id": "demo", "execution_receipt": receipt}
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 201
    assert body["episode_id"] == "episode-existing"
    assert body["idempotent_replay"] is True


def test_revoke_route_requires_revoke_permission(monkeypatch):
    token = _configure_agent(monkeypatch, permission="record")
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/revoke",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "episode_id": "00000000-0000-0000-0000-000000000010",
                    "reason": "invalid observation",
                }
            ),
        },
        None,
    )
    assert response["statusCode"] == 403


def test_revoke_route_is_agent_bound_and_returns_audit_receipt(monkeypatch):
    token = _configure_agent(monkeypatch, permission="revoke")
    monkeypatch.setenv("REVOKE_AGENT_IDS", "recovery-planner")
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "_revoke",
        lambda body, *, agent_id: {
            "revocation_id": "00000000-0000-0000-0000-000000000011",
            "episode_id": body["episode_id"],
            "producer_agent_id": agent_id,
            "revoked": True,
            "idempotent_replay": False,
        },
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/revoke",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "episode_id": "00000000-0000-0000-0000-000000000010",
                    "reason": "invalid observation",
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["revoked"] is True
    assert body["producer_agent_id"] == "recovery-planner"


def test_existing_record_grant_can_revoke_only_with_server_allowlist(monkeypatch):
    token = _configure_agent(monkeypatch, permission="record")
    monkeypatch.setenv("REVOKE_AGENT_IDS", "recovery-planner")
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "_revoke",
        lambda body, *, agent_id: {
            "revocation_id": "00000000-0000-0000-0000-000000000011",
            "episode_id": body["episode_id"],
            "producer_agent_id": agent_id,
            "revoked": True,
            "idempotent_replay": False,
        },
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/revoke",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "episode_id": "00000000-0000-0000-0000-000000000010",
                    "reason": "invalid observation",
                }
            ),
        },
        None,
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["producer_agent_id"] == "recovery-planner"


def test_revoke_validates_uuid_and_reason_before_store_call(monkeypatch):
    class UnexpectedStore:
        def revoke_current_head(self, **_kwargs):
            raise AssertionError("store should not be called")

    monkeypatch.setattr(aws_lambda, "_build_memory_store", lambda: UnexpectedStore())
    try:
        aws_lambda._revoke(
            {"scope_id": "demo", "episode_id": "not-a-uuid", "reason": "bad"},
            agent_id="agent-a",
        )
    except ValueError as exc:
        assert "valid UUID" in str(exc)
    else:
        raise AssertionError("invalid revoke UUID should fail")


def test_execute_removes_advisor_from_critical_path(monkeypatch):
    class AgentWithAdvisor:
        def __init__(self):
            self.advisor = object()

        def decide(self, *, scope_id: str, situation: str) -> Decision:
            assert self.advisor is None
            return Decision(
                strategy=Strategy.GENERIC_RETRY,
                reason="advisor-free execution policy",
            )

    monkeypatch.setenv(
        "EXECUTION_RECEIPT_SECRET", "test-execution-receipt-secret-123"
    )
    monkeypatch.setenv("NVIDIA_EMBED_REVISION", "test-revision-v1")
    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": AgentWithAdvisor(),
    )
    situation = "payment retry"
    payload = aws_lambda._execute(
        {
            "scope_id": "demo",
            "situation": situation,
            "strategy": "GENERIC_RETRY",
            "decision_snapshot": _decision_snapshot(
                situation=situation,
                agent_id="executor-a",
            ),
        },
        agent_id="executor-a",
    )
    assert payload["execution_receipt"]["strategy"] == "GENERIC_RETRY"


def test_execute_rejects_stale_decision_snapshot_without_receipt(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "payment retry after memory changed"
    snapshot = _decision_snapshot(situation=situation)

    class ChangedDecisionAgent:
        def decide(self, *, scope_id: str, situation: str) -> Decision:
            return Decision(
                strategy=Strategy.GENERIC_RETRY,
                reason="same strategy but newer governed evidence",
                recalled_episode_ids=("newer-episode",),
                recalled_producer_agent_ids=("newer-observer",),
                memory_influenced=True,
                memory_resolution="FAILED_STRATEGY_AVOIDANCE",
            )

    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": ChangedDecisionAgent(),
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/execute",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": situation,
                    "strategy": "GENERIC_RETRY",
                    "decision_snapshot": snapshot,
                }
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 409
    assert body["error"] == "conflict"
    assert "stale" in body["detail"]
    assert "execution_receipt" not in body


def test_execute_replay_of_same_snapshot_has_stable_receipt_id(monkeypatch):
    token = _configure_executor(monkeypatch)
    situation = "stable snapshot replay"
    snapshot = _decision_snapshot(situation=situation)
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "rawPath": "/execute",
        "headers": {"X-DecisionVault-Agent-Token": token},
        "body": json.dumps(
            {
                "scope_id": "demo",
                "situation": situation,
                "strategy": "GENERIC_RETRY",
                "decision_snapshot": snapshot,
            }
        ),
    }
    first = json.loads(aws_lambda.lambda_handler(event, None)["body"])
    second = json.loads(aws_lambda.lambda_handler(event, None)["body"])
    assert first["execution_receipt"]["receipt_id"] == second["execution_receipt"]["receipt_id"]


def test_lambda_provider_timeouts_leave_platform_deadline_margin(monkeypatch):
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "20")
    assert aws_lambda._semantic_runtime_timeout() == 12.0
    assert aws_lambda._advisor_runtime_timeout() == 5.0

    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "3")
    assert aws_lambda._semantic_runtime_timeout() == 3.0
    assert aws_lambda._advisor_runtime_timeout() == 3.0

    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "0")
    with pytest.raises(RuntimeError, match="must be positive"):
        aws_lambda._semantic_runtime_timeout()


def test_request_body_and_situation_limits_fail_closed(monkeypatch):
    token = _configure_agent(monkeypatch)
    too_long = "x" * (aws_lambda.MAX_SITUATION_CHARS + 1)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps({"scope_id": "demo", "situation": too_long}),
        },
        None,
    )
    assert response["statusCode"] == 400

    huge = "x" * (aws_lambda.MAX_REQUEST_BODY_BYTES + 1)
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "body": huge,
        },
        None,
    )
    assert response["statusCode"] == 400


def test_record_replay_remains_idempotent_after_receipt_ttl(monkeypatch):
    secret = "test-execution-receipt-secret-123"
    monkeypatch.setenv("EXECUTION_RECEIPT_SECRET", secret)
    receipt = issue_sandbox_receipt(
        scope_id="demo",
        agent_id="executor-a",
        situation="stale token",
        strategy=Strategy.GENERIC_RETRY,
        scenario="stale_payment_token",
        signing_secret=secret,
        now=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    monkeypatch.setattr(
        aws_lambda,
        "_episode_by_receipt",
        lambda receipt_id: {
            "episode_id": "episode-existing",
            "strategy": "GENERIC_RETRY",
            "outcome": "FAILED",
            "effectiveness": 0.1,
            "producer_agent_id": "executor-a",
            "execution_receipt_id": receipt_id,
            "idempotent_replay": True,
        },
    )
    result = aws_lambda._record(
        {"scope_id": "demo", "execution_receipt": receipt},
        agent_id="executor-a",
    )
    assert result["episode_id"] == "episode-existing"
    assert result["idempotent_replay"] is True


def test_security_reconciliation_retires_absent_producers(monkeypatch):
    class Store:
        def __init__(self):
            self.calls = []

        def retire_untrusted_heads(self, **kwargs):
            self.calls.append(kwargs)
            return type("Retirement", (), {"scope_ids": ()})()

    store = Store()
    monkeypatch.setenv("DECISIONVAULT_SECRET_ARN", "arn:test")
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda **_kwargs: None)
    monkeypatch.setattr(
        aws_lambda,
        "_agent_grants",
        lambda: {
            "a" * 64: aws_lambda.AgentGrant(
                agent_id="active-agent",
                scope_prefixes=("demo",),
                permissions=frozenset({"decide"}),
                trust=0.8,
            )
        },
    )
    monkeypatch.setattr(aws_lambda, "_build_memory_store", lambda: store)
    aws_lambda._SECURITY_RECONCILE_AT = 0.0
    aws_lambda._refresh_runtime_security_state(force=True)
    active = store.calls[0]["active_producer_agent_ids"]
    assert "active-agent" in active
    assert "recovery-observer" in active


def test_demo_scope_cleanup_does_not_require_revocation_delete_privilege(monkeypatch):
    class Cursor:
        def __init__(self):
            self.sql = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, _params=None):
            self.sql.append(sql)

    class Connection:
        def __init__(self):
            self.cursor_value = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_value

        def commit(self):
            self.committed = True

        def close(self):
            pass

    conn = Connection()
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: conn),
    )

    aws_lambda._delete_scope("phase7-demo-test")

    statements = "\n".join(conn.cursor_value.sql)
    assert "decision_governed_memory_support" in statements
    assert "decision_governed_memories" in statements
    assert "decision_memory_heads" in statements
    assert "decision_episodes" in statements
    assert "DELETE FROM decision_memory_revocations" not in statements
    assert conn.committed is True


def test_consolidation_failure_defers_without_creating_ungoverned_memory(monkeypatch):
    class Outbox:
        def claim_scope(self, scope_id):
            return aws_lambda.ConsolidationWorkItem(
                scope_id=scope_id,
                scope_level=aws_lambda.MemoryScopeLevel.TEAM,
                attempt_count=0,
                generation=1,
            )

        def mark_deferred(self, **_kwargs):
            return 2

        def backlog_count(self):
            return 1

    monkeypatch.setattr(aws_lambda, "_build_consolidation_outbox", lambda: Outbox())
    monkeypatch.setattr(
        aws_lambda,
        "_consolidate_scope",
        lambda _scope_id, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("provider unavailable")
        ),
    )

    result = aws_lambda._best_effort_consolidation("demo")

    assert result["status"] == "DEFERRED"
    assert result["promoted_count"] == 0
    assert result["memory_ids"] == []
    assert result["governance_revision"] == "governed-adaptive-memory-v1"
    assert result["resolutions"] == ["CONSOLIDATION_DEFERRED:RuntimeError"]


def test_memory_scope_level_is_server_controlled_and_prefix_specific(monkeypatch):
    monkeypatch.setenv("DEFAULT_MEMORY_SCOPE_LEVEL", "TEAM")
    monkeypatch.setenv(
        "MEMORY_SCOPE_LEVELS_JSON",
        json.dumps(
            {
                "private/": "PRIVATE",
                "global/": "GLOBAL",
                "global/payments/": "TEAM",
            }
        ),
    )

    assert aws_lambda._memory_scope_level("private/customer-1") == aws_lambda.MemoryScopeLevel.PRIVATE
    assert aws_lambda._memory_scope_level("global/payments/merchant-1") == aws_lambda.MemoryScopeLevel.TEAM
    assert aws_lambda._memory_scope_level("global/risk") == aws_lambda.MemoryScopeLevel.GLOBAL
    assert aws_lambda._memory_scope_level("ordinary/team") == aws_lambda.MemoryScopeLevel.TEAM


def test_agent_api_rejects_caller_supplied_memory_scope_level(monkeypatch):
    token = _configure_agent(monkeypatch)
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(aws_lambda, "_refresh_runtime_security_state", lambda **_kwargs: None)

    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Agent-Token": token},
            "body": json.dumps(
                {
                    "scope_id": "demo",
                    "situation": "payment failed",
                    "memory_scope_level": "PRIVATE",
                }
            ),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "memory_scope_level_is_server_bound"


def test_scheduled_event_drains_durable_consolidation_outbox(monkeypatch):
    calls = []
    monkeypatch.setattr(
        aws_lambda,
        "_refresh_runtime_security_state",
        lambda **_kwargs: calls.append("security"),
    )
    monkeypatch.setattr(
        aws_lambda,
        "_drain_consolidation_outbox",
        lambda: {"completed": 2, "deferred": 0, "backlog": 0},
    )
    monkeypatch.setattr(
        aws_lambda,
        "_maybe_run_memory_quality_calibration",
        lambda: {"status": "NOT_DUE", "interval_hours": 24},
    )

    response = aws_lambda.lambda_handler(
        {"source": "aws.events", "detail-type": "Scheduled Event"},
        None,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["scheduled"] == "consolidation-retry"
    assert body["result"]["completed"] == 2
    assert body["memory_quality_calibration"]["status"] == "NOT_DUE"
    assert calls == ["security"]


def test_scheduled_memory_quality_calibration_is_read_only_threshold_evaluation(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        aws_lambda,
        "_refresh_runtime_security_state",
        lambda **_kwargs: calls.append("security"),
    )
    monkeypatch.setattr(
        aws_lambda,
        "_run_memory_quality_calibration",
        lambda: {
            "observed_samples": 7,
            "recommendation": "INSUFFICIENT_REAL_TELEMETRY",
            "recommended_profile": None,
        },
    )

    response = aws_lambda.lambda_handler(
        {
            "source": "aws.events",
            "detail-type": "Scheduled Event",
            "detail": {"task": "memory-quality-calibration"},
        },
        None,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["scheduled"] == "memory-quality-calibration"
    assert body["result"]["observed_samples"] == 7
    assert body["result"]["recommended_profile"] is None
    assert calls == ["security"]


def test_unknown_scheduled_task_fails_closed(monkeypatch):
    monkeypatch.setattr(
        aws_lambda,
        "_refresh_runtime_security_state",
        lambda **_kwargs: None,
    )
    response = aws_lambda.lambda_handler(
        {
            "source": "aws.events",
            "detail-type": "Scheduled Event",
            "detail": {"task": "unexpected-task"},
        },
        None,
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "unknown_scheduled_task"
