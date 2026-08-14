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
               h.created_at,
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
               h.created_at,
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
            OR h.created_at >= now() - INTERVAL '90 days'
          )
          AND (
            (h.outcome = 'SUCCESS' AND h.effectiveness >= 0.7)
            OR (h.outcome = 'FAILED' AND h.confidence >= 0.6)
          )
          AND h.semantic_embedding <=> {vector_expr} <= {max_distance_expr}
        ORDER BY cosine_distance
    """
