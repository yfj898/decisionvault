-- DecisionVault memory-quality telemetry v8.
-- No situation text, scope identifiers, agent identifiers, producer IDs,
-- tokens, or model text are persisted here. Decision and outcome rows are
-- append-only from the request runtime's perspective.

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

GRANT SELECT, INSERT
ON TABLE decision_memory_quality_decisions,
         decision_memory_quality_outcomes
TO decisionvault_runtime;

GRANT SELECT
ON TABLE decision_memory_quality_decisions,
         decision_memory_quality_outcomes
TO decisionvault_consolidator;
