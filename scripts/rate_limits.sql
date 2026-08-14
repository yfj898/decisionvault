CREATE TABLE IF NOT EXISTS decision_rate_limits (
    principal_id STRING NOT NULL,
    route_group STRING NOT NULL,
    bucket_epoch INT8 NOT NULL,
    request_count INT8 NOT NULL CHECK (request_count > 0),
    PRIMARY KEY (principal_id, route_group, bucket_epoch)
);

GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE decision_rate_limits
TO decisionvault_runtime;
