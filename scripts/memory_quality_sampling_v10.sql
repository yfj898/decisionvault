-- DecisionVault memory-quality sampling/retention v10.
--
-- Calibration runs gain an aggregate sampling-bias audit. Raw telemetry
-- remains append-only for request runtime; only the separately authenticated
-- consolidator receives DELETE for bounded retention maintenance.

ALTER TABLE decision_memory_quality_calibration_runs
ADD COLUMN IF NOT EXISTS sampling_gate_pass BOOL NOT NULL DEFAULT false;

ALTER TABLE decision_memory_quality_calibration_runs
ADD COLUMN IF NOT EXISTS sampling_audit JSONB NOT NULL DEFAULT '{}'::JSONB;

GRANT DELETE
ON TABLE decision_memory_quality_decisions,
         decision_memory_quality_outcomes,
         decision_memory_quality_calibration_runs
TO decisionvault_consolidator;
