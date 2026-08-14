-- Governed Adaptive Memory v7 contract phase.
-- Apply only after the Lambda has switched adaptive consolidation to the
-- decisionvault_consolidator identity and readiness confirms identity isolation.

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
