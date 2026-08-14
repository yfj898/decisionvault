from __future__ import annotations

from pathlib import Path

from decisionvault.adaptive_memory import ADAPTIVE_MEMORY_GOVERNANCE_REVISION
from decisionvault.memory.governed_query import (
    adaptive_semantic_ann_sql,
    adaptive_semantic_coverage_sql,
)
from scripts.apply_governed_adaptive_memory_v6 import _statements


ROOT = Path(__file__).resolve().parents[1]


def test_v6_schema_contains_candidate_semantic_procedural_and_lineage_layers():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v6.sql").read_text(
        encoding="utf-8"
    )
    assert "decision_memory_consolidation_candidates" in sql
    assert "decision_strategy_effectiveness" in sql
    assert "decision_governed_memories" in sql
    assert "decision_governed_memory_support" in sql
    assert "supporting_episode_ids JSONB NOT NULL" in sql
    assert "producer_set JSONB NOT NULL" in sql
    assert sql.count("rule_key STRING NOT NULL") == 2
    assert "positive_episode_ids JSONB NOT NULL" in sql
    assert "negative_episode_ids JSONB NOT NULL" in sql
    assert "governance_revision STRING NOT NULL" in sql
    assert "semantic_embedding VECTOR(1024) NOT NULL" in sql
    assert "supersedes_memory_id UUID" in sql
    assert "decision_governed_memories_active_rule_uidx" in sql
    assert "scope_id,\n    rule_key,\n    semantic_embedding_space" in sql
    assert "decision_governed_memories_supersedes_uidx" in sql
    assert "decision_governed_memories_scope_space_semantic_vec_idx" in sql
    assert sql.count("TO decisionvault_runtime") == 4
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in sql
    assert "GRANT CREATE" not in sql


def test_v6_runner_keeps_schema_changes_as_individual_committed_statements():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v6.sql").read_text(
        encoding="utf-8"
    )
    statements = _statements(sql)
    assert len(statements) >= 10
    assert not any(statement.upper().startswith("BEGIN") for statement in statements)
    assert not any(statement.upper().startswith("COMMIT") for statement in statements)
    assert any("CREATE VECTOR INDEX" in statement for statement in statements)


def test_adaptive_dvi_fast_path_and_exact_governance_coverage_are_separate():
    ann = adaptive_semantic_ann_sql(
        vector_expr="$vector",
        scope_expr="$scope",
        space_expr="$space",
    )
    coverage = adaptive_semantic_coverage_sql(
        vector_expr="$vector",
        scope_expr="$scope",
        space_expr="$space",
        governance_revision_expr="$revision",
        max_distance_expr="$distance",
    )
    assert "decision_governed_memories" in ann
    assert "ORDER BY m.semantic_embedding <=> $vector" in ann
    assert "LIMIT 32" in ann
    assert "decision_governed_memory_support" not in ann
    assert "decision_governed_memory_support" in coverage
    assert "decision_memory_heads" in coverage
    assert "m.status = 'ACTIVE'" in coverage
    assert "m.expires_at IS NULL OR m.expires_at >= now()" in coverage
    assert "m.governance_revision = $revision" in coverage
    assert "m.semantic_embedding <=> $vector <= $distance" in coverage


def test_current_governance_revision_is_explicitly_versioned():
    assert ADAPTIVE_MEMORY_GOVERNANCE_REVISION == "governed-adaptive-memory-v1"
