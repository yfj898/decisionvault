from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from typing import Callable

from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import NvidiaSemanticEmbedder


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


@dataclass(frozen=True, slots=True)
class MigrationResult:
    target_space: str
    heads_requiring_migration: int
    heads_migrated: int
    concurrent_head_changes_skipped: int


def migrate_current_heads(
    connection_factory: Callable[[], object],
    semantic: NvidiaSemanticEmbedder,
    *,
    dry_run: bool = False,
    limit: int = 0,
) -> MigrationResult:
    target_space = semantic.embedding_space
    conn = connection_factory()
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
            if limit > 0:
                sql += " LIMIT %s"
                params = (target_space, limit)
            else:
                params = (target_space,)
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    if dry_run or not rows:
        return MigrationResult(
            target_space=target_space,
            heads_requiring_migration=len(rows),
            heads_migrated=0,
            concurrent_head_changes_skipped=0,
        )

    migrated = 0
    concurrent_skips = 0
    for scope_id, producer_agent_id, strategy, episode_id, situation, old_space in rows:
        vector = _vector_literal(semantic.embed_passage(str(situation)))
        conn = connection_factory()
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

    return MigrationResult(
        target_space=target_space,
        heads_requiring_migration=len(rows),
        heads_migrated=migrated,
        concurrent_head_changes_skipped=concurrent_skips,
    )


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
        revision=os.getenv("NVIDIA_EMBED_REVISION", "").strip(),
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
    )
    factory = psycopg_connection_factory()
    result = migrate_current_heads(
        factory,
        semantic,
        dry_run=args.dry_run,
        limit=args.limit,
    )

    print(f"target_embedding_space={result.target_space}")
    print(f"heads_requiring_migration={result.heads_requiring_migration}")
    if args.dry_run or result.heads_requiring_migration == 0:
        print("semantic_embedding_space_migration=DRY_RUN" if args.dry_run else "semantic_embedding_space_migration=NOOP")
        return 0

    print(f"heads_migrated={result.heads_migrated}")
    print(f"concurrent_head_changes_skipped={result.concurrent_head_changes_skipped}")
    print("semantic_embedding_space_migration=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
