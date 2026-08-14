-- Typed / race-safe supersession migration.
ALTER TABLE decision_episodes
ADD COLUMN IF NOT EXISTS supersedes_episode_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS decision_episodes_supersedes_uidx
ON decision_episodes (supersedes_episode_id)
WHERE supersedes_episode_id IS NOT NULL;

ALTER TABLE decision_memory_heads
ADD COLUMN IF NOT EXISTS supersedes_episode_id UUID;
