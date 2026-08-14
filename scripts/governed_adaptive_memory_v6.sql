-- Governed Adaptive Memory v6.
-- Apply one statement per transaction. CockroachDB online schema changes are
-- committed individually by apply_governed_adaptive_memory_v6.py.

CREATE TABLE IF NOT EXISTS decision_memory_consolidation_candidates (
    candidate_id UUID PRIMARY KEY,
    scope_id STRING NOT NULL,
    scope_level STRING NOT NULL,
    memory_type STRING NOT NULL,
    polarity STRING NOT NULL,
    situation_class STRING NOT NULL,
    rule_key STRING NOT NULL,
    preconditions JSONB NOT NULL,
    exclusions JSONB NOT NULL,
    intervention STRING NOT NULL,
    expected_outcome STRING NOT NULL,
    supporting_episode_ids JSONB NOT NULL,
    producer_set JSONB NOT NULL,
    positive_episode_ids JSONB NOT NULL,
    negative_episode_ids JSONB NOT NULL,
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    observed_from TIMESTAMPTZ NOT NULL,
    observed_to TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    governance_revision STRING NOT NULL,
    semantic_embedding_space STRING NOT NULL,
    memory_class STRING NOT NULL,
    status STRING NOT NULL,
    governance_resolution STRING,
    governance_trace JSONB,
    governed_at TIMESTAMPTZ,
    supersedes_memory_id UUID
);

CREATE INDEX IF NOT EXISTS decision_memory_candidates_scope_observed_idx
ON decision_memory_consolidation_candidates (scope_id, observed_to DESC);

CREATE TABLE IF NOT EXISTS decision_strategy_effectiveness (
    scope_id STRING NOT NULL,
    situation_class STRING NOT NULL,
    strategy STRING NOT NULL,
    semantic_embedding_space STRING NOT NULL,
    sample_count INT8 NOT NULL CHECK (sample_count >= 0),
    success_count INT8 NOT NULL CHECK (success_count >= 0),
    failure_count INT8 NOT NULL CHECK (failure_count >= 0),
    effectiveness FLOAT8 NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    independent_producer_count INT8 NOT NULL CHECK (independent_producer_count >= 0),
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    observed_to TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    governance_revision STRING NOT NULL,
    PRIMARY KEY (scope_id, situation_class, strategy, semantic_embedding_space)
);

CREATE INDEX IF NOT EXISTS decision_strategy_effectiveness_scope_observed_idx
ON decision_strategy_effectiveness (scope_id, observed_to DESC);

CREATE TABLE IF NOT EXISTS decision_governed_memories (
    memory_id UUID PRIMARY KEY,
    candidate_id UUID NOT NULL UNIQUE,
    scope_id STRING NOT NULL,
    scope_level STRING NOT NULL,
    memory_type STRING NOT NULL,
    polarity STRING NOT NULL,
    situation_class STRING NOT NULL,
    rule_key STRING NOT NULL,
    preconditions JSONB NOT NULL,
    exclusions JSONB NOT NULL,
    intervention STRING NOT NULL,
    expected_outcome STRING NOT NULL,
    supporting_episode_ids JSONB NOT NULL,
    producer_set JSONB NOT NULL,
    positive_episode_ids JSONB NOT NULL,
    negative_episode_ids JSONB NOT NULL,
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    observed_from TIMESTAMPTZ NOT NULL,
    observed_to TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    governance_revision STRING NOT NULL,
    semantic_embedding VECTOR(1024) NOT NULL,
    semantic_embedding_space STRING NOT NULL,
    memory_class STRING NOT NULL,
    expires_at TIMESTAMPTZ,
    status STRING NOT NULL,
    supersedes_memory_id UUID,
    revoked_at TIMESTAMPTZ,
    revocation_reason STRING
);

CREATE UNIQUE INDEX IF NOT EXISTS decision_governed_memories_supersedes_uidx
ON decision_governed_memories (supersedes_memory_id)
WHERE supersedes_memory_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS decision_governed_memories_active_rule_uidx
ON decision_governed_memories (
    scope_id,
    rule_key,
    semantic_embedding_space
)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS decision_governed_memories_scope_observed_idx
ON decision_governed_memories (scope_id, observed_to DESC);

CREATE TABLE IF NOT EXISTS decision_governed_memory_support (
    memory_id UUID NOT NULL,
    episode_id UUID NOT NULL,
    producer_agent_id STRING NOT NULL,
    evidence_polarity STRING NOT NULL,
    PRIMARY KEY (memory_id, episode_id)
);

CREATE INDEX IF NOT EXISTS decision_governed_memory_support_episode_idx
ON decision_governed_memory_support (episode_id, memory_id);

CREATE VECTOR INDEX IF NOT EXISTS decision_governed_memories_scope_space_semantic_vec_idx
ON decision_governed_memories (
    scope_id,
    semantic_embedding_space,
    semantic_embedding vector_cosine_ops
);

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_memory_consolidation_candidates
TO decisionvault_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_strategy_effectiveness
TO decisionvault_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_governed_memories
TO decisionvault_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_governed_memory_support
TO decisionvault_runtime;
