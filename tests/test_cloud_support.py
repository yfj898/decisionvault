from __future__ import annotations

from datetime import datetime, timezone

import pytest

from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import (
    NVIDIA_EMBEDDING_DIMENSIONS,
    deterministic_text_embedding,
    project_dense_embedding,
)


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=()):
        self.cursor_value = FakeCursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_deterministic_embedding_is_stable_and_normalized():
    first = deterministic_text_embedding("stale payment token")
    second = deterministic_text_embedding("stale payment token")

    assert first == second
    assert len(first) == 64
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_deterministic_embedding_rejects_invalid_dimensions():
    with pytest.raises(ValueError, match="dimensions"):
        deterministic_text_embedding("case", dimensions=0)


def test_semantic_projection_is_stable_and_normalized():
    dense = [float(index % 17) / 17.0 for index in range(1024)]
    first = project_dense_embedding(dense)
    second = project_dense_embedding(dense)

    assert first == second
    assert len(first) == 64
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_connection_factory_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        psycopg_connection_factory()


def test_connection_factory_does_not_connect_eagerly(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    factory = psycopg_connection_factory("postgresql://placeholder.invalid/db")

    assert callable(factory)


def test_cockroach_store_save_binds_vector_and_commits():
    conn = FakeConnection()
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
    )
    episode = DecisionEpisode(
        episode_id="00000000-0000-0000-0000-000000000001",
        scope_id="scope-1",
        situation="payment token stale",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        confidence=0.9,
        created_at=datetime.now(timezone.utc),
    )

    store.save(episode)

    sql, params = conn.cursor_value.executions[0]
    assert "INSERT INTO decision_episodes" in sql
    assert params[0] == episode.episode_id
    assert params[1] == "scope-1"
    assert params[8] is None
    assert params[9] is None
    assert params[10] == "[1.00000000,0.00000000]"
    assert conn.committed is True
    assert conn.closed is True


def test_cockroach_store_recall_maps_scoped_vector_result():
    created_at = datetime.now(timezone.utc)
    row = (
        "00000000-0000-0000-0000-000000000001",
        "scope-1",
        "payment token stale",
        Strategy.GENERIC_RETRY.value,
        Outcome.FAILED.value,
        0.1,
        0.9,
        {"source": "test"},
        created_at,
        0.2,
    )
    conn = FakeConnection(rows=[row])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
    )

    recalled = store.recall(scope_id="scope-1", situation="similar", limit=3)

    sql, params = conn.cursor_value.executions[0]
    assert "WHERE scope_id = %s" in sql
    assert params == (
        "[1.00000000,0.00000000]",
        "scope-1",
        "[1.00000000,0.00000000]",
        3,
    )
    assert len(recalled) == 1
    assert recalled[0].episode.scope_id == "scope-1"
    assert recalled[0].episode.outcome == Outcome.FAILED
    assert recalled[0].similarity == pytest.approx(0.8)
    assert conn.closed is True


def test_cockroach_store_uses_query_embedder_for_recall():
    conn = FakeConnection(rows=[])
    calls = []

    def passage(text):
        calls.append(("passage", text))
        return [1.0, 0.0]

    def query(text):
        calls.append(("query", text))
        return [0.0, 1.0]

    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=passage,
        query_embedder=query,
    )
    store.recall(scope_id="scope-1", situation="semantic query", limit=5)

    assert calls == [("query", "semantic query")]
    _, params = conn.cursor_value.executions[0]
    assert params[0] == "[0.00000000,1.00000000]"


def test_nvidia_production_embedding_width_is_native_1024():
    assert NVIDIA_EMBEDDING_DIMENSIONS == 1024


def test_cockroach_store_uses_semantic_heads_for_production_recall():
    conn = FakeConnection(rows=[])
    calls = []

    def semantic_query(text):
        calls.append(("semantic-query", text))
        return [0.25, 0.75]

    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_embedder=lambda _: [0.75, 0.25],
        semantic_query_embedder=semantic_query,
    )
    store.recall(scope_id="scope-1", situation="semantic query", limit=5)

    assert calls == [("semantic-query", "semantic query")]
    sql, params = conn.cursor_value.executions[0]
    assert "FROM decision_memory_heads" in sql
    assert "semantic_embedding <=>" in sql
    assert params[0] == "[0.25000000,0.75000000]"
