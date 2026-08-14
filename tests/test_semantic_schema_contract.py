from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_semantic_schema_uses_native_1024d_and_governed_heads():
    sql = (ROOT / "scripts" / "semantic_memory.sql").read_text(encoding="utf-8")
    assert "semantic_embedding VECTOR(1024)" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_memory_heads" in sql
    assert "PRIMARY KEY (scope_id, producer_agent_id, strategy)" in sql
    assert "decision_memory_heads_scope_semantic_vec_idx" in sql
    assert "(scope_id, semantic_embedding vector_cosine_ops)" in sql
