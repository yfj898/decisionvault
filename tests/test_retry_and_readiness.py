from __future__ import annotations

import json
import sys
import types

import decisionvault.aws_lambda as aws_lambda
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.retry import retry_cockroach_serialization


class RetryableError(Exception):
    sqlstate = "40001"


def test_serialization_retry_retries_complete_operation():
    calls = []

    def operation():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise RetryableError()
        return "ok"

    sleeps = []
    assert retry_cockroach_serialization(
        operation,
        sleep=sleeps.append,
    ) == "ok"
    assert calls == [1, 2, 3]
    assert sleeps == [0.02, 0.04]


def test_non_serialization_error_is_not_retried():
    calls = []

    def operation():
        calls.append(1)
        raise RuntimeError("no retry")

    try:
        retry_cockroach_serialization(operation, sleep=lambda _: None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    assert len(calls) == 1


def test_connection_factory_applies_connection_and_statement_timeouts(monkeypatch):
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return object()

    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=connect))
    factory = psycopg_connection_factory(
        "postgresql://placeholder.invalid/db",
        connect_timeout_seconds=4,
        statement_timeout_ms=7000,
    )
    factory()
    assert calls[0][1]["connect_timeout"] == 4
    assert calls[0][1]["options"] == "-c statement_timeout=7000"


class ReadyCursor:
    def __init__(self):
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, _params=None):
        self.last_sql = sql

    def fetchone(self):
        if "current_database()" in self.last_sql:
            return ("decisionvault",)
        if "WHERE semantic_embedding_space IS DISTINCT FROM" in self.last_sql:
            return (0,)
        if "FROM decision_governed_memories" in self.last_sql and "count(*)" in self.last_sql:
            return (0,)
        if "FROM decision_strategy_effectiveness" in self.last_sql and "count(*)" in self.last_sql:
            return (0,)
        return (1,)


class ReadyConnection:
    def __init__(self, host="cluster-test-host"):
        self.info = types.SimpleNamespace(host=host)

    def cursor(self):
        return ReadyCursor()

    def close(self):
        pass


class ReadyEmbedder:
    def __init__(self, **kwargs):
        self.embedding_space = (
            "nvidia/nv-embedqa-e5-v5|revision="
            f"{kwargs['revision']}|dim=1024|contract=query-passage-v1"
        )

    def embed_query(self, _text):
        return [0.0] * 1024


class FailingEmbedder:
    def __init__(self, **_kwargs):
        pass

    def embed_query(self, _text):
        raise RuntimeError("embedding provider unavailable")


def _configure_ready_security(monkeypatch):
    monkeypatch.setenv(
        "AGENT_AUTH_JSON",
        json.dumps(
            {
                "a" * 64: {
                    "agent_id": "planner",
                    "scope_prefixes": ["demo"],
                    "permissions": ["decide"],
                    "trust": 0.8,
                }
            }
        ),
    )
    monkeypatch.setenv("EXECUTION_RECEIPT_SECRET", "receipt-secret-value")
    monkeypatch.setenv("DEMO_API_TOKEN", "demo-token")
    monkeypatch.setenv("EXECUTION_SANDBOX_SCENARIO", "stale_payment_token")
    monkeypatch.setenv("NVIDIA_EMBED_REVISION", "test-revision-v1")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


def test_readiness_checks_secret_database_and_embedding(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    _configure_ready_security(monkeypatch)
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: ReadyConnection()),
    )
    monkeypatch.setattr(aws_lambda, "NvidiaSemanticEmbedder", ReadyEmbedder)
    monkeypatch.setenv("NVIDIA_API_KEY", "test")

    status, payload = aws_lambda._readiness()

    assert status == 200
    assert payload["status"] == "ready"
    assert payload["database"] is True
    assert payload["consolidation_database"] is True
    assert payload["consolidation_identity_isolated"] is True
    assert payload["consolidation_database_consistent"] is True
    assert payload["consolidation_outbox_schema"] is True
    assert payload["memory_scope_control"] is True
    assert payload["semantic_embedding"] is True
    assert payload["semantic_embedding_revision"] is True
    assert payload["semantic_head_space_current"] is True
    assert payload["adaptive_memory_schema"] is True
    assert payload["adaptive_memory_current"] is True
    assert payload["nvidia_provider_origin"] is True
    assert payload["advisor_required_for_readiness"] is False


def test_readiness_fails_closed_when_consolidation_database_diverges(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    _configure_ready_security(monkeypatch)
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)

    class DivergentCursor(ReadyCursor):
        def fetchone(self):
            if "current_database()" in self.last_sql:
                return ("decisionvault",)
            return super().fetchone()

    class DivergentConnection(ReadyConnection):
        def __init__(self):
            super().__init__(host="cluster-other-host")

        def cursor(self):
            return DivergentCursor()

    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: ReadyConnection()),
    )
    monkeypatch.setattr(
        aws_lambda,
        "_consolidation_connection_factory",
        lambda: (lambda: DivergentConnection()),
    )
    monkeypatch.setattr(aws_lambda, "NvidiaSemanticEmbedder", ReadyEmbedder)
    monkeypatch.setenv("NVIDIA_API_KEY", "test")

    status, payload = aws_lambda._readiness()

    assert status == 503
    assert payload["status"] == "not_ready"
    assert payload["consolidation_database_consistent"] is False


def test_readiness_fails_closed_when_semantic_embedding_is_unavailable(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    _configure_ready_security(monkeypatch)
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: ReadyConnection()),
    )
    monkeypatch.setattr(aws_lambda, "NvidiaSemanticEmbedder", FailingEmbedder)
    monkeypatch.setenv("NVIDIA_API_KEY", "test")

    status, payload = aws_lambda._readiness()

    assert status == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] is True
    assert payload["semantic_embedding"] is False
    assert payload["advisor_required_for_readiness"] is False
    assert payload["errors"]


def test_readiness_fails_closed_on_security_control_misconfiguration(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: ReadyConnection()),
    )
    monkeypatch.setattr(aws_lambda, "NvidiaSemanticEmbedder", ReadyEmbedder)
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setenv("AGENT_AUTH_JSON", "not-json")
    monkeypatch.setenv("EXECUTION_RECEIPT_SECRET", "short")
    monkeypatch.setenv("DEMO_API_TOKEN", "")
    monkeypatch.setenv("NVIDIA_EMBED_REVISION", "test-revision-v1")

    status, payload = aws_lambda._readiness()

    assert status == 503
    assert payload["agent_auth"] is False
    assert payload["execution_receipt_signing"] is False
    assert payload["demo_auth"] is False


def test_readiness_fails_closed_on_nvidia_origin_override(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    _configure_ready_security(monkeypatch)
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://attacker.example/v1")
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setattr(aws_lambda, "hydrate_runtime_secrets", lambda: None)
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: ReadyConnection()),
    )
    monkeypatch.setattr(aws_lambda, "NvidiaSemanticEmbedder", ReadyEmbedder)

    status, payload = aws_lambda._readiness()

    assert status == 503
    assert payload["nvidia_provider_origin"] is False


def test_readiness_cache_avoids_repeated_external_probe(monkeypatch):
    aws_lambda._READINESS_CACHE = None
    calls = []
    monkeypatch.setenv("READINESS_CACHE_SECONDS", "30")
    monkeypatch.setattr(
        aws_lambda,
        "_probe_readiness",
        lambda: (calls.append(1) or (200, {"status": "ready"})),
    )
    assert aws_lambda._readiness()[0] == 200
    assert aws_lambda._readiness()[0] == 200
    assert calls == [1]


def test_liveness_has_no_dependency_contract():
    assert aws_lambda._liveness() == {
        "service": "decisionvault",
        "status": "live",
    }
