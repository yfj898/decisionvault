from __future__ import annotations

from pathlib import Path

from scripts.apply_memory_quality_telemetry_v8 import _statements
from scripts.apply_memory_quality_calibration_v9 import _statements as _v9_statements
from scripts.apply_memory_quality_sampling_v10 import _statements as _v10_statements


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


def test_v9_calibration_runs_are_aggregate_append_only_artifacts():
    sql = (ROOT / "scripts" / "memory_quality_calibration_v9.sql").read_text(
        encoding="utf-8"
    )
    for required in (
        "decision_memory_quality_calibration_runs",
        "observed_samples INT8 NOT NULL",
        "recommendation STRING NOT NULL",
        "challengers JSONB NOT NULL",
        "GRANT SELECT, INSERT",
        "TO decisionvault_runtime",
    ):
        assert required in sql
    for forbidden_column in (
        "scope_id STRING",
        "agent_id STRING",
        "producer_agent_id STRING",
        "situation STRING",
        "episode_id UUID",
        "memory_id UUID",
        "execution_receipt_id STRING",
        "decision_snapshot_id UUID",
    ):
        assert forbidden_column not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql


def test_v9_migration_is_idempotent_shaped_and_individually_committable():
    sql = (ROOT / "scripts" / "memory_quality_calibration_v9.sql").read_text(
        encoding="utf-8"
    )
    statements = _v9_statements(sql)
    assert len(statements) == 4
    assert all(not item.upper().startswith("BEGIN") for item in statements)
    assert all(not item.upper().startswith("COMMIT") for item in statements)
    assert sum("CREATE TABLE IF NOT EXISTS" in item for item in statements) == 1


def test_v10_sampling_audit_is_aggregate_and_retention_delete_is_maintenance_only():
    sql = (ROOT / "scripts" / "memory_quality_sampling_v10.sql").read_text(
        encoding="utf-8"
    )
    statements = _v10_statements(sql)
    assert len(statements) == 3
    assert "sampling_gate_pass BOOL NOT NULL DEFAULT false" in sql
    assert "sampling_audit JSONB NOT NULL DEFAULT '{}'::JSONB" in sql
    assert "GRANT DELETE" in sql
    assert "TO decisionvault_consolidator" in sql
    assert "TO decisionvault_runtime" not in sql
    for forbidden in (
        "scope_id STRING",
        "agent_id STRING",
        "producer_agent_id STRING",
        "situation STRING",
        "token STRING",
    ):
        assert forbidden not in sql
