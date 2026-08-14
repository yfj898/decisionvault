from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from uuid import uuid4

from decisionvault.agent.memory_governance import (
    PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    ConflictAwareMemoryResolver,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import NvidiaSemanticEmbedder, deterministic_text_embedding
from decisionvault.semantic_benchmark import production_semantic_cases, seed_episode


ROOT = Path(__file__).resolve().parents[1]


def _delete_prefix(connection_factory, prefix: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_memory_consolidation_outbox WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                """
                DELETE FROM decision_governed_memory_support
                WHERE memory_id IN (
                    SELECT memory_id FROM decision_governed_memories
                    WHERE scope_id LIKE %s
                )
                """,
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_governed_memories WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_memory_consolidation_candidates WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_strategy_effectiveness WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_memory_revocations WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_memory_heads WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "production-semantic-benchmark.json",
    )
    args = parser.parse_args()

    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("NVIDIA_API_KEY is required")
    runtime_database_url = os.getenv("DATABASE_URL", "").strip()
    cleanup_database_url = os.getenv(
        "DECISIONVAULT_CLEANUP_DATABASE_URL", runtime_database_url
    ).strip()
    if not runtime_database_url:
        raise SystemExit("DATABASE_URL is required")
    if not cleanup_database_url:
        raise SystemExit("DECISIONVAULT_CLEANUP_DATABASE_URL is required")

    run_prefix = f"semantic-prod-{uuid4().hex[:10]}"
    connection_factory = psycopg_connection_factory(runtime_database_url)
    cleanup_connection_factory = psycopg_connection_factory(cleanup_database_url)
    semantic = NvidiaSemanticEmbedder(
        api_key=api_key,
        revision=os.getenv("NVIDIA_EMBED_REVISION", "").strip(),
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
    )
    store = CockroachVectorMemoryStore(
        connection_factory=connection_factory,
        embedder=deterministic_text_embedding,
        semantic_embedder=semantic.embed_passage,
        semantic_query_embedder=semantic.embed_query,
        semantic_embedding_space=semantic.embedding_space,
    )
    policy = OutcomeAwarePolicy(
        resolver=ConflictAwareMemoryResolver(
            minimum_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY
        )
    )
    results = []
    _delete_prefix(cleanup_connection_factory, run_prefix)
    try:
        for case_index, case in enumerate(production_semantic_cases()):
            query_scope = f"{run_prefix}-{case.case_id}"
            episode_ids: list[str] = []
            for seed_index, seed in enumerate(case.seeds):
                scope_id = (
                    query_scope
                    if seed.scope == "query"
                    else f"{query_scope}-foreign"
                )
                episode_id = str(uuid4())
                supersedes = (
                    episode_ids[seed.supersedes_seed_index]
                    if seed.supersedes_seed_index is not None
                    else None
                )
                store.save(
                    seed_episode(
                        episode_id=episode_id,
                        scope_id=scope_id,
                        seed=seed,
                        supersedes_episode_id=supersedes,
                    )
                )
                episode_ids.append(episode_id)

            recalled = store.recall_governed(
                scope_id=query_scope,
                situation=case.query,
                minimum_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY,
            )
            decision = policy.decide(recalled=recalled)
            off = policy.decide(recalled=[])
            matches = (
                decision.strategy == case.expected_strategy
                and decision.action == case.expected_action
                and decision.memory_influenced == case.expected_influenced
                and (case.expected_resolution is None or decision.memory_resolution == case.expected_resolution)
                and (case.expected_conflict is None or decision.memory_conflict == case.expected_conflict)
                and (
                    case.expected_producer is None
                    or case.expected_producer in decision.recalled_producer_agent_ids
                )
                and off.strategy == Strategy.GENERIC_RETRY
                and not off.memory_influenced
            )
            results.append(
                {
                    "case_id": case.case_id,
                    "family": case.family,
                    "expected_strategy": (
                        case.expected_strategy.value
                        if case.expected_strategy is not None
                        else None
                    ),
                    "expected_action": case.expected_action.value,
                    "actual_strategy": (
                        decision.strategy.value if decision.strategy is not None else None
                    ),
                    "actual_action": decision.action.value,
                    "executable": decision.executable,
                    "memory_influenced": decision.memory_influenced,
                    "resolution": decision.memory_resolution,
                    "conflict": decision.memory_conflict,
                    "recalled_count": len(recalled),
                    "top_similarity": recalled[0].similarity if recalled else None,
                    "recalled_producers": list(decision.recalled_producer_agent_ids),
                    "passed": matches,
                }
            )
            print(
                f"{case.case_id}: strategy="
                f"{decision.strategy.value if decision.strategy is not None else 'NONE'} "
                f"action={decision.action.value} "
                f"influenced={decision.memory_influenced} "
                f"resolution={decision.memory_resolution} "
                f"top_similarity={recalled[0].similarity:.4f} "
                if recalled
                else f"{case.case_id}: no_recall",
                flush=True,
            )

        passed = sum(item["passed"] for item in results)
        benefit = [
            item
            for item in results
            if item["family"]
            in {
                "failed_generic_adaptation",
                "successful_refresh_reuse",
                "successful_billing_reuse",
            }
        ]
        controls = [item for item in results if item not in benefit]
        payload = {
            "benchmark": "decisionvault-production-semantic-conformance",
            "embedding_model": semantic.model_id,
            "embedding_revision": semantic.revision,
            "embedding_space": semantic.embedding_space,
            "embedding_dimensions": semantic.expected_dimensions,
            "storage": "decision_memory_heads.semantic_embedding VECTOR(1024)",
            "cases_are_hand_authored": True,
            "summary": {
                "total_cases": len(results),
                "passed_cases": passed,
                "pass_rate": passed / len(results),
                "benefit_cases": len(benefit),
                "benefit_pass_rate": sum(item["passed"] for item in benefit) / len(benefit),
                "control_cases": len(controls),
                "control_pass_rate": sum(item["passed"] for item in controls) / len(controls),
            },
            "cases": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"total_cases={len(results)} passed_cases={passed}")
        print(f"production_semantic_benchmark={'PASS' if passed == len(results) else 'FAIL'}")
        if passed != len(results):
            return 2
        return 0
    finally:
        _delete_prefix(cleanup_connection_factory, run_prefix)


if __name__ == "__main__":
    raise SystemExit(main())
