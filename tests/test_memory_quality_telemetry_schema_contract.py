from __future__ import annotations

from pathlib import Path

from scripts.apply_memory_quality_telemetry_v8 import _statements


ROOT = Path(__file__).resolve().parents[1]


def test_v8_telemetry_schema_is_identity_free_and_append_only_for_runtime():
    sql = (ROOT / "scripts" / "memory_quality_telemetry_v8.sql").read_text(
        encoding="utf-8"
    )
    for required in (
        "decision_memory_quality_decisions",
        "decision_memory_quality_outcomes",
        "quality_features JSONB NOT NULL",
        "GRANT SELECT, INSERT",
        "TO decisionvault_runtime",
    ):
        assert required in sql
    for forbidden_column in (
        "scope_id STRING",
        "agent_id STRING",
        "producer_agent_id STRING",
        "situation STRING",
        "token STRING",
    ):
        assert forbidden_column not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_v8_migration_is_idempotent_shaped_and_individually_committable():
    sql = (ROOT / "scripts" / "memory_quality_telemetry_v8.sql").read_text(
        encoding="utf-8"
    )
    statements = _statements(sql)
    assert len(statements) == 6
    assert all(not item.upper().startswith("BEGIN") for item in statements)
    assert all(not item.upper().startswith("COMMIT") for item in statements)
    assert sum("CREATE TABLE IF NOT EXISTS" in item for item in statements) == 2
