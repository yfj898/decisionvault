CREATE TABLE IF NOT EXISTS decision_episodes (
    episode_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_id STRING NOT NULL,
    situation STRING NOT NULL,
    strategy STRING NOT NULL,
    outcome STRING NOT NULL,
    effectiveness FLOAT8 NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    embedding VECTOR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decision_episodes_scope_created_idx
ON decision_episodes (scope_id, created_at DESC);

-- Nearest-neighbor query used by the adapter:
-- SELECT ..., (embedding <=> $query_vector::VECTOR) AS distance
-- FROM decision_episodes
-- WHERE scope_id = $scope_id
-- ORDER BY embedding <=> $query_vector::VECTOR
-- LIMIT $limit;
--
-- Apply scripts/vector_index.sql after the table exists. The vector index is a
-- separate migration so Phase 2 persistence and Phase 3 index evidence remain
-- independently reproducible.
