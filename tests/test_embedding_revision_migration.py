from __future__ import annotations

from scripts.migrate_semantic_embedding_space import migrate_current_heads

from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.embedding import semantic_embedding_space


class _Cursor:
    def __init__(self, *, rows=(), fetchone_values=()):
        self.rows = list(rows)
        self.fetchone_values = list(fetchone_values)
        self.executions: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None


class _Connection:
    def __init__(self, *, rows=(), fetchone_values=()):
        self.cursor_value = _Cursor(rows=rows, fetchone_values=fetchone_values)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _Semantic:
    def __init__(self, embedding_space: str):
        self.embedding_space = embedding_space
        self.calls: list[str] = []

    def embed_passage(self, text: str):
        self.calls.append(text)
        return [0.25, 0.75]


def test_same_model_different_revisions_are_distinct_recall_spaces():
    r1 = semantic_embedding_space(
        "nvidia/nv-embedqa-e5-v5", revision="provider-generation-r1"
    )
    r2 = semantic_embedding_space(
        "nvidia/nv-embedqa-e5-v5", revision="provider-generation-r2"
    )
    assert r1 != r2

    conn = _Connection(rows=[])
    store = CockroachVectorMemoryStore(
        connection_factory=lambda: conn,
        embedder=lambda _: [1.0, 0.0],
        semantic_query_embedder=lambda _: [0.0, 1.0],
        semantic_embedding_space=r2,
    )
    assert store.recall(scope_id="scope-a", situation="same model new revision") == []
    sql, params = conn.cursor_value.executions[0]
    assert "semantic_embedding_space = %s" in sql
    assert params[2] == r2
    assert r1 not in params


def test_cross_revision_migration_reembeds_head_and_history_with_cas():
    old_space = semantic_embedding_space(
        "nvidia/nv-embedqa-e5-v5", revision="provider-generation-r1"
    )
    new_space = semantic_embedding_space(
        "nvidia/nv-embedqa-e5-v5", revision="provider-generation-r2"
    )
    episode_id = "00000000-0000-0000-0000-000000000123"
    discovery = _Connection(
        rows=[
            (
                "scope-a",
                "observer-a",
                "GENERIC_RETRY",
                episode_id,
                "stale payment token",
                old_space,
            )
        ]
    )
    update = _Connection(fetchone_values=[(episode_id,)])
    connections = iter((discovery, update))
    semantic = _Semantic(new_space)

    result = migrate_current_heads(lambda: next(connections), semantic)

    assert result.heads_requiring_migration == 1
    assert result.heads_migrated == 1
    assert result.concurrent_head_changes_skipped == 0
    assert semantic.calls == ["stale payment token"]
    head_sql, head_params = update.cursor_value.executions[0]
    assert "semantic_embedding_space IS NOT DISTINCT FROM %s" in head_sql
    assert head_params[1] == new_space
    assert head_params[-1] == old_space
    history_sql, history_params = update.cursor_value.executions[1]
    assert "UPDATE decision_episodes" in history_sql
    assert history_params[1] == new_space
    assert update.committed is True
