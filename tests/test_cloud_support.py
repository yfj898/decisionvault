from __future__ import annotations

from datetime import datetime, timezone

import pytest

from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.cockroach import (
    CockroachVectorMemoryStore,
    MemoryRevocationConflict,
    SupersessionWriteConflict,
)
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import (
    NVIDIA_EMBEDDING_DIMENSIONS,
    deterministic_text_embedding,
    project_dense_embedding,
    semantic_embedding_space,
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

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows[0]


class FakeConnection:
    def __init__(self, rows=()):
        self.cursor_value = FakeCursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.committed = False

    def close(self):
        self.closed = True


class ScriptedCursor(FakeCursor):
    def __init__(self, fetchone_values):
        super().__init__(rows=[])
        self.fetchone_values = list(fetchone_values)

    def fetchone(self):
        if not self.fetchone_values:
            return None
        return self.fetchone_values.pop(0)


class ScriptedConnection(FakeConnection):
    def __init__(self, fetchone_values):
        self.cursor_value = ScriptedCursor(fetchone_values)
        self.committed = False
        self.closed = False


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
        observed_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
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
    observed_at = datetime.now(timezone.utc)
    recorded_at = observed_at
    row = (
        "00000000-0000-0000-0000-000000000001",
        "scope-1",
        "payment token stale",
        Strategy.GENERIC_RETRY.value,
        Outcome.FAILED.value,
        0.1,
        0.9,
        {"source": "test"},
        observed_at,
        recorded_at,
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
    assert "decision_memory_revocations" in sql
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


def test_semantic_embedding_space_binds_model_dimensions_and_contract():
    assert semantic_embedding_space(
        "nvidia/nv-embedqa-e5-v5", revision="decisionvault-prod-r1"
    ) == (
        "nvidia/nv-embedqa-e5-v5|revision=decisionvault-prod-r1|dim=1024|contract=query-passage-v1"
    )

    with pytest.raises(ValueError, match="revision"):
        semantic_embedding_space("nvidia/nv-embedqa-e5-v5", revision="")


def test_semantic_store_requires_explicit_embedding_space():
    with pytest.raises(ValueError, match="semantic_embedding_space"):
        CockroachVectorMemoryStore(
            connection_factory=lambda: FakeConnection(),
            embedder=lambda _: [1.0, 0.0],
            semantic_embedder=lambda _: [0.75, 0.25],
        )


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
        semantic_embedding_space="test-space-v1",
    )
    store.recall(scope_id="scope-1", situation="semantic query", limit=5)

    assert calls == [("semantic-query", "semantic query")]
    sql, params = conn.cursor_value.executions[0]
    assert "FROM decision_memory_heads" in sql
    assert "semantic_embedding <=>" in sql
    assert "memory_status" in sql
    assert "INTERVAL '90 days'" in sql
    assert "outcome = 'SUCCESS' AND effectiveness >= 0.7" in sql
    assert "outcome = 'FAILED' AND confidence >= 0.6" in sql
    assert params == (
        "[0.25000000,0.75000000]",
        "scope-1",
        "test-space-v1",
        "[0.25000000,0.75000000]",
        5,
    )


def test_semantic_late_event_is_history_only_and_cannot_replace_newer_head():
    incoming_time = datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)
    newer_time = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    conn = ScriptedConnection([(newer_time,)])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_embedder=lambda _: [0.75, 0.25],
        semantic_embedding_space="test-space-v1",
    )
    episode = DecisionEpisode(
        episode_id="00000000-0000-0000-0000-000000000099",
        scope_id="scope-1",
        situation="late old payment observation",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        confidence=1.0,
        evidence={"producer_agent_id": "agent-a"},
        observed_at=incoming_time,
        recorded_at=newer_time,
    )

    store.save(episode)

    statements = conn.cursor_value.executions
    assert "SELECT max(observed_at)" in statements[0][0]
    assert "INSERT INTO decision_episodes" in statements[1][0]
    assert not any("INSERT INTO decision_memory_heads" in sql for sql, _ in statements)
    assert conn.committed is True


def test_semantic_governed_recall_merges_ann_with_unbounded_threshold_coverage():
    observed_at = datetime.now(timezone.utc)
    recorded_at = observed_at
    row = (
        "00000000-0000-0000-0000-000000000001",
        "scope-1",
        "payment token stale",
        Strategy.GENERIC_RETRY.value,
        Outcome.FAILED.value,
        0.1,
        0.9,
        {"producer_agent_id": "agent-a"},
        observed_at,
        recorded_at,
        0.2,
    )
    conn = FakeConnection(rows=[row])
    calls = []

    def semantic_query(text):
        calls.append(text)
        return [0.25, 0.75]

    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_query_embedder=semantic_query,
        semantic_embedding_space="test-space-v1",
    )

    recalled = store.recall_governed(
        scope_id="scope-1",
        situation="payment token stale",
        minimum_similarity=0.40,
    )

    assert calls == ["payment token stale"]
    assert len(conn.cursor_value.executions) == 2
    ann_sql, _ = conn.cursor_value.executions[0]
    coverage_sql, coverage_params = conn.cursor_value.executions[1]
    assert "LIMIT 32" in ann_sql
    assert "LIMIT" not in coverage_sql
    assert "semantic_embedding <=> %s::VECTOR <= %s" in coverage_sql
    assert coverage_params[-1] == pytest.approx(0.60)
    assert "decision_memory_revocations" in coverage_sql
    assert len(recalled) == 1


def test_semantic_supersession_uses_atomic_current_head_compare_and_delete():
    now = datetime.now(timezone.utc)
    conn = ScriptedConnection(
        [
            (now.replace(year=now.year - 1),),
            ("00000000-0000-0000-0000-000000000001",),
        ]
    )
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_embedder=lambda _: [0.75, 0.25],
        semantic_embedding_space="test-space-v1",
    )
    episode = DecisionEpisode(
        episode_id="00000000-0000-0000-0000-000000000002",
        scope_id="scope-1",
        situation="corrected payment recovery evidence",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        confidence=1.0,
        evidence={
            "producer_agent_id": "agent-a",
            "supersedes_episode_id": "00000000-0000-0000-0000-000000000001",
        },
        observed_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )

    store.save(episode)

    statements = conn.cursor_value.executions
    assert "SELECT max(observed_at)" in statements[0][0]
    delete_sql, delete_params = statements[1]
    assert "DELETE FROM decision_memory_heads" in delete_sql
    assert "producer_agent_id = %s" in delete_sql
    assert "episode_id = %s::UUID" in delete_sql
    assert "RETURNING episode_id::STRING" in delete_sql
    assert delete_params == (
        "scope-1",
        "agent-a",
        "00000000-0000-0000-0000-000000000001",
        episode.observed_at,
    )
    assert "INSERT INTO decision_episodes" in statements[2][0]
    assert "INSERT INTO decision_memory_heads" in statements[3][0]
    assert "ON CONFLICT" in statements[3][0]
    assert "excluded.observed_at > decision_memory_heads.observed_at" in statements[3][0]


def test_supersession_loses_if_normal_write_already_replaced_current_head():
    conn = ScriptedConnection([None, None])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_embedder=lambda _: [0.75, 0.25],
        semantic_embedding_space="test-space-v1",
    )
    episode = DecisionEpisode(
        episode_id="00000000-0000-0000-0000-000000000003",
        scope_id="scope-1",
        situation="late correction after a concurrent normal write",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        confidence=1.0,
        evidence={
            "producer_agent_id": "agent-a",
            "supersedes_episode_id": "00000000-0000-0000-0000-000000000001",
        },
        observed_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
    )

    with pytest.raises(SupersessionWriteConflict, match="current governed head"):
        store.save(episode)

    assert len(conn.cursor_value.executions) == 2
    assert "SELECT max(observed_at)" in conn.cursor_value.executions[0][0]
    assert "DELETE FROM decision_memory_heads" in conn.cursor_value.executions[1][0]
    assert conn.committed is False


def test_revoke_current_head_is_atomic_and_audited():
    episode_id = "00000000-0000-0000-0000-000000000010"
    conn = ScriptedConnection([None, (episode_id,)])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
    )

    result = store.revoke_current_head(
        scope_id="scope-1",
        producer_agent_id="agent-a",
        episode_id=episode_id,
        reason="operator confirmed this observation is invalid",
    )

    assert result.episode_id == episode_id
    assert result.producer_agent_id == "agent-a"
    assert result.idempotent_replay is False
    assert "SELECT revocation_id::STRING" in conn.cursor_value.executions[0][0]
    delete_sql, delete_params = conn.cursor_value.executions[1]
    assert "DELETE FROM decision_memory_heads" in delete_sql
    assert delete_params == ("scope-1", "agent-a", episode_id)
    assert "INSERT INTO decision_memory_revocations" in conn.cursor_value.executions[2][0]
    assert conn.committed is True


def test_revoke_current_head_replay_returns_existing_audit_event():
    episode_id = "00000000-0000-0000-0000-000000000010"
    revocation_id = "00000000-0000-0000-0000-000000000011"
    conn = ScriptedConnection([(revocation_id, "agent-a")])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
    )

    result = store.revoke_current_head(
        scope_id="scope-1",
        producer_agent_id="agent-a",
        episode_id=episode_id,
        reason="same request replayed",
    )

    assert result.revocation_id == revocation_id
    assert result.idempotent_replay is True
    assert len(conn.cursor_value.executions) == 1


def test_revoke_rejects_non_current_or_cross_producer_target():
    episode_id = "00000000-0000-0000-0000-000000000010"
    conn = ScriptedConnection([None, None])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
    )

    with pytest.raises(MemoryRevocationConflict, match="current governed head"):
        store.revoke_current_head(
            scope_id="scope-1",
            producer_agent_id="agent-b",
            episode_id=episode_id,
            reason="attempted cross-producer revoke",
        )

    assert conn.committed is False
