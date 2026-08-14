CREATE TABLE IF NOT EXISTS decision_episodes (
    episode_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_id STRING NOT NULL,
    situation STRING NOT NULL,
    strategy STRING NOT NULL,
    outcome STRING NOT NULL,
    effectiveness FLOAT8 NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    execution_receipt_id STRING,
    supersedes_episode_id UUID,
    embedding VECTOR(64) NOT NULL,
    semantic_embedding VECTOR(1024),
    semantic_embedding_space STRING,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decision_episodes_scope_observed_idx
ON decision_episodes (scope_id, observed_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS decision_episodes_execution_receipt_uidx
ON decision_episodes (execution_receipt_id)
WHERE execution_receipt_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS decision_episodes_supersedes_uidx
ON decision_episodes (supersedes_episode_id)
WHERE supersedes_episode_id IS NOT NULL;

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
    execution_receipt_id STRING,
    supersedes_episode_id UUID,
    semantic_embedding VECTOR(1024) NOT NULL,
    semantic_embedding_space STRING NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_id, producer_agent_id, strategy)
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

CREATE TABLE IF NOT EXISTS decision_governed_memory_support (
    memory_id UUID NOT NULL,
    episode_id UUID NOT NULL,
    producer_agent_id STRING NOT NULL,
    evidence_polarity STRING NOT NULL,
    PRIMARY KEY (memory_id, episode_id)
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

CREATE TABLE IF NOT EXISTS decision_memory_consolidation_outbox (
    scope_id STRING PRIMARY KEY,
    scope_level STRING NOT NULL CHECK (scope_level IN ('PRIVATE', 'TEAM', 'GLOBAL')),
    status STRING NOT NULL CHECK (status IN ('PENDING', 'RUNNING')),
    attempt_count INT8 NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    generation INT8 NOT NULL DEFAULT 1 CHECK (generation >= 1),
    next_attempt_at TIMESTAMPTZ NOT NULL,
    lease_until TIMESTAMPTZ,
    last_error_code STRING,
    requested_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS decision_memory_consolidation_outbox_due_idx
ON decision_memory_consolidation_outbox (status, next_attempt_at, requested_at);

CREATE UNIQUE INDEX IF NOT EXISTS decision_governed_memories_supersedes_uidx
ON decision_governed_memories (supersedes_memory_id)
WHERE supersedes_memory_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS decision_governed_memories_active_rule_uidx
ON decision_governed_memories (
    scope_id, rule_key, semantic_embedding_space
)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS decision_governed_memories_scope_observed_idx
ON decision_governed_memories (scope_id, observed_to DESC);

CREATE INDEX IF NOT EXISTS decision_governed_memory_support_episode_idx
ON decision_governed_memory_support (episode_id, memory_id);

CREATE VECTOR INDEX IF NOT EXISTS decision_governed_memories_scope_space_semantic_vec_idx
ON decision_governed_memories (
    scope_id,
    semantic_embedding_space,
    semantic_embedding vector_cosine_ops
);

CREATE TABLE IF NOT EXISTS decision_rate_limits (
    principal_id STRING NOT NULL,
    route_group STRING NOT NULL,
    bucket_epoch INT8 NOT NULL,
    request_count INT8 NOT NULL CHECK (request_count > 0),
    PRIMARY KEY (principal_id, route_group, bucket_epoch)
);

CREATE TABLE IF NOT EXISTS decision_memory_quality_decisions (
    decision_snapshot_id UUID PRIMARY KEY,
    source STRING NOT NULL CHECK (source IN ('AGENT_API', 'DEMO', 'BENCHMARK')),
    decided_at TIMESTAMPTZ NOT NULL,
    scope_level STRING NOT NULL CHECK (scope_level IN ('PRIVATE', 'TEAM', 'GLOBAL', 'UNKNOWN')),
    selected_strategy STRING,
    executable BOOL NOT NULL,
    memory_influenced BOOL NOT NULL,
    memory_resolution STRING NOT NULL,
    memory_conflict BOOL NOT NULL,
    quality_features JSONB NOT NULL,
    telemetry_revision STRING NOT NULL
);

CREATE INDEX IF NOT EXISTS decision_memory_quality_decisions_source_time_idx
ON decision_memory_quality_decisions (source, decided_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory_quality_outcomes (
    decision_snapshot_id UUID PRIMARY KEY,
    execution_receipt_id STRING NOT NULL UNIQUE,
    outcome STRING NOT NULL,
    effectiveness FLOAT8 NOT NULL CHECK (effectiveness >= 0 AND effectiveness <= 1),
    confidence FLOAT8 NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    telemetry_revision STRING NOT NULL
);

CREATE INDEX IF NOT EXISTS decision_memory_quality_outcomes_recorded_idx
ON decision_memory_quality_outcomes (recorded_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory_quality_calibration_runs (
    run_id UUID PRIMARY KEY,
    source STRING NOT NULL,
    calibration_revision STRING NOT NULL,
    lookback_days INT8 NOT NULL CHECK (lookback_days > 0),
    minimum_samples INT8 NOT NULL CHECK (minimum_samples > 0),
    minimum_success_retention FLOAT8 NOT NULL
        CHECK (minimum_success_retention >= 0 AND minimum_success_retention <= 1),
    maximum_harmful_rate FLOAT8 NOT NULL
        CHECK (maximum_harmful_rate >= 0 AND maximum_harmful_rate <= 1),
    decision_rows INT8 NOT NULL CHECK (decision_rows >= 0),
    labeled_outcomes INT8 NOT NULL CHECK (labeled_outcomes >= 0),
    observed_samples INT8 NOT NULL CHECK (observed_samples >= 0),
    champion_successes INT8 NOT NULL CHECK (champion_successes >= 0),
    champion_harmful INT8 NOT NULL CHECK (champion_harmful >= 0),
    recommendation STRING NOT NULL,
    recommended_profile STRING,
    challengers JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS decision_memory_quality_calibration_runs_time_idx
ON decision_memory_quality_calibration_runs (generated_at DESC);

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
