-- Production semantic-memory migration.
-- The deterministic VECTOR(64) remains for regression evidence. Hosted semantic
-- retrieval uses the native NVIDIA E5-v5 1024D representation without a lossy
-- application-side projection.
ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS semantic_embedding VECTOR(1024);

ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS semantic_embedding_space STRING;

CREATE TABLE IF NOT EXISTS decision_memory_heads (
    scope_id STRING NOT NULL,
    producer_agent_id STRING NOT NULL,
    strategy STRING NOT NULL,
    episode_id UUID NOT NULL,
    situation STRING NOT NULL,
    outcome STRING NOT NULL,
    effectiveness FLOAT8 NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    semantic_embedding VECTOR(1024) NOT NULL,
    semantic_embedding_space STRING NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_id, producer_agent_id, strategy)
);

CREATE VECTOR INDEX IF NOT EXISTS decision_memory_heads_scope_space_semantic_vec_idx
ON decision_memory_heads (
    scope_id,
    semantic_embedding_space,
    semantic_embedding vector_cosine_ops
);
