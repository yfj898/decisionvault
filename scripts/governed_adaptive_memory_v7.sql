-- Governed Adaptive Memory v7 complete target state.
-- Production in-place rollout MUST apply v7_expand before deployment and
-- v7_contract only after the new Lambda confirms consolidator identity isolation.

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

CREATE USER IF NOT EXISTS decisionvault_consolidator;

REVOKE INSERT, UPDATE, DELETE
ON TABLE decision_memory_consolidation_candidates
FROM decisionvault_runtime;

REVOKE INSERT, UPDATE, DELETE
ON TABLE decision_strategy_effectiveness
FROM decisionvault_runtime;

REVOKE INSERT, DELETE
ON TABLE decision_governed_memories
FROM decisionvault_runtime;

REVOKE INSERT, UPDATE, DELETE
ON TABLE decision_governed_memory_support
FROM decisionvault_runtime;

GRANT SELECT, UPDATE
ON TABLE decision_governed_memories
TO decisionvault_runtime;

GRANT SELECT
ON TABLE decision_memory_consolidation_candidates,
         decision_strategy_effectiveness,
         decision_governed_memory_support
TO decisionvault_runtime;

GRANT SELECT, INSERT, UPDATE
ON TABLE decision_memory_consolidation_outbox
TO decisionvault_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_memory_consolidation_candidates,
         decision_strategy_effectiveness,
         decision_governed_memories,
         decision_governed_memory_support
TO decisionvault_consolidator;

GRANT SELECT, UPDATE
ON TABLE decision_memory_heads
TO decisionvault_consolidator;

GRANT SELECT
ON TABLE decision_episodes,
         decision_memory_revocations
TO decisionvault_consolidator;

GRANT SELECT, UPDATE, DELETE
ON TABLE decision_memory_consolidation_outbox
TO decisionvault_consolidator;
