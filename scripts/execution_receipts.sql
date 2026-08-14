-- Verified execution receipt / idempotency migration.
ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS execution_receipt_id STRING;

CREATE UNIQUE INDEX IF NOT EXISTS decision_episodes_execution_receipt_uidx
ON decision_episodes (execution_receipt_id)
WHERE execution_receipt_id IS NOT NULL;

ALTER TABLE decision_memory_heads
ADD COLUMN IF NOT EXISTS execution_receipt_id STRING;
