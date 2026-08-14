-- Production hardening v5: explicit embedding generation and event/record time.
-- IMPORTANT: CockroachDB schema changes become visible after commit. Apply this
-- file one statement per transaction (the companion
-- `apply_production_memory_v5.py` does this); do not wrap the whole file in one
-- transaction.
--
-- Existing `created_at` values represented observation/event time. They cannot
-- reconstruct the historical ingestion instant, so legacy rows conservatively
-- backfill both new columns from that value. New writes populate observed_at
-- from the verified receipt and recorded_at from the DecisionVault runtime.

ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;

ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;

UPDATE decision_episodes
SET observed_at = created_at
WHERE observed_at IS NULL;

UPDATE decision_episodes
SET recorded_at = created_at
WHERE recorded_at IS NULL;

-- Keep the expand migration compatible with still-warm pre-v5 Lambda
-- containers during the short deploy transition. v5 writers always provide
-- both values explicitly; these defaults are only a safety net for an older
-- writer that has not been drained yet.
ALTER TABLE decision_episodes
ALTER COLUMN observed_at SET DEFAULT now();

ALTER TABLE decision_episodes
ALTER COLUMN recorded_at SET DEFAULT now();

ALTER TABLE decision_episodes
ALTER COLUMN observed_at SET NOT NULL;

ALTER TABLE decision_episodes
ALTER COLUMN recorded_at SET NOT NULL;

ALTER TABLE decision_memory_heads
ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ;

ALTER TABLE decision_memory_heads
ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;

UPDATE decision_memory_heads
SET observed_at = created_at
WHERE observed_at IS NULL;

UPDATE decision_memory_heads
SET recorded_at = created_at
WHERE recorded_at IS NULL;

ALTER TABLE decision_memory_heads
ALTER COLUMN observed_at SET DEFAULT now();

ALTER TABLE decision_memory_heads
ALTER COLUMN recorded_at SET DEFAULT now();

ALTER TABLE decision_memory_heads
ALTER COLUMN observed_at SET NOT NULL;

ALTER TABLE decision_memory_heads
ALTER COLUMN recorded_at SET NOT NULL;

-- The old space label did not carry a provider generation. Mark it explicitly
-- as legacy/unversioned before current heads are re-embedded by
-- migrate_semantic_embedding_space.py into the configured revision.
UPDATE decision_episodes
SET semantic_embedding_space =
    'nvidia/nv-embedqa-e5-v5|revision=legacy-unversioned|dim=1024|contract=query-passage-v1'
WHERE semantic_embedding_space =
    'nvidia/nv-embedqa-e5-v5|dim=1024|contract=query-passage-v1';

UPDATE decision_memory_heads
SET semantic_embedding_space =
    'nvidia/nv-embedqa-e5-v5|revision=legacy-unversioned|dim=1024|contract=query-passage-v1'
WHERE semantic_embedding_space =
    'nvidia/nv-embedqa-e5-v5|dim=1024|contract=query-passage-v1';

CREATE INDEX IF NOT EXISTS decision_episodes_scope_observed_idx
ON decision_episodes (scope_id, observed_at DESC);
