from __future__ import annotations


PRODUCTION_ANN_LIMIT = 32


def semantic_ann_sql(
    *,
    vector_expr: str,
    scope_expr: str,
    space_expr: str,
    limit_expr: str = str(PRODUCTION_ANN_LIMIT),
) -> str:
    """Return the exact DVI-compatible production ANN query shape.

    CockroachDB currently abandons the Distributed Vector Index when lifecycle,
    outcome, or revocation filters are pushed into the same top-k vector query.
    Those governance conditions therefore belong to the separate correctness
    coverage query and the resolver, not this DVI fast path.
    """

    return f"""
        SELECT h.episode_id::STRING, h.scope_id, h.situation, h.strategy,
               h.outcome, h.effectiveness, h.confidence, h.evidence,
               h.observed_at, h.recorded_at,
               h.semantic_embedding <=> {vector_expr} AS cosine_distance
        FROM decision_memory_heads h
        WHERE h.scope_id = {scope_expr}
          AND h.semantic_embedding_space = {space_expr}
        ORDER BY h.semantic_embedding <=> {vector_expr}
        LIMIT {limit_expr}
    """


def semantic_coverage_sql(
    *,
    vector_expr: str,
    scope_expr: str,
    space_expr: str,
    max_distance_expr: str,
) -> str:
    """Return the exact unbounded governance-coverage production query."""

    return f"""
        SELECT h.episode_id::STRING, h.scope_id, h.situation, h.strategy,
               h.outcome, h.effectiveness, h.confidence, h.evidence,
               h.observed_at, h.recorded_at,
               h.semantic_embedding <=> {vector_expr} AS cosine_distance
        FROM decision_memory_heads h
        WHERE h.scope_id = {scope_expr}
          AND h.semantic_embedding_space = {space_expr}
          AND NOT EXISTS (
            SELECT 1 FROM decision_memory_revocations r
            WHERE r.scope_id = h.scope_id AND r.episode_id = h.episode_id
          )
          AND COALESCE(upper(h.evidence->>'memory_status'), 'ACTIVE') <> 'REVOKED'
          AND (
            COALESCE(lower(h.evidence->>'pinned'), 'false') = 'true'
            OR h.observed_at >= now() - INTERVAL '90 days'
          )
          AND (
            (h.outcome = 'SUCCESS' AND h.effectiveness >= 0.7)
            OR (h.outcome = 'FAILED' AND h.confidence >= 0.6)
          )
          AND h.semantic_embedding <=> {vector_expr} <= {max_distance_expr}
        ORDER BY cosine_distance
    """


def adaptive_semantic_ann_sql(
    *,
    vector_expr: str,
    scope_expr: str,
    space_expr: str,
    limit_expr: str = str(PRODUCTION_ANN_LIMIT),
) -> str:
    """DVI fast path for promoted L2/L3 memories."""

    return f"""
        SELECT m.memory_id::STRING, m.candidate_id::STRING, m.scope_id,
               m.scope_level, m.memory_type, m.polarity, m.situation_class,
               m.preconditions, m.exclusions, m.intervention,
               m.expected_outcome, m.supporting_episode_ids, m.producer_set,
               m.positive_episode_ids, m.negative_episode_ids, m.confidence,
               m.observed_from, m.observed_to, m.created_at, m.recorded_at,
               m.governance_revision, m.semantic_embedding_space,
               m.memory_class, m.expires_at, m.status,
               m.supersedes_memory_id::STRING, m.revoked_at,
               m.revocation_reason,
               m.semantic_embedding <=> {vector_expr} AS cosine_distance
        FROM decision_governed_memories m
        WHERE m.scope_id = {scope_expr}
          AND m.semantic_embedding_space = {space_expr}
        ORDER BY m.semantic_embedding <=> {vector_expr}
        LIMIT {limit_expr}
    """


def adaptive_semantic_coverage_sql(
    *,
    vector_expr: str,
    scope_expr: str,
    space_expr: str,
    governance_revision_expr: str,
    max_distance_expr: str,
) -> str:
    """Exact governed coverage for promoted L2/L3 memories."""

    return f"""
        SELECT m.memory_id::STRING, m.candidate_id::STRING, m.scope_id,
               m.scope_level, m.memory_type, m.polarity, m.situation_class,
               m.preconditions, m.exclusions, m.intervention,
               m.expected_outcome, m.supporting_episode_ids, m.producer_set,
               m.positive_episode_ids, m.negative_episode_ids, m.confidence,
               m.observed_from, m.observed_to, m.created_at, m.recorded_at,
               m.governance_revision, m.semantic_embedding_space,
               m.memory_class, m.expires_at, m.status,
               m.supersedes_memory_id::STRING, m.revoked_at,
               m.revocation_reason,
               m.semantic_embedding <=> {vector_expr} AS cosine_distance
        FROM decision_governed_memories m
        WHERE m.scope_id = {scope_expr}
          AND m.semantic_embedding_space = {space_expr}
          AND m.governance_revision = {governance_revision_expr}
          AND m.status = 'ACTIVE'
          AND (m.expires_at IS NULL OR m.expires_at >= now())
          AND NOT EXISTS (
            SELECT 1
            FROM decision_governed_memory_support s
            WHERE s.memory_id = m.memory_id
              AND NOT EXISTS (
                SELECT 1
                FROM decision_memory_heads h
                WHERE h.scope_id = m.scope_id
                  AND h.episode_id = s.episode_id
                  AND h.semantic_embedding_space = m.semantic_embedding_space
              )
          )
          AND m.semantic_embedding <=> {vector_expr} <= {max_distance_expr}
        ORDER BY cosine_distance
    """
