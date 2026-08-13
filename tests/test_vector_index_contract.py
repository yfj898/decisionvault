from pathlib import Path

import pytest

from decisionvault.memory.embedding import deterministic_text_embedding


ROOT = Path(__file__).resolve().parents[1]
VECTOR_INDEX_SQL = ROOT / "scripts" / "vector_index.sql"


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_vector_index_migration_uses_scope_prefix_and_cosine_opclass():
    sql = VECTOR_INDEX_SQL.read_text(encoding="utf-8")

    assert "CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx" in sql
    assert "(scope_id, embedding vector_cosine_ops)" in sql


def test_phase3_target_is_relevant_under_deterministic_embedding():
    query = deterministic_text_embedding(
        "payment failed again after the customer replaced the card; "
        "the saved token looks stale"
    )
    target = deterministic_text_embedding(
        "customer payment failed twice after replacing their card "
        "and the stored payment token may be stale"
    )

    assert _cosine(query, target) == pytest.approx(0.5720775535)
    assert _cosine(query, target) > 0.30


def test_exact_query_can_be_forced_to_primary_index_for_ann_comparison():
    source = (ROOT / "scripts" / "vector_index_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "decision_episodes@decision_episodes_pkey" in source
    assert "recall_at_5" in source
    assert "foreign_perfect_match_excluded" in source
