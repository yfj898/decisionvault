-- DecisionVault memory-quality calibration v9.
-- Append-only aggregate artifacts for scheduled champion/challenger evaluation.

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

GRANT SELECT, INSERT
ON TABLE decision_memory_quality_calibration_runs
TO decisionvault_runtime;

GRANT SELECT
ON TABLE decision_memory_quality_calibration_runs
TO decisionvault_consolidator;
