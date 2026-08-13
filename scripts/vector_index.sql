-- Phase 3: CockroachDB Distributed Vector Index.
--
-- scope_id is a prefix column because DecisionVault memory is always isolated
-- by scope before semantic ranking. The cosine opclass matches the <=> operator
-- used by CockroachVectorMemoryStore.recall().
CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx
ON decision_episodes (scope_id, embedding vector_cosine_ops);
