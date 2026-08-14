-- Governed Adaptive Memory v7 expand phase.
-- Safe to apply while the v6 Lambda still uses decisionvault_runtime for
-- consolidation. This phase only adds the durable outbox and a separately
-- permissioned consolidator identity; it does not revoke runtime privileges.

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

ALTER TABLE decision_memory_consolidation_outbox
ADD COLUMN IF NOT EXISTS generation INT8 NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS decision_memory_consolidation_outbox_due_idx
ON decision_memory_consolidation_outbox (status, next_attempt_at, requested_at);

CREATE USER IF NOT EXISTS decisionvault_consolidator;

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
