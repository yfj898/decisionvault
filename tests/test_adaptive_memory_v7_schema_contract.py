from __future__ import annotations

from pathlib import Path

from scripts.apply_governed_adaptive_memory_v7 import _statements


ROOT = Path(__file__).resolve().parents[1]


def test_v7_adds_durable_outbox_and_distinct_consolidator_identity():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v7.sql").read_text(
        encoding="utf-8"
    )
    assert "decision_memory_consolidation_outbox" in sql
    assert "scope_level STRING NOT NULL" in sql
    assert "attempt_count INT8 NOT NULL" in sql
    assert "generation INT8 NOT NULL" in sql
    assert "next_attempt_at TIMESTAMPTZ NOT NULL" in sql
    assert "lease_until TIMESTAMPTZ" in sql
    assert "CREATE USER IF NOT EXISTS decisionvault_consolidator" in sql
    assert "TO decisionvault_consolidator" in sql


def test_v7_narrows_runtime_adaptive_writes_without_breaking_l3_invalidation():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v7.sql").read_text(
        encoding="utf-8"
    )
    assert (
        "REVOKE INSERT, UPDATE, DELETE\n"
        "ON TABLE decision_memory_consolidation_candidates\n"
        "FROM decisionvault_runtime"
    ) in sql
    assert (
        "REVOKE INSERT, UPDATE, DELETE\n"
        "ON TABLE decision_strategy_effectiveness\n"
        "FROM decisionvault_runtime"
    ) in sql
    assert (
        "REVOKE INSERT, DELETE\n"
        "ON TABLE decision_governed_memories\n"
        "FROM decisionvault_runtime"
    ) in sql
    assert (
        "GRANT SELECT, UPDATE\n"
        "ON TABLE decision_governed_memories\n"
        "TO decisionvault_runtime"
    ) in sql
    assert (
        "GRANT SELECT, INSERT, UPDATE\n"
        "ON TABLE decision_memory_consolidation_outbox\n"
        "TO decisionvault_runtime"
    ) in sql


def test_v7_migration_is_individually_committed_and_idempotent_shaped():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v7.sql").read_text(
        encoding="utf-8"
    )
    statements = _statements(sql)
    assert len(statements) >= 10
    assert any("CREATE TABLE IF NOT EXISTS" in statement for statement in statements)
    assert any("CREATE USER IF NOT EXISTS" in statement for statement in statements)
    assert not any(statement.upper().startswith("BEGIN") for statement in statements)
    assert not any(statement.upper().startswith("COMMIT") for statement in statements)


def test_v7_expand_is_safe_before_runtime_privilege_contract():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v7_expand.sql").read_text(
        encoding="utf-8"
    )
    assert "decision_memory_consolidation_outbox" in sql
    assert "decisionvault_consolidator" in sql
    assert "REVOKE " not in sql
    assert "TO decisionvault_runtime" in sql


def test_v7_contract_contains_only_runtime_privilege_narrowing():
    sql = (ROOT / "scripts" / "governed_adaptive_memory_v7_contract.sql").read_text(
        encoding="utf-8"
    )
    assert "REVOKE INSERT, UPDATE, DELETE" in sql
    assert "FROM decisionvault_runtime" in sql
    assert "CREATE TABLE" not in sql
    assert "CREATE USER" not in sql


def test_v7_cloud_smoke_uses_separate_consolidation_identity():
    source = (ROOT / "scripts" / "adaptive_memory_cloud_smoke.py").read_text(
        encoding="utf-8"
    )
    assert '"CONSOLIDATION_DATABASE_URL", runtime_database_url' in source
    assert "consolidation_connection_factory = psycopg_connection_factory(" in source
    assert "connection_factory=consolidation_connection_factory" in source
    assert "DELETE FROM decision_memory_consolidation_outbox" in source
    assert '"decision_memory_consolidation_outbox"' in source


def test_v7_semantic_benchmark_cleanup_uses_admin_boundary_and_covers_outbox():
    source = (ROOT / "scripts" / "benchmark_semantic_production.py").read_text(
        encoding="utf-8"
    )
    assert '"DECISIONVAULT_CLEANUP_DATABASE_URL", runtime_database_url' in source
    assert "cleanup_connection_factory = psycopg_connection_factory(" in source
    assert "DELETE FROM decision_memory_consolidation_outbox" in source
    assert "_delete_prefix(cleanup_connection_factory, run_prefix)" in source
