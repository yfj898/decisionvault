from __future__ import annotations

import json

import decisionvault.aws_lambda as aws_lambda
from decisionvault.domain import Decision, Strategy


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
    assert "secret" not in response["body"]


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
    assert "do-not-embed-this" not in response["body"]


def test_decide_function_url_shape(monkeypatch):
    monkeypatch.setattr(
        aws_lambda,
        "_build_agent",
        lambda *, memory_enabled, agent_id="recovery-planner": StubAgent(),
    )
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "body": json.dumps(
                {"scope_id": "demo", "situation": "payment failed again"}
            ),
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["strategy"] == "REFRESH_PAYMENT_TOKEN"
    assert body["memory_influenced"] is True
    assert body["model_provider"] == "nvidia:test"
    assert body["recalled_producer_agent_ids"] == ["recovery-observer"]


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


def test_post_routes_require_demo_token_when_configured(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "local-demo-token")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {},
            "body": "{}",
        },
        None,
    )
    assert response["statusCode"] == 401


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


def test_post_routes_accept_matching_demo_token(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "local-demo-token")
    response = aws_lambda.lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/decide",
            "headers": {"X-DecisionVault-Token": "local-demo-token"},
            "body": "{}",
        },
        None,
    )
    assert response["statusCode"] == 400
