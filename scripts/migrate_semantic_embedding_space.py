from __future__ import annotations

import argparse
import os

from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import NvidiaSemanticEmbedder


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Re-embed current governed heads into the configured semantic "
            "embedding space without changing outcome/audit content."
        )
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NVIDIA_API_KEY is required")

    semantic = NvidiaSemanticEmbedder(
        api_key=api_key,
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
    )
    target_space = semantic.embedding_space
    factory = psycopg_connection_factory()
    conn = factory()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT scope_id, producer_agent_id, strategy,
                       episode_id::STRING, situation, semantic_embedding_space
                FROM decision_memory_heads
                WHERE semantic_embedding_space IS DISTINCT FROM %s
                ORDER BY scope_id, producer_agent_id, strategy
            """
            params: tuple[object, ...]
            if args.limit > 0:
                sql += " LIMIT %s"
                params = (target_space, args.limit)
            else:
                params = (target_space,)
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    print(f"target_embedding_space={target_space}")
    print(f"heads_requiring_migration={len(rows)}")
    if args.dry_run or not rows:
        print("semantic_embedding_space_migration=DRY_RUN" if args.dry_run else "semantic_embedding_space_migration=NOOP")
        return 0

    migrated = 0
    concurrent_skips = 0
    for scope_id, producer_agent_id, strategy, episode_id, situation, old_space in rows:
        vector = _vector_literal(semantic.embed_passage(str(situation)))
        conn = factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE decision_memory_heads
                    SET semantic_embedding = %s::VECTOR,
                        semantic_embedding_space = %s
                    WHERE scope_id = %s
                      AND producer_agent_id = %s
                      AND strategy = %s
                      AND episode_id = %s::UUID
                      AND semantic_embedding_space IS NOT DISTINCT FROM %s
                    RETURNING episode_id::STRING
                    """,
                    (
                        vector,
                        target_space,
                        scope_id,
                        producer_agent_id,
                        strategy,
                        episode_id,
                        old_space,
                    ),
                )
                if cur.fetchone() is None:
                    concurrent_skips += 1
                    conn.rollback()
                    continue
                cur.execute(
                    """
                    UPDATE decision_episodes
                    SET semantic_embedding = %s::VECTOR,
                        semantic_embedding_space = %s
                    WHERE episode_id = %s::UUID
                    """,
                    (vector, target_space, episode_id),
                )
            conn.commit()
            migrated += 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    print(f"heads_migrated={migrated}")
    print(f"concurrent_head_changes_skipped={concurrent_skips}")
    print("semantic_embedding_space_migration=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
