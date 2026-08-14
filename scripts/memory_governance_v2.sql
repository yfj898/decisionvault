-- Production multi-agent memory governance v2.
--
-- Existing hosted semantic vectors were produced with NVIDIA E5-v5 using the
-- query/passage contract below. Label them before enforcing non-null head
-- metadata so future model changes cannot silently mix incompatible spaces.

ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS semantic_embedding_space STRING;

ALTER TABLE decision_memory_heads
ADD COLUMN IF NOT EXISTS semantic_embedding_space STRING;

UPDATE decision_episodes
SET semantic_embedding_space = 'nvidia/nv-embedqa-e5-v5|dim=1024|contract=query-passage-v1'
WHERE semantic_embedding IS NOT NULL
  AND semantic_embedding_space IS NULL;

UPDATE decision_memory_heads
SET semantic_embedding_space = 'nvidia/nv-embedqa-e5-v5|dim=1024|contract=query-passage-v1'
WHERE semantic_embedding_space IS NULL;

ALTER TABLE decision_memory_heads
ALTER COLUMN semantic_embedding_space SET NOT NULL;

CREATE VECTOR INDEX IF NOT EXISTS decision_memory_heads_scope_space_semantic_vec_idx
ON decision_memory_heads (
    scope_id,
    semantic_embedding_space,
    semantic_embedding vector_cosine_ops
);

CREATE TABLE IF NOT EXISTS decision_memory_revocations (
    revocation_id UUID PRIMARY KEY,
    scope_id STRING NOT NULL,
    episode_id UUID NOT NULL,
    producer_agent_id STRING NOT NULL,
    reason STRING NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope_id, episode_id)
);

GRANT SELECT, INSERT
ON TABLE decision_memory_revocations
TO decisionvault_runtime;
