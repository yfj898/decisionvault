from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_semantic_schema_uses_native_1024d_and_governed_heads():
    sql = (ROOT / "scripts" / "semantic_memory.sql").read_text(encoding="utf-8")
    assert "semantic_embedding VECTOR(1024)" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_memory_heads" in sql
    assert "PRIMARY KEY (scope_id, producer_agent_id, strategy)" in sql
    assert "decision_memory_heads_scope_space_semantic_vec_idx" in sql
    assert "semantic_embedding_space" in sql
    assert "observed_at TIMESTAMPTZ" in sql
    assert "recorded_at TIMESTAMPTZ" in sql


def test_memory_governance_v2_adds_embedding_space_and_revocation_audit():
    sql = (ROOT / "scripts" / "memory_governance_v2.sql").read_text(
        encoding="utf-8"
    )
    assert "semantic_embedding_space STRING" in sql
    assert "semantic_embedding_space SET NOT NULL" in sql
    assert "decision_memory_heads_scope_space_semantic_vec_idx" in sql
    assert "scope_id," in sql
    assert "semantic_embedding_space," in sql
    assert "semantic_embedding vector_cosine_ops" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_memory_revocations" in sql
    assert "UNIQUE (scope_id, episode_id)" in sql
    assert "GRANT SELECT, INSERT" in sql


def test_production_memory_v5_separates_event_and_record_time_and_versions_space():
    sql = (ROOT / "scripts" / "production_memory_v5.sql").read_text(
        encoding="utf-8"
    )
    assert "ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ" in sql
    assert "ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ" in sql
    assert "SET observed_at = created_at" in sql
    assert "SET recorded_at = created_at" in sql
    assert "ALTER COLUMN observed_at SET DEFAULT now()" in sql
    assert "ALTER COLUMN recorded_at SET DEFAULT now()" in sql
    assert "revision=legacy-unversioned" in sql
    assert "decision_episodes_scope_observed_idx" in sql
