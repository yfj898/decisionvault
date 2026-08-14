from __future__ import annotations

from scripts.apply_production_memory_v5 import _statements


def test_v5_runner_splits_schema_changes_into_separate_commits():
    sql = """
    -- expand; this comment semicolon must not split a statement
    ALTER TABLE t ADD COLUMN IF NOT EXISTS x STRING;
    UPDATE t SET x = 'v' WHERE x IS NULL;
    """
    statements = _statements(sql)
    assert len(statements) == 2
    assert "ALTER TABLE" in statements[0]
    assert "UPDATE t" in statements[1]
